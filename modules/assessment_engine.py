"""
Assessment Engine Module for SkillTrace.
Implements the Evidence Rubric and Confidence Scoring defined in SRS Section 8.2.
"""
from typing import List, Dict, Any, Optional, Tuple


class AssessmentEngine:
    def __init__(self):
        pass

    def evaluate_skill(
        self,
        skill_id: str,
        skill_name: str,
        evidence_list: List[Dict[str, Any]],
        scope_summary: str,
        is_code_assessable: bool = True
    ) -> Dict[str, Any]:
        """
        Applies Section 8.2 Evidence Rubric to compute:
        - state: Demonstrated | Partially demonstrated | Not demonstrated in this scope | Not assessable from code
        - confidence: High | Medium | Low
        - rationale: Plain-language explanation
        """
        # 1. Non-assessable requirements
        if not is_code_assessable:
            return {
                "skill_id": skill_id,
                "state": "Not assessable from code",
                "confidence": "High",
                "scope_summary": scope_summary,
                "rationale": "Requirement is not observable in code repositories (e.g., degree, oral communication, or behavioral trait)."
            }

        # Filter to active evidence
        active = [e for e in evidence_list if e.get("status", "active") == "active"]

        strong_signals = [e for e in active if e.get("strength") == "Strong"]
        corrob_signals = [e for e in active if e.get("strength") == "Corroborating"]
        weak_signals = [e for e in active if e.get("strength") == "Weak"]

        # 2. Check for Demonstrated:
        # "At least one Strong signal in student-authored, non-vendored code AND at least one additional
        # Strong or Corroborating signal (a second file, a test, or a manifest dependency)"
        if len(strong_signals) >= 1 and (len(strong_signals) >= 2 or len(corrob_signals) >= 1):
            state = "Demonstrated"

            # Confidence calculation
            # High: 2+ strong signals or strong + corroborating with confirmed authorship
            has_student_author = any(e.get("authored_by_student", 1) == 1 for e in strong_signals)
            if len(strong_signals) >= 2 or (len(corrob_signals) >= 1 and has_student_author):
                confidence = "High"
            else:
                confidence = "Medium"

            details = []
            files_seen = {e["file_path"] for e in strong_signals}
            details.append(f"{len(strong_signals)} Strong signal(s) across files ({', '.join(list(files_seen)[:3])})")
            if corrob_signals:
                c_types = {e.get("signal_type") for e in corrob_signals}
                details.append(f"{len(corrob_signals)} Corroborating signal(s) ({', '.join(c_types)})")

            rationale = (
                f"Demonstrated in codebase: Found {'; '.join(details)}. "
                f"Meets multi-tier verification rubric (at least 1 Strong + 1 additional Strong/Corroborating signal)."
            )

        # 3. Check for Partially demonstrated:
        # "Exactly one Strong signal with no corroboration, OR only Corroborating signals"
        elif len(strong_signals) == 1 or len(corrob_signals) >= 1:
            state = "Partially demonstrated"

            if len(strong_signals) == 1:
                confidence = "Medium"
                s = strong_signals[0]
                rationale = (
                    f"Partially demonstrated: Single Strong signal found in {s['file_path']} "
                    f"without secondary corroboration (e.g. manifest dependency or automated test layer)."
                )
            else:
                confidence = "Medium" if len(corrob_signals) >= 2 else "Low"
                c_types = {e.get("signal_type") for e in corrob_signals}
                rationale = (
                    f"Partially demonstrated: Found corroborating signals ({', '.join(c_types)}) "
                    f"without dedicated implementation or direct code execution artifact."
                )

        # 4. Check for Not demonstrated in this scope:
        # "No Strong or Corroborating signals in the analysed repositories and commit range (Weak signals alone are shown but do not change the state)"
        else:
            state = "Not demonstrated in this scope"
            confidence = "High" if not weak_signals else "Medium"

            if weak_signals:
                rationale = (
                    f"Not demonstrated in this scope. Mentioned in documentation/README ({len(weak_signals)} weak mention(s)), "
                    f"but documentation claims alone do not verify implementation depth without executable code."
                )
            else:
                rationale = (
                    f"Not demonstrated in this scope. No implementation files, test suites, or manifest dependencies "
                    f"matching {skill_name} were identified across the selected repositories."
                )

        return {
            "skill_id": skill_id,
            "state": state,
            "confidence": confidence,
            "scope_summary": scope_summary,
            "rationale": rationale
        }
