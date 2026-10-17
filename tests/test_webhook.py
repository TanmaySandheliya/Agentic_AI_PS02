"""
Unit tests for GitHub Webhook Receiver and Signature Verification.
Covers SRS Section 4.5 (FR-21, FR-22, FR-29) and Section 13.2 TC-07, TC-08.
"""
import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from api import app
from config import settings
from modules import storage


@pytest.fixture
def client(tmp_path):
    # Set temporary database
    db_file = str(tmp_path / "test_webhook.db")
    settings.database_path = db_file
    storage.init_db(db_file)
    return TestClient(app)


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), msg=payload_bytes, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def test_webhook_invalid_signature_rejected(client):
    """
    SRS TC-07: Webhook with invalid or missing signature is rejected.
    """
    payload = {"zen": "Keep it logically awesome."}
    body = json.dumps(payload).encode("utf-8")

    # Missing signature header
    resp1 = client.post("/webhooks/github", content=body, headers={"X-GitHub-Event": "ping"})
    assert resp1.status_code == 401

    # Tampered signature
    resp2 = client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": "ping",
        "X-Hub-Signature-256": "sha256=invalidhex00000000000000000000000000000000000000000000000000000000"
    })
    assert resp2.status_code == 401


def test_webhook_ping_event_success(client):
    """
    SRS FR-21: Endpoint accepts ping events and returns pong.
    """
    payload = {"zen": "Responsive is better than fast.", "hook_id": 12345}
    body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body, settings.webhook_secret)

    resp = client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": "delivery-ping-101",
        "X-Hub-Signature-256": sig
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "pong"
    assert data["status"] == "active"


def test_webhook_duplicate_idempotency(client):
    """
    SRS TC-08: Duplicate webhook delivery is processed only once (idempotent).
    """
    student = storage.get_or_create_student("teststudent")
    storage.upsert_repository(student["student_id"], "teststudent/testrepo")

    payload = {
        "repository": {"full_name": "teststudent/testrepo"},
        "before": "0000000000000000000000000000000000000000",
        "after": "1111111111111111111111111111111111111111",
        "commits": [{"added": [], "modified": [], "removed": []}]
    }
    body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body, settings.webhook_secret)
    delivery_id = "test-delivery-idempotent-99"

    # First delivery
    resp1 = client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": sig
    })
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "accepted"

    # Duplicate delivery with same delivery ID
    resp2 = client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": sig
    })
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "skipped"
