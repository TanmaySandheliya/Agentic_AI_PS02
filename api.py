"""
SkillTrace FastAPI Webhook Server.
Exposes endpoints for GitHub webhook ingestion (HMAC-SHA256 verified) and system health.
Adheres to SRS Section 4.5 (FR-21, FR-22, FR-29), Section 6.3, and Section 7.3.
"""
import logging
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Header, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import uvicorn

from config import settings
from modules import storage
from modules.change_agent import verify_webhook_signature, ChangeAgent
from modules.github_client import GitHubClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("skilltrace.api")

app = FastAPI(
    title="SkillTrace Webhook & Ingestion API",
    description="Real-time GitHub webhook receiver and change-detection pipeline for SkillTrace portfolio verification.",
    version="1.0.0"
)

# Initialize storage and agent
storage.init_db()
change_agent = ChangeAgent()


@app.get("/")
def root():
    return {
        "service": "SkillTrace API",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "health": "/health",
            "webhook": "POST /webhooks/github",
            "poll": "POST /api/poll"
        }
    }


@app.get("/health")
def health_check():
    """Health check endpoint providing rate limit and database status."""
    gh = GitHubClient()
    rate_info = gh.get_rate_limit()
    return {
        "status": "healthy",
        "database": settings.database_path,
        "github_rate_limit": rate_info
    }


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256")
):
    """
    Receives GitHub webhook events (push, ping).
    Verifies HMAC-SHA256 signature and triggers incremental reassessment (FR-21, FR-22, FR-29).
    """
    body_bytes = await request.body()

    # 1. Signature Verification (FR-22, TC-07)
    if not verify_webhook_signature(body_bytes, x_hub_signature_256, settings.webhook_secret):
        logger.warning("Rejected webhook delivery %s: Invalid or missing HMAC signature", x_github_delivery)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Hub-Signature-256 signature"
        )

    # 2. Ping Event Handling (SRS FR-21)
    if x_github_event == "ping":
        logger.info("Received ping event from GitHub (delivery: %s)", x_github_delivery)
        return {"message": "pong", "status": "active", "delivery_id": x_github_delivery}

    # 3. Push Event Handling
    if x_github_event == "push":
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        repo_info = payload.get("repository", {})
        repo_full_name = repo_info.get("full_name")
        before_sha = payload.get("before", "")
        after_sha = payload.get("after", "")
        commits = payload.get("commits", [])
        delivery_id = x_github_delivery or f"webhook_{after_sha}"

        if not repo_full_name or not after_sha:
            raise HTTPException(status_code=400, detail="Missing repository full_name or after SHA")

        # Collect changed files across all commits in push
        changed_files_map = {}
        for c in commits:
            for f in c.get("added", []):
                changed_files_map[f] = {"filename": f, "status": "added"}
            for f in c.get("modified", []):
                changed_files_map[f] = {"filename": f, "status": "modified"}
            for f in c.get("removed", []):
                changed_files_map[f] = {"filename": f, "status": "removed"}

        changed_list = list(changed_files_map.values())

        # Check idempotency
        if storage.is_event_processed(delivery_id):
            return {"status": "skipped", "message": "Duplicate delivery already processed", "delivery_id": delivery_id}

        # Run reassessment
        result = change_agent.process_change_event(
            repo_full_name=repo_full_name,
            before_sha=before_sha,
            after_sha=after_sha,
            changed_files_info=changed_list,
            delivery_id=delivery_id,
            source="webhook"
        )

        return {
            "status": "accepted",
            "delivery_id": delivery_id,
            "details": result
        }

    return {"status": "ignored", "message": f"Event '{x_github_event}' not processed."}


@app.post("/api/poll")
def trigger_polling():
    """Manual polling trigger for all tracked repositories (FR-23, TC-11)."""
    gh = GitHubClient()
    conn = storage.get_connection()
    repos = conn.execute("SELECT * FROM repositories WHERE selected = 1").fetchall()
    conn.close()

    results = []
    for r in repos:
        repo_name = r["full_name"]
        tracked_branch = r["tracked_branch"] or "main"
        last_sha = r["last_analysed_sha"]

        try:
            head_sha = gh.get_branch_head_sha(repo_name, tracked_branch)
            if last_sha and head_sha != last_sha:
                changed = gh.get_changed_files_between_commits(repo_name, last_sha, head_sha)
                delivery_id = f"poll_{repo_name}_{head_sha[:10]}"
                res = change_agent.process_change_event(
                    repo_full_name=repo_name,
                    before_sha=last_sha,
                    after_sha=head_sha,
                    changed_files_info=changed,
                    delivery_id=delivery_id,
                    source="poll"
                )
                results.append(res)
            else:
                results.append({"repo": repo_name, "status": "up-to-date", "sha": head_sha})
        except Exception as e:
            results.append({"repo": repo_name, "status": "error", "message": str(e)})

    return {"polled_count": len(repos), "results": results}


if __name__ == "__main__":
    uvicorn.run("api:app", host=settings.api_host, port=settings.api_port, reload=True)
