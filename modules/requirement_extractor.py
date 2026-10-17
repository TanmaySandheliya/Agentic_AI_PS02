"""
Requirement Extraction Module for SkillTrace.
Extracts skill requirements, preserves verbatim snippets, and classifies must-have vs. nice-to-have.
Adheres to SRS Section 4.2 (FR-07, FR-08, FR-09) and Section 7.2.
"""
import re
import uuid
from typing import List, Dict, Any, Optional
import yaml
from pathlib import Path

from config import settings


MUST_HAVE_HEADERS = [
    r"minimum\s+qualifications?",
    r"basic\s+qualifications?",
    r"required\s+(skills?|experience|qualifications?)",
    r"requirements?",
    r"what\s+you'?ll\s+need",
    r"what\s+we'?re\s+looking\s+for",
    r"must\s+haves?",
    r"core\s+requirements?"
]

NICE_TO_HAVE_HEADERS = [
    r"preferred\s+(skills?|experience|qualifications?)",
    r"bonus\s+(skills?|points|qualifications?)",
    r"nice\s+to\s+haves?",
    r"plus(es)?",
    r"good\s+to\s+have",
    r"desired\s+qualifications?",
    r"extra\s+points\s+if"
]

NON_ASSESSABLE_PATTERNS = [
    (r"(bachelor|master|phd|degree|b\.?s\.?|m\.?s\.?)\s+(in|of)?\s*(computer science|engineering|related)?", "Degree requirement (Academic credential)"),
    (r"(verbal|written)\s+communication\s+skills?", "Communication skills (Interpersonal)"),
    (r"(team\s*player|collaborative\s+attitude|teamwork)", "Teamwork & Collaboration (Behavioral)"),
    (r"(problem[- ]solving|critical\s+thinking)", "General problem-solving (Cognitive)"),
    (r"(work\s+ethic|self[- ]motivated|fast[- ]paced)", "Work ethic & cultural fit (Behavioral)")
]


class RequirementExtractor:
    def __init__(self, taxonomy_path: Optional[str] = None):
        self.taxonomy_path = Path(taxonomy_path or settings.taxonomy_file)
        self.skills = self._load_taxonomy()

    def _load_taxonomy(self) -> List[Dict[str, Any]]:
        """Loads skills and aliases from YAML taxonomy."""
        if not self.taxonomy_path.exists():
            return []
        with open(self.taxonomy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("skills", [])

    def extract_requirements(self, job_id: str, text: str) -> List[Dict[str, Any]]:
        """
        Parses the job snapshot text and extracts verbatim snippets mapped to taxonomy skills.
        """
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        current_importance = "must"  # default section importance
        extracted: List[Dict[str, Any]] = []
        seen_skills = set()

        for line in lines:
            # Check section headers
            header_lower = line.lower().strip(": ")
            if any(re.search(pat, header_lower) for pat in MUST_HAVE_HEADERS):
                current_importance = "must"
                continue
            if any(re.search(pat, header_lower) for pat in NICE_TO_HAVE_HEADERS):
                current_importance = "nice"
                continue

            # Determine line-level importance override
            line_importance = current_importance
            if re.search(r"\b(plus|bonus|nice to have|preferred|optional)\b", line, re.I):
                line_importance = "nice"
            elif re.search(r"\b(must|required|mandatory|essential)\b", line, re.I):
                line_importance = "must"

            # 1. Check for non-assessable requirements (FR-11, Section 8.2)
            for non_pat, reason in NON_ASSESSABLE_PATTERNS:
                if re.search(non_pat, line, re.I):
                    non_id = f"non_code_{len(extracted)}"
                    if non_id not in seen_skills:
                        seen_skills.add(non_id)
                        extracted.append({
                            "req_id": str(uuid.uuid4()),
                            "job_id": job_id,
                            "raw_text_snippet": line[:280],
                            "skill_id": "non_code_requirement",
                            "importance": line_importance,
                            "assessable": False,
                            "mapping_note": f"Not assessable from repository code: {reason}"
                        })

            # 2. Check for technical skills in taxonomy
            for skill in self.skills:
                skill_id = skill["skill_id"]
                aliases = [skill["name"]] + skill.get("aliases", [])

                matched_alias = None
                for alias in aliases:
                    # Match whole words to avoid false positives (e.g. "go" in "good")
                    pattern = r"(?<![a-zA-Z0-9_-])" + re.escape(alias) + r"(?![a-zA-Z0-9_-])"
                    if re.search(pattern, line, re.I):
                        matched_alias = alias
                        break

                if matched_alias:
                    key = (skill_id, line_importance)
                    if key not in seen_skills:
                        seen_skills.add(key)
                        extracted.append({
                            "req_id": str(uuid.uuid4()),
                            "job_id": job_id,
                            "raw_text_snippet": line[:280],
                            "skill_id": skill_id,
                            "importance": line_importance,
                            "assessable": True,
                            "mapping_note": f"Matched term '{matched_alias}' in text -> categorized as {line_importance}-have"
                        })

        return extracted


# Helper singleton
_extractor = None

def get_requirement_extractor() -> RequirementExtractor:
    global _extractor
    if _extractor is None:
        _extractor = RequirementExtractor()
    return _extractor
