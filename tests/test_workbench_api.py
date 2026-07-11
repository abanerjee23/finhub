from __future__ import annotations

import time


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from cfin_agents import document_store
    from cfin_agents.api import app

    monkeypatch.setattr(document_store, "DB_PATH", tmp_path / "finhub.db")
    monkeypatch.setenv("FINHUB_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DISABLE_LLM", "1")
    monkeypatch.setenv("SUMMARY_USE_LLM", "0")
    return TestClient(app)


def test_workbench_reset_and_sweep(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    status = client.get("/api/workbench/status")
    assert status.status_code == 200
    assert status.json()["ticket_count"] == 0

    reset = client.post("/api/workbench/reset?count=5&seed=7")
    assert reset.status_code == 200
    payload = reset.json()
    assert payload["seeded_documents"] == 5
    assert payload["ticket_count"] == 0
    assert payload["staging_counts"]["new"] == 5

    sweep = client.post("/api/workbench/sweep", json={"batch_size": 2, "wait": True})
    assert sweep.status_code == 200
    sweep_payload = sweep.json()
    assert sweep_payload["status"] == "completed"
    assert sweep_payload["processed"] == 2
    assert sweep_payload["created_tickets"] == 2
    assert sweep_payload["ticket_count"] == 2

    listed = client.get("/api/tickets")
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    assert listed.json()[0]["agent_summary"]
    assert listed.json()[0]["operator_status"] in {"assigned", "in_progress", "resolved", "blocked"}
    assert listed.json()[0]["amount"] > 0
    assert listed.json()[0]["currency"]
    assert listed.json()[0]["amount_usd"] > 0


def test_workbench_async_sweep_job(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post("/api/workbench/reset?count=3&seed=11")

    started = client.post("/api/workbench/sweep", json={"batch_size": 3})
    assert started.status_code == 200
    job = started.json()
    assert job["status"] in {"running", "completed"}
    job_id = job["job_id"]

    deadline = time.time() + 30
    while time.time() < deadline:
        polled = client.get(f"/api/workbench/sweep/jobs/{job_id}")
        assert polled.status_code == 200
        job = polled.json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.2)

    assert job["status"] == "completed"
    assert job["processed"] == 3
    assert job["created_tickets"] == 3
    assert "dashboard" in job

    missing = client.get("/api/workbench/sweep/jobs/SWEEP-UNKNOWN")
    assert missing.status_code == 404


def test_dashboard_business_metrics(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post("/api/workbench/reset?count=6&seed=3")
    client.post("/api/workbench/sweep", json={"batch_size": 6, "wait": True})

    summary = client.get("/api/dashboard/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["total_tickets"] == 6
    assert payload["total_value_usd"] > 0
    assert payload["open_value_usd"] > 0
    assert payload["open_value_by_company_code"]
    assert payload["open_value_by_source_system"]
    assert payload["value_by_currency"]
    assert set(payload["aging_buckets"]) == {"0-1d", "1-3d", "3-7d", "7d+"}
    assert 0.0 <= payload["automation_rate"] <= 1.0
    assert payload["fx_rates_to_usd"]["USD"] == 1.0


def test_approve_and_resolve_needs_approval_ticket(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post("/api/workbench/reset?count=12&seed=3")
    client.post("/api/workbench/sweep", json={"batch_size": 12, "wait": True})

    tickets = client.get("/api/tickets").json()
    pending = [row for row in tickets if row["workflow_status"] == "needs_approval"]
    assert pending, "expected at least one needs_approval ticket in seed 3"
    ticket_id = pending[0]["ticket_id"]

    approved = client.post(
        f"/api/tickets/{ticket_id}/approve",
        json={"actor": "Test Approver", "note": "Approved in test"},
    )
    assert approved.status_code == 200
    payload = approved.json()
    assert payload["workflow_run"]["status"] == "reprocessed"
    assert payload["operator_status"] == "resolved"
    actions = [event["action"] for event in payload["timeline"]]
    assert "approval_recorded" in actions
    assert payload["workflow_run"]["reprocess_result"]["target_document_id"]

    # A second approve on the now-reprocessed ticket must be rejected.
    again = client.post(f"/api/tickets/{ticket_id}/approve", json={"actor": "Test Approver"})
    assert again.status_code == 400


def test_maintain_mapping_resolves_mp_ticket(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post("/api/workbench/reset?count=12&seed=3")
    client.post("/api/workbench/sweep", json={"batch_size": 12, "wait": True})

    tickets = client.get("/api/tickets").json()
    mapping_tickets = [row for row in tickets if row["reason_code"].startswith("MP_")]
    assert mapping_tickets, "expected at least one MP_* ticket in seed 3"
    ticket_id = mapping_tickets[0]["ticket_id"]

    maintained = client.post(
        f"/api/tickets/{ticket_id}/maintain-mapping",
        json={"target_value": "CC-TARGET-999", "actor": "Test Analyst"},
    )
    assert maintained.status_code == 200
    payload = maintained.json()
    assert payload["operator_status"] == "resolved"
    events = {event["action"]: event for event in payload["timeline"]}
    assert "mapping_maintained" in events
    assert events["mapping_maintained"]["details"]["target_value"] == "CC-TARGET-999"
    assert events["mapping_maintained"]["details"]["source_value"] not in ("", None)

    # Mapping maintenance is invalid for master-data tickets.
    md_tickets = [row for row in tickets if row["reason_code"].startswith("MD_")]
    if md_tickets:
        rejected = client.post(
            f"/api/tickets/{md_tickets[0]['ticket_id']}/maintain-mapping",
            json={"target_value": "X"},
        )
        assert rejected.status_code == 400


def test_assignee_update_and_summary_feedback(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post("/api/workbench/reset?count=2&seed=5")
    client.post("/api/workbench/sweep", json={"batch_size": 2, "wait": True})

    tickets = client.get("/api/tickets").json()
    ticket_id = tickets[0]["ticket_id"]

    assignees = client.get("/api/workbench/assignees")
    assert assignees.status_code == 200
    names = [row["name"] for row in assignees.json()["assignees"]]
    assert "Maria Chen" in names

    reassigned = client.patch(
        f"/api/tickets/{ticket_id}/assignee",
        json={"assignee": "Maria Chen", "actor": "Test Lead"},
    )
    assert reassigned.status_code == 200
    assert reassigned.json()["assignee"] == "Maria Chen"
    assert any(event["action"] == "reassigned" for event in reassigned.json()["timeline"])

    feedback = client.post(
        f"/api/tickets/{ticket_id}/summary-feedback",
        json={"rating": "up", "note": "Clear and accurate."},
    )
    assert feedback.status_code == 200
    assert feedback.json()["summary_feedback"]["rating"] == "up"


def test_ticket_mutations_use_per_ticket_writes(tmp_path, monkeypatch) -> None:
    """A mutation on one ticket must not rewrite (and clobber) other rows."""
    from cfin_agents import document_store

    client = _client(tmp_path, monkeypatch)
    client.post("/api/workbench/reset?count=3&seed=5")
    client.post("/api/workbench/sweep", json={"batch_size": 3, "wait": True})

    tickets = client.get("/api/tickets").json()
    first, second = tickets[0]["ticket_id"], tickets[1]["ticket_id"]

    # Mutate the second ticket directly in the store, then comment on the first
    # via the API. The direct mutation must survive.
    stored = document_store.get_ticket(second)
    stored.assignee = "Out-of-band Editor"
    document_store.upsert_ticket(stored)

    commented = client.post(f"/api/tickets/{first}/comments", json={"text": "hello"})
    assert commented.status_code == 200

    assert document_store.get_ticket(second).assignee == "Out-of-band Editor"
