"""
Job board ingest and parsing adapters for SkillTrace.
"""

from .url_ingest import fetch_job_from_url, ingest_pasted_text
from .greenhouse import parse_greenhouse_job
from .lever import parse_lever_job

__all__ = [
    "fetch_job_from_url",
    "ingest_pasted_text",
    "parse_greenhouse_job",
    "parse_lever_job"
]