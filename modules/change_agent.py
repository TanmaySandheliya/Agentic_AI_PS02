"""
Change Detection Agent for SkillTrace.
Implements GitHub Webhook verification (HMAC-SHA256), polling fallback worker,
affected-skill mapping, and incremental reassessment pipeline.
Adheres to SRS Section 4.5 (FR-21 to FR-29) and Section 8.3.
"""
import hmac
import hashlib
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
import yaml
from pathlib import Path

from config import settings
from modules import storage
from modules.evidence_analyzer import EvidenceAnalyzer
from modules.assessment_engine import AssessmentEngine
from modules.github_client import GitHubClient

logger = logging.getLogger("skilltrace.change_agent")


def verify_webhook_signature(payload_bytes: bytes, signature_header: Optional[str], secret: Optional[str] = None) -> bool:
    """
    Validates GitHub HMAC-SHA256 signature using constant-time comparison (SRS FR-22, TC-07).
    """
    if not signature_header:
        return False

    expected_secret = secret or settings.webhook_secret
    if not expected_secret:
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False

    given_hash = signature_header[len(prefix):]
    mac = hmac.new(expected_secret.encode("utf-8"), msg=payload_bytes, digestmod=hashlib.sha256)
    expected_hash = mac.hexdigest()

    return hmac.compare_digest(given_hash, expected_hash)


class ChangeAgent:
    def __init__(self, github_client: Optional[GitHubClient] = None):
        self.gh_client = github_client or GitHubClient()
        self.analyzer = EvidenceAnalyzer()
        self.assessment_engine = AssessmentEngine()
        self.skills = self._load_taxonomy()

    def _load_taxonomy(self) -> List[Dict[str, Any]]:
        tax_path = Path(settings.taxonomy_file)
        if not tax_path.exists():
            return []
        with open(tax_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("skills", [])

    def compute_affected_skills(
        self,
        repo_id: str,
        changed_files: List[Dict[str, Any]],
        file_contents: Optional[Dict[str, str]] = None
    ) -> List[str]:
        """
        Determines which skills are affected by the changed files (SRS FR-25).
        1. Skills with existing active evidence in changed or removed files.
        2. Skills whose detectors match added or modified files or manifests.
        """
        affected = set()
        changed_paths = {f["filename"] for f in changed_files}

        # 1. Existing active evidence residing in any of the changed paths
        conn = storage.get_connection()
        placeholders = ",".join("?" for _ in changed_paths) if changed_paths else "''"
        if changed_paths:
            rows = conn.execute(
                f"SELECT DISTINCT skill_id FROM evidence WHERE repo_id = ? AND file_path IN ({placeholders}) AND status = 'active'",
                [repo_id] + list(changed_paths)
            ).fetchall()
            for r in rows:
                affected.add(r["skill_id"])
        conn.close()

        # 2. Match detectors against changed filenames and extensions
        for f in changed_files:
            fname = Path(f["filename"]).name
            fext = Path(f["filename"]).suffix.lower()
            is_manifest = fname in ("requirements.txt", "package.json", "setup.py", "pyproject.toml")

            for skill in self.skills:
                sid = skill["skill_id"]
                strong = skill.get("strong_patterns", {})

                # Check extension/name match
                if fext and fext in strong.get("file_extensions", []):
                    affected.add(sid)
                elif fname in strong.get("file_names", []):
                    affected.add(sid)

                # If manifest changed, check if skill defines dependencies
                if is_manifest and skill.get("corroborating_patterns", {}).get("manifest_dependencies"):
                    affected.add(sid)

                # If file content is available, run regex quick-scan
                if file_contents and f["filename"] in file_contents:
                    content = file_contents[f["filename"]]
                    for reg in strong.get("code_regex", []):
                        import re
                        if re.search(reg, content):
                            affected.add(sid)
                            break

        return list(affected)

    def process_change_event(
        self,
        repo_full_name: str,
        before_sha: str,
        after_sha: str,
        changed_files_info: List[Dict[str, Any]],
        delivery_id: str,
        source: str = "webhook",
        file_contents: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Executes the Reassessment Algorithm (SRS Section 8.3).
        """
        # Idempotency check (FR-29)
        if storage.is_event_processed(delivery_id):
            logger.info("Event %s already processed. Skipping.", delivery_id)
            return {"status": "skipped", "reason": "duplicate delivery", "delivery_id": delivery_id}

        repo = storage.get_repository_by_name(repo_full_name)
        if not repo:
            logger.warning("Repository %s not tracked in database.", repo_full_name)
            return {"status": "skipped", "reason": "untracked repository"}

        repo_id = repo["repo_id"]
        student_id = repo["student_id"]
        changed_paths = [f["filename"] for f in changed_files_info]

        # Compute affected skills
        affected_skill_ids = self.compute_affected_skills(repo_id, changed_files_info, file_contents)
        logger.info("Change in %s affected skills: %s", repo_full_name, affected_skill_ids)

        reassessment_results = []

        if affected_skill_ids:
            # Mark superseded evidence for removed or modified files (FR-26)
            superseded_count = storage.mark_evidence_superseded(repo_id, changed_paths)

            # Analyze changed files that are added or modified
            new_evidence_batch = []
            for f in changed_files_info:
                if f.get("status") in ("added", "modified", "renamed", "copied"):
                    fpath = f["filename"]

                    # Fetch content if not provided
                    content = None
                    if file_contents and fpath in file_contents:
                        content = file_contents[fpath]
                    else:
                        content = self.gh_client.get_file_content(repo_full_name, fpath, after_sha)

                    if content:
                        found_ev = self.analyzer.analyze_file(
                            file_path=fpath,
                            content=content,
                            repo_id=repo_id,
                            repo_full_name=repo_full_name,
                            commit_sha=after_sha,
                            target_skill_ids=affected_skill_ids
                        )
                        new_evidence_batch.extend(found_ev)

            if new_evidence_batch:
                storage.save_evidence_batch(new_evidence_batch)

            # Reassess each affected skill
            scope_summary = f"repo: {repo_full_name}, branch: {repo.get('tracked_branch', 'main')}, commit: {after_sha[:7]}"

            # Fetch latest previous assessments for comparison
            prev_assessments = {
                a["skill_id"]: a for a in storage.get_latest_assessments(student_id)
            }

            for sid in affected_skill_ids:
                skill_obj = next((s for s in self.skills if s["skill_id"] == sid), None)
                sname = skill_obj["name"] if skill_obj else sid.title()

                active_ev = storage.get_active_evidence_for_student(student_id, skill_id=sid)
                eval_res = self.assessment_engine.evaluate_skill(
                    skill_id=sid,
                    skill_name=sname,
                    evidence_list=active_ev,
                    scope_summary=scope_summary
                )

                old_state = prev_assessments.get(sid, {}).get("state", "Not evaluated")
                new_state = eval_res["state"]

                # Save new immutable assessment version (FR-27)
                saved = storage.save_assessment(
                    student_id=student_id,
                    skill_id=sid,
                    state=new_state,
                    confidence=eval_res["confidence"],
                    scope_summary=scope_summary,
                    rationale=eval_res["rationale"],
                    trigger_sha=after_sha,
                    previous_state=old_state
                )

                reassessment_results.append({
                    "skill_id": sid,
                    "skill_name": sname,
                    "previous_state": old_state,
                    "new_state": new_state,
                    "confidence": eval_res["confidence"],
                    "changed": old_state != new_state
                })

        # Update repository last_analysed_sha
        storage.upsert_repository(
            student_id=student_id,
            full_name=repo_full_name,
            last_analysed_sha=after_sha
        )

        # Record event in audit log (FR-29)
        storage.record_event(
            delivery_id=delivery_id,
            source=source,
            repo_id=repo_id,
            before_sha=before_sha,
            after_sha=after_sha,
            changed_files=changed_paths,
            affected_skills=affected_skill_ids,
            status="processed"
        )

        return {
            "status": "processed",
            "repo": repo_full_name,
            "after_sha": after_sha,
            "affected_skills": affected_skill_ids,
            "reassessments": reassessment_results
        }
