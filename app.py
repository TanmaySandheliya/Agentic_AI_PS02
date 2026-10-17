"""
SkillTrace - Automated GitHub Portfolio & Job Requirement Verification Dashboard.
Conforms to SRS Section 4.6 (FR-30 to FR-34), Section 8.2 Rubric, Section 18 Demo Scenario.
"""
import streamlit as st
import pandas as pd
import json
import yaml
from pathlib import Path
from datetime import datetime, timezone

from config import settings
from modules import storage
from modules.job_sources import fetch_job_from_url, ingest_pasted_text
from modules.job_sources.url_ingest import JobIngestError
from modules.requirement_extractor import get_requirement_extractor
from modules.evidence_analyzer import EvidenceAnalyzer
from modules.assessment_engine import AssessmentEngine
from modules.gap_analyzer import GapAnalyzer
from modules.github_client import GitHubClient
from modules.change_agent import ChangeAgent
from urllib.parse import urlparse


def normalize_github_username(value):
    value = value.strip().rstrip("/")

    if value.startswith(("https://", "http://")):
        parsed = urlparse(value)
        if parsed.hostname not in ("github.com", "www.github.com"):
            raise ValueError("Invalid GitHub profile URL")

        parts = parsed.path.strip("/").split("/")

        if len(parts) != 1 or not parts[0]:
            raise ValueError("Enter a GitHub profile URL")

        return parts[0]

    return value.lstrip("@")

# Set Streamlit Page Configuration
st.set_page_config(
    page_title="SkillTrace | Automated Portfolio Verification",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 18px;
        color: #f8fafc;
        text-align: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
    }
    .metric-value {
        font-size: 2.2rem;
        font-weight: 700;
        margin: 4px 0;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .badge-demonstrated {
        background-color: #065f46;
        color: #34d399;
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .badge-partial {
        background-color: #854d0e;
        color: #fde047;
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .badge-not-demonstrated {
        background-color: #7f1d1d;
        color: #fca5a5;
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .badge-not-assessable {
        background-color: #334155;
        color: #cbd5e1;
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .scope-box {
        background-color: #1e1b4b;
        border-left: 4px solid #6366f1;
        padding: 12px 16px;
        border-radius: 6px;
        margin-bottom: 20px;
        font-size: 0.95rem;
        color: #e0e7ff;
    }
    .evidence-card {
        background-color: #182234;
        border: 1px solid #2d3748;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 12px;
    }
    .disclaimer-box {
        background-color: #1e293b;
        border: 1px solid #475569;
        border-radius: 8px;
        padding: 14px;
        font-size: 0.85rem;
        color: #94a3b8;
        margin-top: 30px;
    }
</style>
""", unsafe_allow_html=True)


# Initialize database and taxonomy
storage.init_db()
if "taxonomy_synced" not in st.session_state:
    try:
        with open(settings.taxonomy_file, "r", encoding="utf-8") as f:
            tax_data = yaml.safe_load(f)
            storage.sync_skills(tax_data.get("skills", []))
            st.session_state["taxonomy_synced"] = True
    except Exception as e:
        st.error(f"Failed to load taxonomy: {e}")


def load_demo_data(student_id: str):
    """Seeds initial demonstration repositories and files (SRS Section 18)."""
    # 1. Seed Repository
    repo = storage.upsert_repository(
        student_id=student_id,
        full_name="demo-student/cloud-task-manager",
        default_branch="main",
        tracked_branch="main",
        last_analysed_sha="a1b2c3d4e5f678901234567890abcdef12345678",
        selected=True
    )
    repo_id = repo["repo_id"]

    # 2. Seed initial files: Python, Docker, FastAPI, REST, Unit Tests (No SQL yet!)
    analyzer = EvidenceAnalyzer()
    initial_files = {
        "app/main.py": """from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests

app = FastAPI(title="Cloud Task Manager")

class TaskCreate(BaseModel):
    title: str
    description: str

@app.get("/tasks")
def list_tasks():
    return [{"id": 1, "title": "Setup CI"}]

@app.post("/tasks")
def create_task(task: TaskCreate):
    return {"status": "created", "task": task.dict()}
""",
        "Dockerfile": """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
        "requirements.txt": """fastapi==0.110.0
uvicorn==0.29.0
pydantic==2.7.0
requests==2.31.0
pytest==8.1.0
""",
        "tests/test_api.py": """from fastapi.testclient import TestClient
from app.main import app
import pytest

client = TestClient(app)

def test_list_tasks():
    response = client.get("/tasks")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
""",
        "README.md": """# Cloud Task Manager
A high-performance cloud task management backend built with Python, FastAPI, and Docker.
Planned features: Database migration to SQL PostgreSQL with SQLAlchemy.
"""
    }

    # Mark any old evidence as superseded
    storage.mark_evidence_superseded(repo_id, list(initial_files.keys()))

    new_evidence = []
    for fpath, content in initial_files.items():
        ev = analyzer.analyze_file(
            file_path=fpath,
            content=content,
            repo_id=repo_id,
            repo_full_name="demo-student/cloud-task-manager",
            commit_sha="a1b2c3d4e5f678901234567890abcdef12345678"
        )
        new_evidence.extend(ev)

    storage.save_evidence_batch(new_evidence)

    # Run assessment engine on all taxonomy skills
    engine = AssessmentEngine()
    skills = storage.get_all_skills()
    scope = "repo: demo-student/cloud-task-manager, branch: main, commit: a1b2c3d"

    for s in skills:
        sid = s["skill_id"]
        ev_items = storage.get_active_evidence_for_student(student_id, skill_id=sid)
        eval_res = engine.evaluate_skill(
            skill_id=sid,
            skill_name=s["name"],
            evidence_list=ev_items,
            scope_summary=scope
        )
        storage.save_assessment(
            student_id=student_id,
            skill_id=sid,
            state=eval_res["state"],
            confidence=eval_res["confidence"],
            scope_summary=scope,
            rationale=eval_res["rationale"],
            trigger_sha="a1b2c3d4e5f678901234567890abcdef12345678",
            previous_state="Initial evaluation"
        )

    # 3. Seed sample Job Posting (Full Stack / Backend Engineer)
    job_text = """
Software Engineer - Backend & Cloud Systems
Acme Cloud Technologies | San Francisco, CA (Hybrid)

Role Overview:
We are seeking a talented backend software engineer to design resilient cloud architectures and scalable microservices.

Minimum Qualifications:
- Bachelor's degree in Computer Science or equivalent practical experience
- Demonstrated proficiency with Python and modern async frameworks like FastAPI or Flask
- Strong understanding of SQL and relational database schemas
- Experience containerizing microservices with Docker
- Excellent written and verbal communication skills

Preferred Qualifications:
- Experience building and deploying automated Unit Testing suites with Pytest
- Familiarity with CI/CD GitHub Actions pipelines
- Hands-on experience with Redis caching and PostgreSQL
"""
    saved_job = storage.save_job(
        title="Software Engineer - Backend & Cloud Systems",
        company="Acme Cloud Technologies",
        source_name="Sample Posting",
        source_url="https://boards.greenhouse.io/acmecloud/jobs/4820192",
        snapshot_text=job_text,
        job_id="demo-backend-job"
    )

    extractor = get_requirement_extractor()
    reqs = extractor.extract_requirements(saved_job["job_id"], job_text)
    storage.save_requirements(saved_job["job_id"], reqs)


# ==========================================
# SIDEBAR: Student Profile & Repository Scope
# ==========================================
st.sidebar.title("🛡️ SkillTrace")
st.sidebar.caption("Evidence-Based Portfolio Verification (SRS v1.0)")

# Student Onboarding & Consent (FR-01)

username_input = st.sidebar.text_input("GitHub Username", value="demo-student").strip()
if username_input.strip():
    try:
        username_input = normalize_github_username(username_input)
    except ValueError as e:
        st.error(str(e))
        st.stop()
consent_given = st.sidebar.checkbox(
    "I consent to SkillTrace analyzing my public GitHub repositories.",
    value=True,
    help="SRS FR-01: Explicit student consent is required to index commits and code files."
)

if not consent_given:
    st.warning("⚠️ Student consent is required to proceed with portfolio evidence analysis.")
    st.stop()

student = storage.get_or_create_student(username_input)
student_id = student["student_id"]

st.sidebar.markdown(f"**Student ID:** `{student_id[:8]}...`")
st.sidebar.markdown(f"**Consented At:** `{student['consent_at'][:19].replace('T', ' ')} UTC`")

# Demo Seeding Button
if st.sidebar.button("🚀 Load Pre-Populated Demo Scenario", help="Seeds demo repositories and real job posting according to SRS Section 18"):
    load_demo_data(student_id)
    st.sidebar.success("Loaded demo repository and job posting!")
    st.rerun()

st.sidebar.divider()

# Repository Selection (FR-02)
st.sidebar.subheader("📂 Repository Scope")
tracked_repos = storage.get_repositories(student_id)

if not tracked_repos:
    st.sidebar.info("No repositories tracked yet. Click above to load the demo or enter a public repository.")
    with st.sidebar.expander("Add Repository"):
        new_repo_name = st.text_input("Repository (owner/repo)", value="demo-student/cloud-task-manager")
        if st.button("Track Repository"):
            storage.upsert_repository(student_id=student_id, full_name=new_repo_name, selected=True)
            st.rerun()
else:
    for repo in tracked_repos:
        is_sel = st.sidebar.checkbox(
            f"{repo['full_name']}",
            value=bool(repo["selected"]),
            key=f"repo_chk_{repo['repo_id']}"
        )
        if is_sel != bool(repo["selected"]):
            storage.upsert_repository(student_id, repo["full_name"], selected=is_sel)
            st.rerun()

st.sidebar.divider()

# Change Detection & Live Simulation Control (FR-21 to FR-26, Section 18)
st.sidebar.subheader("🔄 Change Detection")
st.sidebar.caption(f"Webhook Endpoint: `http://localhost:{settings.api_port}/webhooks/github`")

# Simulate Live Commit Button (SRS Section 18 Demo Scenario: Push commit adding SQL)
if st.sidebar.button("⚡ Simulate Commit: 'Add SQL queries & migrations'"):
    change_agent = ChangeAgent()
    repo_name = "demo-student/cloud-task-manager"
    new_sha = "f9e8d7c6b5a432101234567890abcdef98765432"

    # Files added in this commit
    changed_files = [
        {"filename": "db/schema.sql", "status": "added"},
        {"filename": "app/database.py", "status": "added"},
        {"filename": "requirements.txt", "status": "modified"}
    ]
    file_contents = {
        "db/schema.sql": """-- Production PostgreSQL Schema
CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tasks_status ON tasks(status);
""",
        "app/database.py": """import sqlite3
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")

def get_tasks_from_db():
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, status FROM tasks WHERE status = 'pending'")
    rows = cursor.fetchall()
    conn.close()
    return rows
""",
        "requirements.txt": """fastapi==0.110.0
uvicorn==0.29.0
pydantic==2.7.0
requests==2.31.0
pytest==8.1.0
psycopg2-binary==2.9.9
sqlite3
"""
    }

    delivery_id = f"sim_{new_sha[:10]}"
    res = change_agent.process_change_event(
        repo_full_name=repo_name,
        before_sha="a1b2c3d4e5f678901234567890abcdef12345678",
        after_sha=new_sha,
        changed_files_info=changed_files,
        delivery_id=delivery_id,
        source="webhook",
        file_contents=file_contents
    )
    st.sidebar.success("Pushed live commit! Reassessment triggered automatically.")
    st.rerun()


# ==========================================
# MAIN DASHBOARD CONTENT
# ==========================================

st.title("🎯 SkillTrace Portfolio & Job Alignment")
st.markdown("### Evidence-Backed Skill Discovery & Incremental Change Verification")

# Scope Banner (SRS Section 8.5)
selected_repos = storage.get_repositories(student_id, selected_only=True)
if selected_repos:
    repo_names = ", ".join([r["full_name"] for r in selected_repos])
    tracked_commits = ", ".join([f"{r['full_name']}@{r['last_analysed_sha'][:7] if r['last_analysed_sha'] else 'head'}" for r in selected_repos])
    st.markdown(f"""
    <div class="scope-box">
        <strong>🔍 Active Verification Scope:</strong><br>
        <strong>Repositories:</strong> {repo_names} | <strong>Tracked Commits:</strong> <code>{tracked_commits}</code><br>
        <span style="font-size:0.85rem; color:#a5b4fc;">*Notice: Skill assessments are computed strictly across this designated scope and do not evaluate code outside these commits.</span>
    </div>
    """, unsafe_allow_html=True)
else:
    st.warning("No repositories currently selected in the scope. Please select at least one repository in the sidebar.")

# Tabs for Core Modules
tab_matrix, tab_job, tab_evidence, tab_history, tab_growth = st.tabs([
    "📊 Requirement & Gap Matrix",
    "💼 Target Job Posting",
    "🔎 Evidence Inspector",
    "⏱️ Activity Feed & Timeline",
    "🚀 Resume & Learning Growth"
])


# ----------------------------------------------------
# TAB 2: Target Job Posting (Ingestion & Extraction)
# ----------------------------------------------------
with tab_job:
    st.subheader("Ingest Target Job Posting (SRS Section 4.2)")

    col_input1, col_input2 = st.columns([3, 1])
    with col_input1:
        job_url_input = st.text_input(
            "Target Job URL (Greenhouse, Lever, or Career Page)",
            value="https://boards.greenhouse.io/acmecloud/jobs/4820192",
            help="SRS FR-06: Fetches clean text snapshot and retains original URL for traceability."
        )
    with col_input2:
        st.write("")
        st.write("")
        fetch_btn = st.button("Fetch & Analyze Job", type="primary")

    with st.expander("Or Paste Job Description Manually (Fallback TC-02)", expanded=False):
        paste_title = st.text_input("Job Title", value="Software Engineer")
        paste_company = st.text_input("Company", value="Tech Corp")
        paste_url = st.text_input("Source URL", value="https://example.com/jobs/123")
        paste_text = st.text_area("Paste Full Posting Text", height=200)
        paste_btn = st.button("Ingest Pasted Posting")

    if fetch_btn and job_url_input:
        try:
            with st.spinner("Fetching job posting snapshot..."):
                job_data = fetch_job_from_url(job_url_input)
                saved = storage.save_job(
                    title=job_data["title"],
                    company=job_data["company"],
                    source_name=job_data["source_name"],
                    source_url=job_data["source_url"],
                    snapshot_text=job_data["snapshot_text"]
                )
                extractor = get_requirement_extractor()
                extracted_reqs = extractor.extract_requirements(saved["job_id"], job_data["snapshot_text"])
                storage.save_requirements(saved["job_id"], extracted_reqs)
                st.success(f"Successfully ingested '{job_data['title']}' at {job_data['company']} ({len(extracted_reqs)} requirements extracted).")
                st.rerun()
        except JobIngestError as e:
            st.error(f"Ingestion Blocked: {e.message}")
            st.info("Tip: Use the manual paste accordion above to paste the job description while retaining the link.")
        except Exception as e:
            st.error(f"Error fetching job: {e}")

    if paste_btn and paste_text:
        saved = storage.save_job(
            title=paste_title,
            company=paste_company,
            source_name="Direct Paste",
            source_url=paste_url,
            snapshot_text=paste_text
        )
        extractor = get_requirement_extractor()
        extracted_reqs = extractor.extract_requirements(saved["job_id"], paste_text)
        storage.save_requirements(saved["job_id"], extracted_reqs)
        st.success(f"Saved manual posting '{paste_title}' ({len(extracted_reqs)} requirements extracted).")
        st.rerun()

    # List Stored Jobs
    jobs = storage.list_jobs()
    if jobs:
        st.divider()
        st.subheader("Select Active Job Posting for Gap Analysis")
        job_options = {f"{j['title']} @ {j['company']} ({j['retrieved_at'][:10]})": j["job_id"] for j in jobs}
        selected_job_label = st.selectbox("Active Target Posting", list(job_options.keys()))
        selected_job_id = job_options[selected_job_label]

        active_job = storage.get_job(selected_job_id)
        if active_job:
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**Company:** {active_job['company']}")
            c2.markdown(f"**Source:** [{active_job['source_name']}]({active_job['source_url']})")
            c3.markdown(f"**Retrieved:** {active_job['retrieved_at'][:19].replace('T', ' ')} UTC")

            with st.expander("View Job Description Snapshot", expanded=False):
                st.text(active_job["snapshot_text"])
    else:
        selected_job_id = None


# ----------------------------------------------------
# TAB 1: Requirement & Gap Matrix
# ----------------------------------------------------
with tab_matrix:
    if not jobs:
        st.info("Please load the demo scenario or ingest a job posting in the 'Target Job Posting' tab.")
    else:
        reqs = storage.get_requirements_for_job(selected_job_id)
        assessments_list = storage.get_latest_assessments(student_id)
        assessments_map = {a["skill_id"]: a for a in assessments_list}

        # Group evidence by skill
        all_active_ev = storage.get_active_evidence_for_student(student_id)
        ev_by_skill = {}
        for ev in all_active_ev:
            ev_by_skill.setdefault(ev["skill_id"], []).append(ev)

        scope_desc = f"{len(selected_repos)} repo(s)"
        gap_analyzer = GapAnalyzer()
        gap_results = gap_analyzer.analyze_gaps(
            requirements=reqs,
            assessments=assessments_map,
            evidence_by_skill=ev_by_skill,
            scope_summary=scope_desc
        )

        # High-level Metrics Cards (FR-20)
        counts = gap_results["counts"]
        cov_pct = gap_results["portfolio_coverage_pct"]

        m1, m2, m3, m4, m5 = st.columns(5)
        with m1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Demonstrated</div>
                <div class="metric-value" style="color: #34d399;">{counts.get('Demonstrated', 0)}</div>
            </div>
            """, unsafe_allow_html=True)
        with m2:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Partially Demonstrated</div>
                <div class="metric-value" style="color: #fde047;">{counts.get('Partially demonstrated', 0)}</div>
            </div>
            """, unsafe_allow_html=True)
        with m3:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Not Demonstrated</div>
                <div class="metric-value" style="color: #fca5a5;">{counts.get('Not demonstrated in this scope', 0)}</div>
            </div>
            """, unsafe_allow_html=True)
        with m4:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Non-Code Requirements</div>
                <div class="metric-value" style="color: #cbd5e1;">{counts.get('Not assessable from code', 0)}</div>
            </div>
            """, unsafe_allow_html=True)
        with m5:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Coverage of Requirements</div>
                <div class="metric-value" style="color: #818cf8;">{cov_pct}%</div>
            </div>
            """, unsafe_allow_html=True)

        st.caption("ℹ️ **Compliance Note (FR-20, Section 8.5):** Portfolio coverage represents verified evidence alignment across the listed technical requirements. It is an objective coverage metric, not a predictive score of employability or candidate competence.")

        st.subheader("📋 Requirement-to-Evidence Alignment Matrix")

        # Render Matrix Rows
        for row in gap_results["matrix_rows"]:
            state = row["state"]
            if state == "Demonstrated":
                badge_html = '<span class="badge-demonstrated">Demonstrated</span>'
            elif state == "Partially demonstrated":
                badge_html = '<span class="badge-partial">Partially Demonstrated</span>'
            elif state == "Not assessable from code":
                badge_html = '<span class="badge-not-assessable">Not Assessable From Code</span>'
            else:
                badge_html = '<span class="badge-not-demonstrated">Not Demonstrated</span>'

            importance_badge = "🔴 Must-Have" if row["importance"] == "must" else "🟡 Nice-to-Have"

            with st.container():
                st.markdown(f"""
                <div style="background-color: #1e293b; border-radius: 8px; padding: 14px; margin-bottom: 12px; border: 1px solid #334155;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="font-size: 1.1rem; font-weight: 600; color: #f1f5f9;">{row['skill_name']} &nbsp; {badge_html}</span>
                        <span style="font-size: 0.85rem; color: #cbd5e1;">{importance_badge} | Confidence: <strong>{row['confidence']}</strong></span>
                    </div>
                    <div style="font-size: 0.9rem; color: #94a3b8; margin-bottom: 8px;">
                        <em>Posting Excerpt:</em> "{row['raw_text_snippet']}"
                    </div>
                    <div style="font-size: 0.9rem; color: #e2e8f0; background: #0f172a; padding: 10px; border-radius: 6px;">
                        <strong>Audit Assessment:</strong> {row['explanation']}
                    </div>
                    <div style="font-size: 0.85rem; color: #38bdf8; margin-top: 6px;">
                        💡 <strong>Actionable Hint:</strong> {row['closing_hint']}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                if row["evidence"]:
                    with st.expander(f"View {len(row['evidence'])} Supporting Evidence Snippet(s) for {row['skill_name']}"):
                        for ev in row["evidence"]:
                            st.markdown(f"""
                            **File:** `{ev['file_path']}` (Lines {ev['line_start']}–{ev['line_end']})
                            **Signal:** `{ev['strength']}` ({ev['signal_type']}) | **Commit:** `{ev['commit_sha'][:7]}`
                            🔗 [Open Commit Permalink on GitHub]({ev['permalink']})
                            """)
                            st.code(ev["excerpt"])


# ----------------------------------------------------
# TAB 3: Evidence Inspector
# ----------------------------------------------------
with tab_evidence:
    st.subheader("🔎 Deep Evidence Inspector (SRS Section 4.6 FR-31)")
    all_ev = storage.get_active_evidence_for_student(student_id)

    if not all_ev:
        st.info("No active evidence records in scope. Ingest repositories or trigger a change event.")
    else:
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            skills_found = sorted(list({e["skill_name"] for e in all_ev}))
            filter_skill = st.selectbox("Filter by Skill", ["All Skills"] + skills_found)
        with filter_col2:
            strengths_found = ["All Strengths", "Strong", "Corroborating", "Weak"]
            filter_strength = st.selectbox("Filter by Signal Strength", strengths_found)

        filtered = all_ev
        if filter_skill != "All Skills":
            filtered = [e for e in filtered if e["skill_name"] == filter_skill]
        if filter_strength != "All Strengths":
            filtered = [e for e in filtered if e["strength"] == filter_strength]

        st.markdown(f"Showing **{len(filtered)}** verified evidence records:")

        for ev in filtered:
            with st.container():
                st.markdown(f"""
                <div class="evidence-card">
                    <div style="display:flex; justify-content:space-between;">
                        <span style="font-weight:600; font-size:1.05rem; color:#f8fafc;">
                            {ev['skill_name']} &nbsp;
                            <span style="font-size:0.8rem; background:#334155; padding:2px 8px; border-radius:4px; color:#38bdf8;">
                                {ev['strength']} ({ev['signal_type']})
                            </span>
                        </span>
                        <span style="font-size:0.85rem; color:#94a3b8;">
                            Repo: <code>{ev['repo_name']}</code>
                        </span>
                    </div>
                    <div style="font-size:0.85rem; color:#cbd5e1; margin:6px 0;">
                        File: <code>{ev['file_path']}</code> (L{ev['line_start']}–L{ev['line_end']}) &bull; Commit: <code>{ev['commit_sha'][:8]}</code> &bull; Student Author: {'✅ Verified' if ev['authored_by_student'] else '⚠️ Unverified'}
                    </div>
                    <div style="margin-top:6px;">
                        <a href="{ev['permalink']}" target="_blank" style="color:#60a5fa; text-decoration:none; font-size:0.85rem;">
                            🔗 View GitHub Permitted Permalink
                        </a>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                st.code(ev["excerpt"])


# ----------------------------------------------------
# TAB 4: Activity Feed & Timeline
# ----------------------------------------------------
with tab_history:
    st.subheader("⏱️ Live Change Feed & Immutable Audit Log (FR-27, FR-28, FR-32)")

    events = storage.get_event_feed(limit=20)
    if not events:
        st.info("No push or polling events recorded yet. Click 'Simulate Commit' in the sidebar to test.")
    else:
        for ev in events:
            ev_time = ev["processed_at"][:19].replace("T", " ")
            ch_files = ev.get("changed_files", [])
            aff_skills = ev.get("affected_skills", [])

            with st.container():
                st.markdown(f"""
                <div style="background-color: #1e293b; border-left: 4px solid #3b82f6; border-radius: 6px; padding: 12px; margin-bottom: 12px;">
                    <div style="display:flex; justify-content:space-between;">
                        <span style="font-weight:600; color:#93c5fd;">
                            Event: <code>{ev['delivery_id']}</code> ({ev['source'].upper()})
                        </span>
                        <span style="font-size:0.85rem; color:#94a3b8;">{ev_time} UTC</span>
                    </div>
                    <div style="font-size:0.9rem; color:#e2e8f0; margin-top:4px;">
                        Repository: <code>{ev.get('repo_name', 'default')}</code> &bull; Commits: <code>{ev.get('before_sha', '')[:7]} &rarr; {ev.get('after_sha', '')[:7]}</code>
                    </div>
                    <div style="font-size:0.85rem; color:#cbd5e1; margin-top:6px;">
                        <strong>Changed Files ({len(ch_files)}):</strong> {', '.join(ch_files) if ch_files else 'None'}<br>
                        <strong>Affected Skills ({len(aff_skills)}):</strong> {', '.join(aff_skills) if aff_skills else 'None'}
                    </div>
                </div>
                """, unsafe_allow_html=True)

    st.divider()
    st.subheader("Skill State Evolution History")
    all_skills = storage.get_all_skills()
    history_skill_options = {s["name"]: s["skill_id"] for s in all_skills}
    hist_choice = st.selectbox("Select Skill to View Timeline", list(history_skill_options.keys()))

    if hist_choice:
        chosen_id = history_skill_options[hist_choice]
        hist_records = storage.get_assessment_history(student_id, chosen_id)
        if not hist_records:
            st.info(f"No history recorded yet for {hist_choice}.")
        else:
            for h in hist_records:
                st.markdown(f"""
                - **Version {h['version']}** ({h['created_at'][:19].replace('T', ' ')} UTC):
                  State: `{h['previous_state']}` &rarr; **`{h['state']}`** (Confidence: {h['confidence']})
                  *Rationale:* {h['rationale']}
                  *Trigger SHA:* `{(h['trigger_sha'] or '')[:7]}`
                """)


# ----------------------------------------------------
# TAB 5: Resume & Growth Plan (FR-35, FR-36, FR-37)
# ----------------------------------------------------
with tab_growth:
    st.subheader("🚀 Growth & Portfolio Artifacts (SRS Section 4.7)")

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.markdown("#### 📄 Evidence-Backed Resume Suggestions (FR-35)")
        st.caption("Auto-generated bullet points strictly derived from Demonstrated skills with traceable code files.")

        if jobs:
            reqs = storage.get_requirements_for_job(selected_job_id)
            assessments_list = storage.get_latest_assessments(student_id)
            assessments_map = {a["skill_id"]: a for a in assessments_list}
            all_active_ev = storage.get_active_evidence_for_student(student_id)
            ev_by_skill = {}
            for ev in all_active_ev:
                ev_by_skill.setdefault(ev["skill_id"], []).append(ev)

            gap_analyzer = GapAnalyzer()
            gap_results = gap_analyzer.analyze_gaps(reqs, assessments_map, ev_by_skill, "portfolio")
            suggestions = gap_analyzer.generate_resume_suggestions(gap_results["matrix_rows"])

            if not suggestions:
                st.info("Demonstrate skills in your codebase to unlock evidence-backed resume bullet points.")
            else:
                for sug in suggestions:
                    st.markdown(f"""
                    * **{sug['skill']}**: {sug['bullet_point']}
                      *(Evidence: [`{sug['evidence_file']}`]({sug['permalink']}))*
                    """)

    with col_g2:
        st.markdown("#### 🎯 Gap Closing Recommendations (FR-36)")
        st.caption("Actionable, concrete implementation steps to close gaps identified for this role.")

        if jobs:
            for row in gap_results["matrix_rows"]:
                if row["state"] != "Demonstrated" and row["assessable"]:
                    st.markdown(f"""
                    **{row['skill_name']}** ({row['state']})
                    &bull; {row['closing_hint']}
                    """)
# Ollama AI-Powered Skill Gap Recommendations
    st.divider()
    st.subheader("🤖 AI-Powered Skill Gap Recommendations")

    if st.button("✨ Generate AI Recommendations", key="ollama_recommend"):
        from modules.gap_analyzer import generate_ollama_recommendations

        if jobs and gap_results["matrix_rows"]:
            with st.spinner("Ollama is analyzing your skill gaps..."):
                ai_result = generate_ollama_recommendations(
                    gap_results["matrix_rows"]
                )

            st.session_state["ollama_recommendations"] = ai_result
        else:
            st.warning("Please select a job and analyze your portfolio first.")

    if "ollama_recommendations" in st.session_state:
        st.markdown(st.session_state["ollama_recommendations"])
    st.divider()
    st.subheader("📥 Export Verification Report (FR-37)")

    if jobs:
        export_payload = {
            "student_username": username_input,
            "export_timestamp": datetime.now(timezone.utc).isoformat(),
            "target_job": {
                "title": active_job["title"] if active_job else "None",
                "company": active_job["company"] if active_job else "None",
                "source_url": active_job["source_url"] if active_job else "None"
            },
            "summary_metrics": gap_results["counts"],
            "portfolio_coverage_pct": gap_results["portfolio_coverage_pct"],
            "matrix": [
                {
                    "skill": r["skill_name"],
                    "state": r["state"],
                    "confidence": r["confidence"],
                    "requirement": r["raw_text_snippet"],
                    "evidence_count": r["evidence_count"],
                    "explanation": r["explanation"]
                }
                for r in gap_results["matrix_rows"]
            ]
        }
        json_str = json.dumps(export_payload, indent=2)
        st.download_button(
            label="Download Verification Report (JSON)",
            data=json_str,
            file_name=f"skilltrace_report_{username_input}.json",
            mime="application/json"
        )


# Disclaimer footer (FR-33, Section 8.5, Section 12.4)
st.markdown("""
<div class="disclaimer-box">
    <strong>⚖️ SkillTrace Responsible AI & Fair Evaluation Disclaimer (SRS Section 8.5 & 12.4):</strong><br>
    The assessments, state classifications, and matrix coverages displayed on this dashboard reflect solely the analyzed code repositories, tracked branches, and specified commit ranges.
    The absence of evidence in a portfolio does <em>not</em> prove that a candidate lacks the skill. SkillTrace outputs are objective traceability signals and do not constitute hiring decisions or complete employability predictions.
</div>
""", unsafe_allow_html=True)
st.divider()
