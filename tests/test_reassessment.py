"""
Unit tests for Incremental Reassessment Pipeline and Affected-Skill Mapping.
Covers SRS Section 8.3, Section 13.2 TC-04, TC-09, TC-10.
"""
import pytest
from modules.change_agent import ChangeAgent
from modules import storage
from config import settings


@pytest.fixture
def test_setup(tmp_path):
    db_file = str(tmp_path / "test_reassess.db")
    settings.database_path = db_file
    storage.init_db(db_file)

    # Sync taxonomy
    import yaml
    with open(settings.taxonomy_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        storage.sync_skills(data.get("skills", []))

    # Create student and repo
    student = storage.get_or_create_student("alice")
    repo = storage.upsert_repository(student["student_id"], "alice/backend-svc")

    agent = ChangeAgent()
    return {
        "student": student,
        "repo": repo,
        "agent": agent,
        "db": db_file
    }


def test_reassessment_adds_sql_demonstrated(test_setup):
    """
    SRS TC-04: Push a commit adding .sql queries and DB code.
    SQL assessment state updates to 'Demonstrated' citing the new files.
    """
    agent = test_setup["agent"]
    student_id = test_setup["student"]["student_id"]
    repo_name = "alice/backend-svc"

    # Step 1: Initial state (no SQL files)
    storage.save_assessment(
        student_id=student_id,
        skill_id="sql",
        state="Not demonstrated in this scope",
        confidence="High",
        scope_summary=f"repo: {repo_name}, commit: 0000000",
        rationale="Initial state"
    )

    # Step 2: Push commit adding schema.sql and queries in python
    changed_files = [
        {"filename": "db/schema.sql", "status": "added"},
        {"filename": "app/queries.py", "status": "added"}
    ]
    file_contents = {
        "db/schema.sql": "CREATE TABLE items (id SERIAL PRIMARY KEY, name TEXT);",
        "app/queries.py": "def get_items(db):\n    cursor = db.cursor()\n    cursor.execute('SELECT * FROM items')\n    return cursor.fetchall()"
    }

    res = agent.process_change_event(
        repo_full_name=repo_name,
        before_sha="0000000000000000000000000000000000000000",
        after_sha="1111111111111111111111111111111111111111",
        changed_files_info=changed_files,
        delivery_id="delivery-add-sql",
        source="webhook",
        file_contents=file_contents
    )

    assert "sql" in res["affected_skills"]

    # Verify latest assessment is now Demonstrated
    latest = {a["skill_id"]: a for a in storage.get_latest_assessments(student_id)}
    assert latest["sql"]["state"] == "Demonstrated"
    assert latest["sql"]["previous_state"] == "Not demonstrated in this scope"

    # Verify active evidence was saved
    active_ev = storage.get_active_evidence_for_student(student_id, skill_id="sql")
    assert len(active_ev) >= 2
    assert any(e["file_path"] == "db/schema.sql" for e in active_ev)


def test_reassessment_documentation_only_no_change(test_setup):
    """
    SRS TC-09: Push that changes only documentation.
    Event is recorded in history; unrelated technical skill assessments remain unchanged.
    """
    agent = test_setup["agent"]
    student_id = test_setup["student"]["student_id"]
    repo_name = "alice/backend-svc"

    # Establish baseline for python
    storage.save_assessment(
        student_id=student_id,
        skill_id="python",
        state="Demonstrated",
        confidence="High",
        scope_summary=f"repo: {repo_name}",
        rationale="Baseline python"
    )

    # Push commit that touches only docs/architecture.md
    changed_files = [
        {"filename": "docs/architecture.md", "status": "modified"}
    ]
    file_contents = {
        "docs/architecture.md": "# System Architecture\nExplaining cloud topology and deployment."
    }

    res = agent.process_change_event(
        repo_full_name=repo_name,
        before_sha="1111111111111111111111111111111111111111",
        after_sha="2222222222222222222222222222222222222222",
        changed_files_info=changed_files,
        delivery_id="delivery-doc-change",
        source="webhook",
        file_contents=file_contents
    )

    # Affected skills should be empty
    assert len(res["affected_skills"]) == 0

    # Assessment for python remains untouched
    latest = {a["skill_id"]: a for a in storage.get_latest_assessments(student_id)}
    assert latest["python"]["state"] == "Demonstrated"
    assert latest["python"]["version"] == 1


def test_reassessment_delete_evidence_superseded(test_setup):
    """
    SRS TC-10: Delete the file that provided SQL evidence.
    Evidence is superseded; state moves down; history records the transition honestly.
    """
    agent = test_setup["agent"]
    student_id = test_setup["student"]["student_id"]
    repo_name = "alice/backend-svc"
    repo_id = test_setup["repo"]["repo_id"]

    # Initial evidence & assessment
    storage.save_evidence_batch([{
        "evidence_id": "ev-sql-1",
        "repo_id": repo_id,
        "skill_id": "sql",
        "file_path": "db/queries.sql",
        "commit_sha": "1111111",
        "signal_type": "dedicated_artifact",
        "strength": "Strong",
        "excerpt": "SELECT * FROM users;",
        "permalink": "https://github.com/alice/backend-svc/blob/1111111/db/queries.sql#L1",
        "authored_by_student": 1,
        "status": "active"
    }])

    storage.save_assessment(
        student_id=student_id,
        skill_id="sql",
        state="Partially demonstrated",
        confidence="Medium",
        scope_summary=f"repo: {repo_name}",
        rationale="Initial query file"
    )

    # Commit removing db/queries.sql
    changed_files = [
        {"filename": "db/queries.sql", "status": "removed"}
    ]

    res = agent.process_change_event(
        repo_full_name=repo_name,
        before_sha="1111111111111111111111111111111111111111",
        after_sha="3333333333333333333333333333333333333333",
        changed_files_info=changed_files,
        delivery_id="delivery-delete-sql",
        source="webhook"
    )

    # Active evidence should now be 0 (superseded)
    active_ev = storage.get_active_evidence_for_student(student_id, skill_id="sql")
    assert len(active_ev) == 0

    # Assessment state moves down to "Not demonstrated in this scope"
    latest = {a["skill_id"]: a for a in storage.get_latest_assessments(student_id)}
    assert latest["sql"]["state"] == "Not demonstrated in this scope"
    assert latest["sql"]["previous_state"] == "Partially demonstrated"

    # History contains both versions
    history = storage.get_assessment_history(student_id, "sql")
    assert len(history) == 2
    assert history[0]["state"] == "Partially demonstrated"
    assert history[1]["state"] == "Not demonstrated in this scope"
