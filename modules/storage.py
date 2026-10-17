"""
Storage Module for SkillTrace
Implements SQLite schema and CRUD persistence according to SRS Section 9.2.
All timestamps are ISO 8601 strings.
"""
import sqlite3
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List
from pathlib import Path

from config import settings


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Returns a connection to the SQLite database with row factory enabled."""
    path = db_path or settings.database_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes the database schema with all required tables and indexes."""
    conn = get_connection(db_path)
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            github_username TEXT NOT NULL UNIQUE,
            consent_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS repositories (
            repo_id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            full_name TEXT NOT NULL UNIQUE,
            default_branch TEXT DEFAULT 'main',
            tracked_branch TEXT DEFAULT 'main',
            last_analysed_sha TEXT,
            webhook_id TEXT,
            selected INTEGER DEFAULT 1,
            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT,
            source_name TEXT,
            source_url TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            snapshot_text TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS requirements (
            req_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            raw_text_snippet TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            importance TEXT NOT NULL, -- 'must', 'nice', 'unclear'
            assessable INTEGER DEFAULT 1,
            mapping_note TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            aliases TEXT NOT NULL, -- JSON list
            category TEXT NOT NULL,
            detector_ids TEXT NOT NULL -- JSON list
        );

        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            repo_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            line_start INTEGER,
            line_end INTEGER,
            commit_sha TEXT NOT NULL,
            signal_type TEXT NOT NULL, -- 'source_usage', 'dedicated_artifact', 'manifest_dependency', 'test', 'ci_step', 'doc_mention'
            strength TEXT NOT NULL,    -- 'Strong', 'Corroborating', 'Weak'
            excerpt TEXT NOT NULL,
            permalink TEXT NOT NULL,
            authored_by_student INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active', -- 'active', 'superseded'
            created_at TEXT NOT NULL,
            FOREIGN KEY (repo_id) REFERENCES repositories(repo_id) ON DELETE CASCADE,
            FOREIGN KEY (skill_id) REFERENCES skills(skill_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS assessments (
            assessment_id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            state TEXT NOT NULL, -- 'Demonstrated', 'Partially demonstrated', 'Not demonstrated in this scope', 'Not assessable from code'
            confidence TEXT NOT NULL, -- 'High', 'Medium', 'Low'
            scope_summary TEXT NOT NULL,
            rationale TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            trigger_sha TEXT,
            previous_state TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
            FOREIGN KEY (skill_id) REFERENCES skills(skill_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS events (
            delivery_id TEXT PRIMARY KEY,
            source TEXT NOT NULL, -- 'webhook', 'poll'
            repo_id TEXT NOT NULL,
            before_sha TEXT,
            after_sha TEXT,
            received_at TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            changed_files TEXT NOT NULL, -- JSON list
            affected_skills TEXT NOT NULL, -- JSON list
            status TEXT DEFAULT 'processed'
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_repo_student ON repositories(student_id);
        CREATE INDEX IF NOT EXISTS idx_req_job ON requirements(job_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_skill ON evidence(skill_id, status);
        CREATE INDEX IF NOT EXISTS idx_evidence_repo ON evidence(repo_id, status);
        CREATE INDEX IF NOT EXISTS idx_assessment_student ON assessments(student_id, skill_id);
        CREATE INDEX IF NOT EXISTS idx_events_repo ON events(repo_id);
        """)
    conn.close()


def utcnow_iso() -> str:
    """Returns current UTC time formatted as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ------------------- Students & Repositories -------------------

def get_or_create_student(github_username: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves an existing student or creates a new record upon consent."""
    conn = get_connection(db_path)
    username = github_username.strip().lower()
    with conn:
        row = conn.execute(
            "SELECT * FROM students WHERE LOWER(github_username) = ?", (username,)
        ).fetchone()
        if row:
            res = dict(row)
        else:
            student_id = str(uuid.uuid4())
            now = utcnow_iso()
            conn.execute(
                "INSERT INTO students (student_id, github_username, consent_at, created_at) VALUES (?, ?, ?, ?)",
                (student_id, username, now, now)
            )
            created = conn.execute("SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
            res = dict(created)
    conn.close()
    return res


def upsert_repository(
    student_id: str,
    full_name: str,
    default_branch: str = "main",
    tracked_branch: str = "main",
    last_analysed_sha: Optional[str] = None,
    webhook_id: Optional[str] = None,
    selected: bool = True,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Upserts a repository tracked for a student."""
    conn = get_connection(db_path)
    with conn:
        row = conn.execute(
            "SELECT * FROM repositories WHERE full_name = ?", (full_name,)
        ).fetchone()
        if row:
            conn.execute("""
                UPDATE repositories
                SET student_id = ?, default_branch = ?, tracked_branch = ?,
                    last_analysed_sha = COALESCE(?, last_analysed_sha),
                    webhook_id = COALESCE(?, webhook_id),
                    selected = ?
                WHERE full_name = ?
            """, (student_id, default_branch, tracked_branch, last_analysed_sha, webhook_id, 1 if selected else 0, full_name))
            repo_id = row["repo_id"]
        else:
            repo_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO repositories (repo_id, student_id, full_name, default_branch, tracked_branch, last_analysed_sha, webhook_id, selected)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (repo_id, student_id, full_name, default_branch, tracked_branch, last_analysed_sha, webhook_id, 1 if selected else 0))

        updated = conn.execute("SELECT * FROM repositories WHERE repo_id = ?", (repo_id,)).fetchone()
        res = dict(updated)
    conn.close()
    return res


def get_repositories(student_id: str, selected_only: bool = False, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Gets repositories for a student."""
    conn = get_connection(db_path)
    query = "SELECT * FROM repositories WHERE student_id = ?"
    params: List[Any] = [student_id]
    if selected_only:
        query += " AND selected = 1"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_repository_by_name(full_name: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves repository by full_name ('owner/repo')."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM repositories WHERE full_name = ?", (full_name,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ------------------- Skills -------------------

def sync_skills(skills_list: List[Dict[str, Any]], db_path: Optional[str] = None) -> None:
    """Syncs skills from the taxonomy YAML into the skills table."""
    conn = get_connection(db_path)
    with conn:
        for skill in skills_list:
            aliases_json = json.dumps(skill.get("aliases", []))
            detector_ids_json = json.dumps(skill.get("detector_ids", [skill["skill_id"]]))
            conn.execute("""
                INSERT INTO skills (skill_id, name, aliases, category, detector_ids)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET
                    name = excluded.name,
                    aliases = excluded.aliases,
                    category = excluded.category,
                    detector_ids = excluded.detector_ids
            """, (skill["skill_id"], skill["name"], aliases_json, skill["category"], detector_ids_json))
    conn.close()


def get_all_skills(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Gets all registered skills."""
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM skills ORDER BY category, name").fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["aliases"] = json.loads(d["aliases"])
        d["detector_ids"] = json.loads(d["detector_ids"])
        res.append(d)
    return res


# ------------------- Jobs & Requirements -------------------

def save_job(
    title: str,
    source_url: str,
    snapshot_text: str,
    company: Optional[str] = None,
    source_name: Optional[str] = None,
    job_id: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Stores a job posting snapshot."""
    conn = get_connection(db_path)
    jid = job_id or str(uuid.uuid4())
    now = utcnow_iso()
    with conn:
        conn.execute("""
            INSERT INTO jobs (job_id, title, company, source_name, source_url, retrieved_at, snapshot_text, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(job_id) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                source_name = excluded.source_name,
                source_url = excluded.source_url,
                retrieved_at = excluded.retrieved_at,
                snapshot_text = excluded.snapshot_text
        """, (jid, title, company or "Unknown Company", source_name or "Custom URL", source_url, now, snapshot_text))
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (jid,)).fetchone()
    conn.close()
    return dict(row)


def save_requirements(
    job_id: str,
    requirements: List[Dict[str, Any]],
    db_path: Optional[str] = None
) -> None:
    """Saves extracted requirements for a job, replacing existing ones."""
    conn = get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM requirements WHERE job_id = ?", (job_id,))
        for req in requirements:
            req_id = req.get("req_id") or str(uuid.uuid4())
            conn.execute("""
                INSERT INTO requirements (req_id, job_id, raw_text_snippet, skill_id, importance, assessable, mapping_note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                req_id,
                job_id,
                req["raw_text_snippet"],
                req["skill_id"],
                req.get("importance", "must"),
                1 if req.get("assessable", True) else 0,
                req.get("mapping_note", "")
            ))
    conn.close()


def get_job(job_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Gets a job by ID."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_jobs(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists all stored jobs."""
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM jobs ORDER BY retrieved_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_requirements_for_job(job_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Gets requirements for a specific job."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT r.*, s.name as skill_name, s.category as skill_category
        FROM requirements r
        LEFT JOIN skills s ON r.skill_id = s.skill_id
        WHERE r.job_id = ?
        ORDER BY r.importance DESC, r.raw_text_snippet
    """, (job_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------- Evidence -------------------

def save_evidence_batch(evidence_list: List[Dict[str, Any]], db_path: Optional[str] = None) -> None:
    """Saves a batch of evidence records."""
    if not evidence_list:
        return
    conn = get_connection(db_path)
    now = utcnow_iso()
    with conn:
        for ev in evidence_list:
            ev_id = ev.get("evidence_id") or str(uuid.uuid4())
            conn.execute("""
                INSERT INTO evidence (
                    evidence_id, repo_id, skill_id, file_path, line_start, line_end,
                    commit_sha, signal_type, strength, excerpt, permalink,
                    authored_by_student, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ev_id,
                ev["repo_id"],
                ev["skill_id"],
                ev["file_path"],
                ev.get("line_start", 1),
                ev.get("line_end", 1),
                ev["commit_sha"],
                ev["signal_type"],
                ev["strength"],
                ev["excerpt"],
                ev["permalink"],
                1 if ev.get("authored_by_student", True) else 0,
                ev.get("status", "active"),
                now
            ))
    conn.close()


def mark_evidence_superseded(repo_id: str, file_paths: List[str], db_path: Optional[str] = None) -> int:
    """Marks existing evidence in specified files as superseded."""
    if not file_paths:
        return 0
    conn = get_connection(db_path)
    placeholders = ",".join("?" for _ in file_paths)
    with conn:
        cursor = conn.execute(
            f"UPDATE evidence SET status = 'superseded' WHERE repo_id = ? AND file_path IN ({placeholders}) AND status = 'active'",
            [repo_id] + file_paths
        )
        count = cursor.rowcount
    conn.close()
    return count


def get_active_evidence_for_student(student_id: str, skill_id: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Gets all active evidence records for repositories belonging to a student."""
    conn = get_connection(db_path)
    query = """
        SELECT e.*, r.full_name as repo_name, s.name as skill_name
        FROM evidence e
        JOIN repositories r ON e.repo_id = r.repo_id
        JOIN skills s ON e.skill_id = s.skill_id
        WHERE r.student_id = ? AND r.selected = 1 AND e.status = 'active'
    """
    params: List[Any] = [student_id]
    if skill_id:
        query += " AND e.skill_id = ?"
        params.append(skill_id)
    query += " ORDER BY e.strength DESC, e.file_path"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------- Assessments -------------------

def save_assessment(
    student_id: str,
    skill_id: str,
    state: str,
    confidence: str,
    scope_summary: str,
    rationale: str,
    trigger_sha: Optional[str] = None,
    previous_state: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Stores an assessment version and records the change history."""
    conn = get_connection(db_path)
    now = utcnow_iso()
    with conn:
        latest = conn.execute(
            "SELECT version, state FROM assessments WHERE student_id = ? AND skill_id = ? ORDER BY version DESC LIMIT 1",
            (student_id, skill_id)
        ).fetchone()

        version = (latest["version"] + 1) if latest else 1
        prev = previous_state if previous_state is not None else (latest["state"] if latest else "Not evaluated")

        assessment_id = str(uuid.uuid4())
        conn.execute("""
            INSERT INTO assessments (
                assessment_id, student_id, skill_id, state, confidence,
                scope_summary, rationale, version, trigger_sha, previous_state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            assessment_id, student_id, skill_id, state, confidence,
            scope_summary, rationale, version, trigger_sha, prev, now
        ))
        row = conn.execute("SELECT * FROM assessments WHERE assessment_id = ?", (assessment_id,)).fetchone()
    conn.close()
    return dict(row)


def get_latest_assessments(student_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves the latest assessment for every skill assessed for a student."""
    conn = get_connection(db_path)
    # Using window function to grab row with highest version per skill_id
    query = """
        WITH RankedAssessments AS (
            SELECT a.*, s.name as skill_name, s.category as skill_category,
                   ROW_NUMBER() OVER(PARTITION BY a.skill_id ORDER BY a.version DESC) as rn
            FROM assessments a
            JOIN skills s ON a.skill_id = s.skill_id
            WHERE a.student_id = ?
        )
        SELECT * FROM RankedAssessments WHERE rn = 1
        ORDER BY skill_category, skill_name;
    """
    rows = conn.execute(query, (student_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_assessment_history(student_id: str, skill_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns the immutable evolution timeline for a skill assessment."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT a.*, s.name as skill_name
        FROM assessments a
        JOIN skills s ON a.skill_id = s.skill_id
        WHERE a.student_id = ? AND a.skill_id = ?
        ORDER BY a.version ASC
    """, (student_id, skill_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------- Events & Audit Feed -------------------

def is_event_processed(delivery_id: str, db_path: Optional[str] = None) -> bool:
    """Checks if a delivery ID was already processed (Idempotency)."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT delivery_id FROM events WHERE delivery_id = ?", (delivery_id,)).fetchone()
    conn.close()
    return row is not None


def record_event(
    delivery_id: str,
    source: str,
    repo_id: str,
    before_sha: Optional[str],
    after_sha: Optional[str],
    changed_files: List[str],
    affected_skills: List[str],
    status: str = "processed",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Records an incoming webhook or polling change event."""
    conn = get_connection(db_path)
    now = utcnow_iso()
    with conn:
        conn.execute("""
            INSERT INTO events (
                delivery_id, source, repo_id, before_sha, after_sha,
                received_at, processed_at, changed_files, affected_skills, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            delivery_id,
            source,
            repo_id,
            before_sha,
            after_sha,
            now,
            now,
            json.dumps(changed_files),
            json.dumps(affected_skills),
            status
        ))
        row = conn.execute("SELECT * FROM events WHERE delivery_id = ?", (delivery_id,)).fetchone()
    conn.close()
    d = dict(row)
    d["changed_files"] = json.loads(d["changed_files"])
    d["affected_skills"] = json.loads(d["affected_skills"])
    return d


def get_event_feed(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves recent events for the change feed."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT e.*, r.full_name as repo_name
        FROM events e
        LEFT JOIN repositories r ON e.repo_id = r.repo_id
        ORDER BY e.processed_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["changed_files"] = json.loads(d["changed_files"]) if d["changed_files"] else []
        d["affected_skills"] = json.loads(d["affected_skills"]) if d["affected_skills"] else []
        res.append(d)
    return res
