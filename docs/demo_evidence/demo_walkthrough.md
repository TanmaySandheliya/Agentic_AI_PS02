# SkillTrace Demo Walkthrough Script
Adheres to SRS Section 18 (5-Minute Demonstration + 3-Minute Q&A).

## Timing and Script

### 0:00–0:30 | The Problem
- Explain that static resumes and portfolios go stale.
- Candidates claim skills, but hiring teams and students cannot easily verify whether code repositories demonstrate those claims at commit depth.

### 0:30–1:15 | Job Requirements Ingestion
- Open the SkillTrace Dashboard (`http://localhost:8501`).
- Switch to the **Target Job Posting** tab.
- Click **Fetch & Analyze Job** with a real posting (e.g. Greenhouse/Lever posting).
- Show how SkillTrace preserves:
  1. The original source link.
  2. The verbatim posting text snippet.
  3. Automatic classification into **Must-Have** vs **Nice-to-Have**.
  4. Non-code requirements (e.g. degree, soft skills) marked as *Not assessable from code*.

### 1:15–2:15 | Repository Evidence Analysis
- Click **Load Pre-Populated Demo Scenario** in the sidebar.
- Inspect the **Requirement & Gap Matrix**:
  - `Python`: **Demonstrated** (High Confidence) &mdash; verified in `app/main.py`.
  - `FastAPI`: **Demonstrated** (High Confidence) &mdash; verified in `app/main.py` + manifest in `requirements.txt`.
  - `Docker`: **Demonstrated** (High Confidence) &mdash; verified in `Dockerfile`.
  - `Unit Testing`: **Demonstrated** &mdash; verified in `tests/test_api.py`.
- Click on **Evidence Inspector** to show commit-pinned GitHub permalinks with line numbers.

### 2:15–3:00 | Gap Analysis
- Point out `SQL`:
  - Current State: **Not demonstrated in this scope**.
  - Review the plain-language explanation:
    *"Not demonstrated in this scope. This does not mean the skill is absent. Found 0 executable code or test signals."*
  - Review the actionable closing hint:
    *"Commit a `.sql` schema migration, table creation script, or backend code executing queries against a database."*

### 3:00–4:15 | Code Change & Incremental Reassessment
- Click the sidebar button: **⚡ Simulate Commit: 'Add SQL queries & migrations'** (or push an actual commit through `POST /webhooks/github`).
- Observe the webhook receiver verify HMAC-SHA256 signature and execute incremental reassessment.
- Observe the **Live Change Feed**:
  - Event `sim_f9e8d7c6b5` received.
  - Affected skills mapped: `["sql"]`.
  - Unaffected skills (`python`, `docker`, `fastapi`) remained untouched.

### 4:15–5:00 | Updated Assessment & Evolution Timeline
- Switch back to the **Requirement & Gap Matrix**:
  - `SQL` has dynamically transitioned:
    `Not demonstrated in this scope` &rarr; **`Demonstrated`** (citing `db/schema.sql` and `app/database.py`).
  - Portfolio coverage metric automatically recalculated.
- Open **Activity Feed & Timeline** to inspect the version history (Version 1 &rarr; Version 2) with trigger SHA and exact diff.
- Open **Resume & Learning Growth** to show the newly unlocked resume bullet point with verified evidence file link.

---

## Key Q&A Talking Points
1. **Absence is not inability:** Absence of evidence in a portfolio does not mean the student lacks the skill; it only means it is not demonstrated in the analyzed commits.
2. **Authorship & Originality:** Lockfiles (`package-lock.json`), vendored packages (`node_modules`), and forks are strictly excluded.
3. **Security:** GitHub webhooks use constant-time `hmac.compare_digest` with SHA256; delivery IDs prevent replay attacks.
4. **Reliability:** When webhooks are disabled, conditional ETag polling (`If-None-Match`) prevents rate limit exhaustion.
