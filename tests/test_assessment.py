"""
Unit tests for SkillTrace Assessment Engine Rubric.
Covers SRS Section 8.2, Section 13.2 TC-03, TC-05.
"""
import pytest
from modules.assessment_engine import AssessmentEngine


@pytest.fixture
def engine():
    return AssessmentEngine()


def test_no_signals_is_not_demonstrated(engine):
    """SRS TC-03: Repo with no SQL files or dependencies -> Not demonstrated in this scope."""
    res = engine.evaluate_skill(
        skill_id="sql",
        skill_name="SQL",
        evidence_list=[],
        scope_summary="repo: test/repo, commit: 12345"
    )
    assert res["state"] == "Not demonstrated in this scope"
    assert "Not demonstrated in this scope" in res["rationale"]


def test_readme_weak_signals_only(engine):
    """
    SRS TC-05: README claims SQL but no code uses it.
    Weak signals alone are shown but do not change state from Not demonstrated.
    """
    weak_ev = [{
        "skill_id": "sql",
        "file_path": "README.md",
        "strength": "Weak",
        "signal_type": "doc_mention",
        "status": "active"
    }]
    res = engine.evaluate_skill(
        skill_id="sql",
        skill_name="SQL",
        evidence_list=weak_ev,
        scope_summary="repo: test/repo, commit: 12345"
    )
    assert res["state"] == "Not demonstrated in this scope"
    assert "documentation/README" in res["rationale"]


def test_partially_demonstrated_single_strong(engine):
    """Exactly one Strong signal with no corroboration -> Partially demonstrated."""
    single_strong = [{
        "skill_id": "sql",
        "file_path": "scripts/query.sql",
        "strength": "Strong",
        "signal_type": "dedicated_artifact",
        "status": "active"
    }]
    res = engine.evaluate_skill(
        skill_id="sql",
        skill_name="SQL",
        evidence_list=single_strong,
        scope_summary="repo: test/repo, commit: 12345"
    )
    assert res["state"] == "Partially demonstrated"
    assert res["confidence"] == "Medium"


def test_partially_demonstrated_corroborating_only(engine):
    """Only Corroborating signals (e.g. dependency in requirements.txt) -> Partially demonstrated."""
    corrob = [{
        "skill_id": "sql",
        "file_path": "requirements.txt",
        "strength": "Corroborating",
        "signal_type": "manifest_dependency",
        "status": "active"
    }]
    res = engine.evaluate_skill(
        skill_id="sql",
        skill_name="SQL",
        evidence_list=corrob,
        scope_summary="repo: test/repo, commit: 12345"
    )
    assert res["state"] == "Partially demonstrated"


def test_demonstrated_strong_plus_corroborating(engine):
    """At least one Strong signal + at least one Corroborating signal -> Demonstrated."""
    evidence = [
        {
            "skill_id": "sql",
            "file_path": "db/queries.sql",
            "strength": "Strong",
            "signal_type": "dedicated_artifact",
            "authored_by_student": 1,
            "status": "active"
        },
        {
            "skill_id": "sql",
            "file_path": "requirements.txt",
            "strength": "Corroborating",
            "signal_type": "manifest_dependency",
            "status": "active"
        }
    ]
    res = engine.evaluate_skill(
        skill_id="sql",
        skill_name="SQL",
        evidence_list=evidence,
        scope_summary="repo: test/repo, commit: 12345"
    )
    assert res["state"] == "Demonstrated"
    assert res["confidence"] == "High"
    assert "Demonstrated in codebase" in res["rationale"]


def test_demonstrated_two_strong_signals(engine):
    """Two independent Strong signals in code -> Demonstrated with High confidence."""
    evidence = [
        {
            "skill_id": "sql",
            "file_path": "db/schema.sql",
            "strength": "Strong",
            "signal_type": "dedicated_artifact",
            "authored_by_student": 1,
            "status": "active"
        },
        {
            "skill_id": "sql",
            "file_path": "app/repository.py",
            "strength": "Strong",
            "signal_type": "source_usage",
            "authored_by_student": 1,
            "status": "active"
        }
    ]
    res = engine.evaluate_skill(
        skill_id="sql",
        skill_name="SQL",
        evidence_list=evidence,
        scope_summary="repo: test/repo, commit: 12345"
    )
    assert res["state"] == "Demonstrated"
    assert res["confidence"] == "High"


def test_not_assessable_from_code(engine):
    """Section 8.2: Non-code requirements (degree, soft skills) -> Not assessable from code."""
    res = engine.evaluate_skill(
        skill_id="non_code_requirement",
        skill_name="Communication",
        evidence_list=[],
        scope_summary="repo: test/repo, commit: 12345",
        is_code_assessable=False
    )
    assert res["state"] == "Not assessable from code"
    assert res["confidence"] == "High"
