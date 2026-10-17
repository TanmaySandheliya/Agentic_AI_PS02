# 🛡️ SkillTrace

> **Automated GitHub Portfolio & Job Requirement Verification System**
> *Traceable, conservative skill judgements with real-time incremental change detection.*
> Compliant with **SkillTrace SRS v1.0**.

---

## 🌟 Executive Overview

SkillTrace is a software engineering intelligence platform that automatically verifies a student's public GitHub portfolio against real-world job posting requirements.

Unlike traditional static resume scanners or unverified LLM summaries:
1. **Verifiable Traceability:** Every claimed skill is pinned to exact repository files, line ranges, commit SHAs, and GitHub permalinks.
2. **Conservative Multi-Tier Rubric:** Rigorously distinguishes **Strong** signals (source code usage, dedicated schemas/Dockerfiles) from **Corroborating** signals (package dependencies, unit tests) and **Weak** signals (README text).
3. **Automated Incremental Reassessment:** Subscribes to GitHub webhooks (HMAC-SHA256 verified) and conditional ETag polling. When code is pushed or deleted, SkillTrace identifies *only the affected skills* and updates judgements in real time without manual re-runs.
4. **Responsible AI & Fairness:** Adheres to the principle that *“Absence of evidence is not absence of skill.”* Gaps are paired with actionable guidance on what commits would demonstrate competence.

---

## 🏗️ Architecture & Component Responsibilities

```
SkillTrace Architecture
┌─────────────────────────────────────────────────────────────┐
│                 Streamlit Dashboard (app.py)                │
│  - Scope Selector        - Requirement & Gap Matrix         │
│  - Target Job Ingest     - Deep Evidence Inspector          │
│  - Live Audit Feed       - Resume & Learning Action Plan    │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
┌───────────────────────────┐         ┌───────────────────────────┐
│ FastAPI Webhook (api.py)  │         │   Storage Layer (SQLite)  │
│ - HMAC-SHA256 Validation  │◄───────►│  - Students & Repos       │
│ - Ping / Push Router      │         │  - Jobs & Requirements    │
│ - Polling Fallback Worker │         │  - Evidence & Assessments │
└─────────────┬─────────────┘         │  - Audit Event Log        │
              │                       └───────────────────────────┘
              ▼                                     ▲
┌───────────────────────────┐                       │
│    Change Agent Engine    │                       │
│ - Affected-Skill Mapper   │                       │
│ - Incremental Evaluator   │───────────────────────┘
└─────────────┬─────────────┘
              │
      ┌───────┴───────┬─────────────────┬─────────────────┐
      ▼               ▼                 ▼                 ▼
┌───────────┐   ┌───────────┐     ┌───────────┐     ┌───────────┐
│ Taxonomy  │   │ Evidence  │     │ Assessment│     │    Gap    │
│(skills.yml│   │ Analyzer  │     │  Engine   │     │ Analyzer  │
└───────────┘   └───────────┘     └───────────┘     └───────────┘
```

| Component | File | Responsibilities |
| :--- | :--- | :--- |
| **User Interface** | `app.py` | Interactive dashboard displaying requirement matrices, confidence badges, permalinks, and before-and-after timelines. |
| **API Server** | `api.py` | FastAPI server exposing `POST /webhooks/github` and `GET /health` with constant-time HMAC-SHA256 validation. |
| **Configuration** | `config.py` | Centralized settings for GitHub tokens, webhook secret, SQLite path, and vendor exclusions. |
| **Taxonomy** | `taxonomy/skills.yaml` | Taxonomy rules for 25+ skills, defining aliases, code regexes, and multi-tier detection patterns. |
| **Storage** | `modules/storage.py` | SQLite implementation for Section 9.2 tables (`students`, `repositories`, `jobs`, `requirements`, `evidence`, `assessments`, `events`). |
| **Job Discovery** | `modules/job_sources/` | Adapters for Greenhouse, Lever, and arbitrary career pages using BeautifulSoup4 snapshot extraction. |
| **Requirement Extractor** | `modules/requirement_extractor.py` | Parses job snapshots into verbatim text snippets, classifying must-have vs. nice-to-have, and identifying non-code requirements. |
| **GitHub Client** | `modules/github_client.py` | Authenticated PyGithub integration handling tree recursion, file contents, conditional ETag polling, and permalink generation. |
| **Evidence Analyzer** | `modules/evidence_analyzer.py` | Scans files for Strong, Corroborating, and Weak signals, strictly excluding vendored (`node_modules`) and generated lockfiles. |
| **Assessment Engine** | `modules/assessment_engine.py` | Implements the Section 8.2 Rubric (`Demonstrated`, `Partially demonstrated`, `Not demonstrated in this scope`, `Not assessable from code`). |
| **Gap Analyzer** | `modules/gap_analyzer.py` | Compares requirements with portfolio evidence, generates plain-language gap explanations, and creates evidence-backed resume suggestions. |
| **Change Agent** | `modules/change_agent.py` | Webhook verification, commit file comparison, affected-skill mapper, and incremental reassessment orchestration. |

---

## 🚀 Quickstart & Installation

### 1. Prerequisites
- Python 3.11+ (Tested and verified on Python 3.14)
- Git

### 2. Environment Setup
Clone the repository and install all dependencies:
```bash
git clone https://github.com/your-org/skilltrace.git
cd skilltrace
python -m pip install -r requirements.txt
```

### 3. Environment Configuration (Optional)
Create an optional `.env` file or export environment variables:
```bash
# Optional: GitHub PAT to increase API rate limit from 60 to 5,000 req/hr
export GITHUB_TOKEN="ghp_yourPersonalAccessTokenHere"

# Shared secret for verifying GitHub Webhooks
export WEBHOOK_SECRET="skilltrace_dev_secret_2026"

# Port configurations
export API_PORT=8000
export DASHBOARD_PORT=8501
```

---

## 💻 Running the Application

### Option A: Launch Both Services (Recommended)

In Terminal 1 &mdash; Start the FastAPI Webhook Receiver:
```bash
python api.py
```
*API will run at `http://localhost:8000` (Health check: `http://localhost:8000/health`).*

In Terminal 2 &mdash; Start the Streamlit Dashboard:
```bash
streamlit run app.py --server.port 8501
```
*The dashboard will automatically open in your browser at `http://localhost:8501`.*

---

## ⚡ 5-Minute Live Demo Walkthrough (SRS Section 18)

Follow these exact steps to demonstrate the end-to-end functionality:

1. **Onboard & Consent (0:00–0:30):**
   - Open `http://localhost:8501`.
   - Verify the student username is entered and consent is checked.
   - Click **🚀 Load Pre-Populated Demo Scenario** in the sidebar. This seeds a sample repository (`demo-student/cloud-task-manager`) and real job posting.
2. **Review Initial Baseline (0:30–2:15):**
   - In the **Requirement & Gap Matrix** tab, observe:
     - `Python`: **Demonstrated** (High Confidence) &mdash; verified in `app/main.py`.
     - `FastAPI`: **Demonstrated** (High Confidence) &mdash; verified in `app/main.py` + `requirements.txt`.
     - `Docker`: **Demonstrated** (High Confidence) &mdash; verified in `Dockerfile`.
     - `SQL`: **Not demonstrated in this scope**.
   - Review the explanation: *"Searched across repo: demo-student/cloud-task-manager. Found 0 executable code or test signals. Not demonstrated in this scope. This does not mean the skill is absent."*
3. **Simulate a Live Commit (2:15–3:45):**
   - In the sidebar, click the button: **⚡ Simulate Commit: 'Add SQL queries & migrations'**.
   - This simulates a push event adding `db/schema.sql` and `app/database.py`.
   - Notice the instant notification: *"Pushed live commit! Reassessment triggered automatically."*
4. **Observe Incremental Reassessment (3:45–5:00):**
   - In the **Requirement & Gap Matrix** tab:
     - `SQL` has automatically transitioned to **Demonstrated** (High Confidence).
     - New active evidence records are linked with permalinks.
     - Unaffected skills (`Python`, `Docker`, `FastAPI`) remain completely unchanged.
   - Switch to **Activity Feed & Timeline**:
     - View the audit entry showing before-and-after commit SHAs, changed files, and affected skills (`["sql"]`).
     - Inspect the SQL evolution history (Version 1: Not demonstrated &rarr; Version 2: Demonstrated).
   - Switch to **Resume & Learning Growth**:
     - See the newly unlocked, evidence-backed resume bullet point citing `db/schema.sql`.

---

## 🌐 Configuring GitHub Webhooks with ngrok

To receive real webhook pushes from GitHub repositories:

1. Start ngrok on port 8000:
   ```bash
   ngrok http 8000
   ```
2. Copy the public forwarding URL (e.g. `https://abc1234.ngrok-free.app`).
3. In your GitHub repository:
   - Navigate to **Settings &rarr; Webhooks &rarr; Add webhook**.
   - **Payload URL:** `https://abc1234.ngrok-free.app/webhooks/github`
   - **Content type:** `application/json`
   - **Secret:** `skilltrace_dev_secret_2026` (or your configured `WEBHOOK_SECRET`)
   - **Events:** Select *Just the push event*.
4. Push a commit to your repository. SkillTrace will verify the signature and reassess affected skills immediately!

---

## 🧪 Running the Test Suite

SkillTrace includes a full unit test suite covering Section 13.2 test cases:
```bash
python -m pytest -v
```

### Test Suite Coverage:
- `tests/test_detectors.py`: Verifies Strong, Corroborating, and Weak signals, as well as strict exclusion of vendored directories and lockfiles (`TC-05`, `TC-06`).
- `tests/test_assessment.py`: Verifies Section 8.2 evidence rubric transitions, confidence ratings, and non-code requirements (`TC-03`, `TC-05`).
- `tests/test_webhook.py`: Validates constant-time HMAC-SHA256 signature verification, rejection of tampered payloads, and delivery idempotency (`TC-07`, `TC-08`).
- `tests/test_reassessment.py`: Tests incremental reassessment, affected-skill computation, documentation-only changes (`TC-09`), and evidence superseding upon deletion (`TC-04`, `TC-10`).

---

## ⚖️ Responsible AI & Ethical Principles

1. **Absence is Not Inability (SRS Section 8.5):** SkillTrace explicitly labels results as reflective only of the analyzed repositories and commits. Absence of code does not imply lack of skill.
2. **Authorship Verification:** Generated code, third-party libraries, and forked codebases are excluded to prevent false credit attribution.
3. **Traceability First:** Every assessment references exact line numbers and commit hashes. SkillTrace never presents unverified assertions.
