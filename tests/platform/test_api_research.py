"""Investigaciones: modo básico, pipeline con IA, auditoría y presupuesto."""

from __future__ import annotations

import time

from tests.platform.conftest import auth_headers, register

TERMINAL = {"completed", "failed", "cancelled"}


def wait_job(client, headers, job_id: int, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/research/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in TERMINAL:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Trabajo {job_id} sin terminar: {last}")


def test_basic_research_without_ai(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)

    created = client.post(
        "/api/v1/research",
        headers=headers,
        json={"ticker": "AAPL", "profile": "basic"},
    )
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["profile"] == "basic"

    finished = wait_job(client, headers, job["id"])
    assert finished["status"] == "completed", finished
    assert finished["report_id"]

    report = client.get(f"/api/v1/reports/{finished['report_id']}", headers=headers).json()
    sections = {section["id"]: section for section in report["sections"]}
    assert len(sections) >= 18
    assert "identification" in sections and "conclusion" in sections
    assert "ledger" not in sections
    assert sections["identification"]["basis"] == "fact"
    assert sections["business"]["basis"] == "unavailable"
    assert "no se genera" in sections["business"]["bullets"][0]
    assert sections["scenarios"]["table"]["rows"]
    assert report["audit"]["unsupported_count"] == 0
    assert "# Nexo Invest AI" in report["markdown"]
    assert report["provenance"]["source_url"]


def test_research_with_fake_ai_and_audit(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)

    plan = client.get("/api/v1/research/plan?profile=standard", headers=headers)
    assert plan.status_code == 200
    assert plan.json()["ai_available"] is True
    assert len(plan.json()["plan"]["roles"]) == 5

    created = client.post(
        "/api/v1/research",
        headers=headers,
        json={"ticker": "AAPL", "profile": "standard", "budget_usd": 1.0},
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]

    finished = wait_job(client, headers, job_id)
    assert finished["status"] == "completed", finished
    assert finished["attempts"] == 1

    steps = client.get(f"/api/v1/research/{job_id}/steps", headers=headers).json()["steps"]
    assert [step["role"] for step in steps] == [
        "business_researcher",
        "financial_analyst",
        "contrarian_analyst",
        "evidence_auditor",
        "coordinator",
    ]
    assert all(step["status"] == "completed" for step in steps), steps

    report = client.get(f"/api/v1/reports/{finished['report_id']}", headers=headers).json()
    sections = {section["id"]: section for section in report["sections"]}
    assert sections["business"]["basis"] == "ai"
    assert "hardware" in sections["business"]["paragraphs"][0]
    assert sections["thesis"]["basis"] == "ai"
    assert "No es precio objetivo" not in report["markdown"]

    audit = report["audit"]
    unsupported = [item["raw"] for item in audit["unsupported_numbers"]]
    assert any("987" in raw for raw in unsupported), audit
    assert audit["unknown_citations"] == []

    listed = client.get("/api/v1/research", headers=headers).json()
    assert listed["total"] == 1

    usage = client.get("/api/v1/settings", headers=headers).json()["usage"]
    assert usage["jobs"] == 1
    assert usage["tokens_in"] > 0


def test_budget_exhausted_forces_basic_profile(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    updated = client.patch(
        "/api/v1/settings", headers=headers, json={"monthly_budget_usd": 0}
    )
    assert updated.status_code == 200

    blocked = client.post(
        "/api/v1/research",
        headers=headers,
        json={"ticker": "AAPL", "profile": "standard"},
    )
    assert blocked.status_code == 402
    assert blocked.json()["error"]["code"] == "budget_exhausted"

    allowed = client.post(
        "/api/v1/research",
        headers=headers,
        json={"ticker": "AAPL", "profile": "basic"},
    )
    assert allowed.status_code == 202
    wait_job(client, headers, allowed.json()["id"])


def test_cancel_and_idempotence(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)

    created = client.post(
        "/api/v1/research", headers=headers, json={"ticker": "AAPL", "profile": "basic"}
    )
    job_id = created.json()["id"]
    wait_job(client, headers, job_id)

    cancelled = client.post(f"/api/v1/research/{job_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["changed"] is False
    assert cancelled.json()["status"] == "completed"

    missing = client.get("/api/v1/research/999999", headers=headers)
    assert missing.status_code == 404


def test_other_user_cannot_read_job(client):
    owner = register(client, email="dueno@nexo.invalid")["access_token"]
    intruder = register(client, email="intruso@nexo.invalid")["access_token"]
    created = client.post(
        "/api/v1/research",
        headers=auth_headers(owner),
        json={"ticker": "AAPL", "profile": "basic"},
    )
    job_id = created.json()["id"]
    assert (
        client.get(f"/api/v1/research/{job_id}", headers=auth_headers(intruder)).status_code
        == 404
    )
    assert (
        client.post(f"/api/v1/research/{job_id}/cancel", headers=auth_headers(intruder)).status_code
        == 404
    )
