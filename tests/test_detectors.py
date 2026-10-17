"""
Unit tests for SkillTrace Evidence Analyzers and Taxonomy Detectors.
Covers SRS Section 13.2 TC-05, TC-06, and Section 4.3 (FR-10 to FR-16).
"""
import pytest
from modules.evidence_analyzer import EvidenceAnalyzer


@pytest.fixture
def analyzer():
    return EvidenceAnalyzer()


def test_sql_strong_signal(analyzer):
    """Verifies that dedicated .sql files or executable queries generate Strong signals."""
    sql_file = "migrations/001_initial.sql"
    content = "CREATE TABLE users (id SERIAL PRIMARY KEY, name VARCHAR(100));\nSELECT * FROM users;"

    records = analyzer.analyze_file(
        file_path=sql_file,
        content=content,
        repo_id="test_repo",
        repo_full_name="test_org/test_repo",
        commit_sha="c123456"
    )

    sql_records = [r for r in records if r["skill_id"] == "sql"]
    assert len(sql_records) >= 1
    assert any(r["strength"] == "Strong" for r in sql_records)
    assert any(r["signal_type"] in ("dedicated_artifact", "source_usage") for r in sql_records)


def test_sql_corroborating_manifest_signal(analyzer):
    """Verifies that dependencies in requirements.txt generate Corroborating signals."""
    req_file = "requirements.txt"
    content = "fastapi==0.110.0\npsycopg2-binary==2.9.9\npytest>=8.0.0"

    records = analyzer.analyze_file(
        file_path=req_file,
        content=content,
        repo_id="test_repo",
        repo_full_name="test_org/test_repo",
        commit_sha="c123456"
    )

    sql_records = [r for r in records if r["skill_id"] == "sql"]
    assert len(sql_records) >= 1
    assert any(r["strength"] == "Corroborating" and r["signal_type"] == "manifest_dependency" for r in sql_records)


def test_readme_weak_signal(analyzer):
    """
    SRS TC-05: README claims SQL but no code uses it.
    Weak signal should be recorded, but not Strong or Corroborating.
    """
    readme_file = "README.md"
    content = "# Project Title\nThis project demonstrates my SQL and database design skills."

    records = analyzer.analyze_file(
        file_path=readme_file,
        content=content,
        repo_id="test_repo",
        repo_full_name="test_org/test_repo",
        commit_sha="c123456"
    )

    sql_records = [r for r in records if r["skill_id"] == "sql"]
    assert len(sql_records) >= 1
    assert all(r["strength"] == "Weak" for r in sql_records)
    assert all(r["signal_type"] == "doc_mention" for r in sql_records)


def test_vendored_and_generated_exclusion(analyzer):
    """
    SRS TC-06: Vendored or generated files must be strictly excluded from evidence.
    """
    vendored_path = "node_modules/postgres/index.js"
    lockfile_path = "package-lock.json"
    minified_path = "dist/bundle.min.js"

    assert analyzer.is_excluded_path(vendored_path) is True
    assert analyzer.is_excluded_path(lockfile_path) is True
    assert analyzer.is_excluded_path(minified_path) is True

    # Ensure analyzer returns empty list for excluded files
    records = analyzer.analyze_file(
        file_path=vendored_path,
        content="SELECT * FROM users;",
        repo_id="test_repo",
        repo_full_name="test_org/test_repo",
        commit_sha="c123456"
    )
    assert len(records) == 0


def test_docker_and_fastapi_detection(analyzer):
    """Tests multi-skill detection on Dockerfile and FastAPI application."""
    docker_content = "FROM python:3.11-slim\nWORKDIR /app\nRUN pip install -r requirements.txt\nCMD ['uvicorn', 'app:app']"
    records_docker = analyzer.analyze_file(
        file_path="Dockerfile",
        content=docker_content,
        repo_id="test_repo",
        repo_full_name="test_org/test_repo",
        commit_sha="c123456"
    )
    docker_signals = [r for r in records_docker if r["skill_id"] == "docker"]
    assert len(docker_signals) >= 1
    assert any(r["strength"] == "Strong" for r in docker_signals)

    py_content = "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health():\n    return {'status': 'ok'}"
    records_py = analyzer.analyze_file(
        file_path="app/main.py",
        content=py_content,
        repo_id="test_repo",
        repo_full_name="test_org/test_repo",
        commit_sha="c123456"
    )
    fastapi_signals = [r for r in records_py if r["skill_id"] == "fastapi"]
    assert len(fastapi_signals) >= 1
    assert any(r["strength"] == "Strong" for r in fastapi_signals)
