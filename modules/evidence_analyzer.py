"""
Evidence Analyzer Module for SkillTrace.
Runs multi-tier detectors across repository files to identify Strong, Corroborating, and Weak signals.
Enforces exclusions for vendored and generated files (SRS Section 4.3 FR-10 to FR-16, Section 8.2).
"""
import re
import uuid
from typing import List, Dict, Any, Optional
import yaml
from pathlib import Path

from config import settings


class EvidenceAnalyzer:
    def __init__(self, taxonomy_path: Optional[str] = None):
        self.taxonomy_path = Path(taxonomy_path or settings.taxonomy_file)
        self.skills = self._load_taxonomy()

    def _load_taxonomy(self) -> List[Dict[str, Any]]:
        """Loads skill taxonomy and detector patterns."""
        if not self.taxonomy_path.exists():
            return []
        with open(self.taxonomy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("skills", [])

    def is_excluded_path(self, file_path: str) -> bool:
        """
        Filters out vendored directories, build artifacts, and lockfiles (FR-15, TC-06).
        """
        normalized = file_path.lower().replace("\\", "/")
        parts = normalized.split("/")

        # Check parent folder names
        for folder in parts[:-1]:
            if folder in settings.vendor_directories or folder.startswith(".git"):
                return True

        filename = parts[-1]
        # Check generated lockfiles and minified files
        for pattern in settings.generated_file_patterns:
            if filename == pattern or filename.endswith(pattern):
                return True

        return False

    def analyze_file(
        self,
        file_path: str,
        content: str,
        repo_id: str,
        repo_full_name: str,
        commit_sha: str,
        target_skill_ids: Optional[List[str]] = None,
        authored_by_student: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Scans a single file against the skill taxonomy detectors.
        Catches errors per-file to ensure one faulty detector doesn't abort the run (Section 8.4).
        """
        if self.is_excluded_path(file_path):
            return []

        evidence_records: List[Dict[str, Any]] = []
        filename = Path(file_path).name
        ext = Path(file_path).suffix.lower()
        is_readme = filename.lower() in ("readme.md", "readme.rst", "readme.txt", "readme")
        is_test_file = bool(re.search(r"(^test_|_test\.|/\btests?\b/|\.spec\.|\.test\.)", file_path, re.I))
        is_ci_file = bool(re.search(r"(\.github/workflows/|\.gitlab-ci|jenkinsfile)", file_path, re.I))
        is_manifest = filename in (
            "requirements.txt", "setup.py", "pyproject.toml", "Pipfile",
            "package.json", "pom.xml", "build.gradle", "go.mod", "Cargo.toml", "Gemfile"
        )

        lines = content.splitlines()

        for skill in self.skills:
            skill_id = skill["skill_id"]
            if target_skill_ids and skill_id not in target_skill_ids:
                continue

            try:
                # ---------------- 1. STRONG SIGNALS ----------------
                strong = skill.get("strong_patterns", {})
                strong_exts = strong.get("file_extensions", [])
                strong_names = strong.get("file_names", [])
                strong_regexes = strong.get("code_regex", [])

                # Dedicated artifact match (e.g. .sql files, Dockerfile, etc.)
                if not is_readme and not is_test_file:
                    if ext and ext in strong_exts and ext != ".py": # Dedicated extension like .sql or .tsx
                        first_line = lines[0] if lines else ""
                        evidence_records.append(self._create_evidence(
                            repo_id=repo_id,
                            repo_full_name=repo_full_name,
                            skill_id=skill_id,
                            file_path=file_path,
                            line_start=1,
                            line_end=min(10, len(lines)),
                            commit_sha=commit_sha,
                            signal_type="dedicated_artifact",
                            strength="Strong",
                            excerpt="\n".join(lines[:10]),
                            authored=authored_by_student
                        ))
                    elif filename in strong_names:
                        evidence_records.append(self._create_evidence(
                            repo_id=repo_id,
                            repo_full_name=repo_full_name,
                            skill_id=skill_id,
                            file_path=file_path,
                            line_start=1,
                            line_end=min(10, len(lines)),
                            commit_sha=commit_sha,
                            signal_type="dedicated_artifact",
                            strength="Strong",
                            excerpt="\n".join(lines[:10]),
                            authored=authored_by_student
                        ))

                # Source usage match (concrete code pattern)
                if not is_readme and not is_manifest:
                    for reg in strong_regexes:
                        for idx, line in enumerate(lines, start=1):
                            if re.search(reg, line):
                                # Grab context
                                ctx_start = max(1, idx - 1)
                                ctx_end = min(len(lines), idx + 2)
                                ctx_snippet = "\n".join(lines[ctx_start - 1:ctx_end])
                                evidence_records.append(self._create_evidence(
                                    repo_id=repo_id,
                                    repo_full_name=repo_full_name,
                                    skill_id=skill_id,
                                    file_path=file_path,
                                    line_start=ctx_start,
                                    line_end=ctx_end,
                                    commit_sha=commit_sha,
                                    signal_type="source_usage",
                                    strength="Strong",
                                    excerpt=ctx_snippet,
                                    authored=authored_by_student
                                ))
                                break  # One strong signal per file per regex is sufficient

                # ---------------- 2. CORROBORATING SIGNALS ----------------
                corroborating = skill.get("corroborating_patterns", {})

                # Manifest dependencies (requirements.txt, package.json, etc.)
                if is_manifest:
                    deps = corroborating.get("manifest_dependencies", [])
                    for dep in deps:
                        dep_pattern = r"(?i)(^|\"|'|\b)" + re.escape(dep) + r"(\b|\"|'|==|>=|<=|\n|$)"
                        for idx, line in enumerate(lines, start=1):
                            if re.search(dep_pattern, line):
                                evidence_records.append(self._create_evidence(
                                    repo_id=repo_id,
                                    repo_full_name=repo_full_name,
                                    skill_id=skill_id,
                                    file_path=file_path,
                                    line_start=idx,
                                    line_end=idx,
                                    commit_sha=commit_sha,
                                    signal_type="manifest_dependency",
                                    strength="Corroborating",
                                    excerpt=line.strip(),
                                    authored=authored_by_student
                                ))
                                break

                # Tests or CI pipelines
                if is_test_file or is_ci_file:
                    signal_type = "ci_step" if is_ci_file else "test"
                    # Check if test file or CI touches skill aliases or strong patterns
                    aliases = [skill["name"]] + skill.get("aliases", [])
                    for idx, line in enumerate(lines, start=1):
                        if any(re.search(r"\b" + re.escape(a) + r"\b", line, re.I) for a in aliases):
                            evidence_records.append(self._create_evidence(
                                repo_id=repo_id,
                                repo_full_name=repo_full_name,
                                skill_id=skill_id,
                                file_path=file_path,
                                line_start=max(1, idx - 1),
                                line_end=min(len(lines), idx + 2),
                                commit_sha=commit_sha,
                                signal_type=signal_type,
                                strength="Corroborating",
                                excerpt="\n".join(lines[max(0, idx - 2):min(len(lines), idx + 1)]),
                                authored=authored_by_student
                            ))
                            break

                # ---------------- 3. WEAK SIGNALS ----------------
                # README mentions and topic tags
                if is_readme:
                    weak = skill.get("weak_patterns", {})
                    keywords = weak.get("readme_keywords", [])
                    for kw in keywords:
                        for idx, line in enumerate(lines, start=1):
                            if re.search(r"\b" + re.escape(kw) + r"\b", line, re.I):
                                evidence_records.append(self._create_evidence(
                                    repo_id=repo_id,
                                    repo_full_name=repo_full_name,
                                    skill_id=skill_id,
                                    file_path=file_path,
                                    line_start=idx,
                                    line_end=idx,
                                    commit_sha=commit_sha,
                                    signal_type="doc_mention",
                                    strength="Weak",
                                    excerpt=line.strip(),
                                    authored=authored_by_student
                                ))
                                break

            except Exception:
                # Detector fault tolerance: do not halt other skill detectors (SRS Section 8.4)
                continue

        return evidence_records

    def _create_evidence(
        self,
        repo_id: str,
        repo_full_name: str,
        skill_id: str,
        file_path: str,
        line_start: int,
        line_end: int,
        commit_sha: str,
        signal_type: str,
        strength: str,
        excerpt: str,
        authored: bool = True
    ) -> Dict[str, Any]:
        """Helper to assemble a validated evidence dictionary with GitHub permalink."""
        line_ref = f"#L{line_start}-L{line_end}" if line_start != line_end else f"#L{line_start}"
        permalink = f"https://github.com/{repo_full_name}/blob/{commit_sha}/{file_path}{line_ref}"

        return {
            "evidence_id": str(uuid.uuid4()),
            "repo_id": repo_id,
            "skill_id": skill_id,
            "file_path": file_path,
            "line_start": line_start,
            "line_end": line_end,
            "commit_sha": commit_sha,
            "signal_type": signal_type,
            "strength": strength,
            "excerpt": excerpt[:300],  # bounded excerpt length
            "permalink": permalink,
            "authored_by_student": 1 if authored else 0,
            "status": "active"
        }
