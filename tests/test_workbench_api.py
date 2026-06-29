from __future__ import annotations


def test_workbench_reset_and_sweep(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from cfin_agents import document_store
    from cfin_agents.api import app

    monkeypatch.setattr(document_store, "DB_PATH", tmp_path / "finhub.db")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DISABLE_LLM", "1")
    monkeypatch.setenv("SUMMARY_USE_LLM", "0")

    client = TestClient(app)

    status = client.get("/api/workbench/status")
    assert status.status_code == 200
    assert status.json()["ticket_count"] == 0

    reset = client.post("/api/workbench/reset?count=5&seed=7")
    assert reset.status_code == 200
    payload = reset.json()
    assert payload["seeded_documents"] == 5
    assert payload["ticket_count"] == 0
    assert payload["staging_counts"]["new"] == 5

    sweep = client.post("/api/workbench/sweep", json={"batch_size": 2})
    assert sweep.status_code == 200
    sweep_payload = sweep.json()
    assert sweep_payload["processed"] == 2
    assert sweep_payload["created_tickets"] == 2
    assert sweep_payload["ticket_count"] == 2

    listed = client.get("/api/tickets")
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    assert listed.json()[0]["agent_summary"]
    assert listed.json()[0]["operator_status"] in {"assigned", "in_progress", "resolved", "blocked"}
