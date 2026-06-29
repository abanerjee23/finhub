from __future__ import annotations

from cfin_agents.batch import StagedDocumentRepository, bootstrap_demo, load_tickets
from cfin_agents.models import ActionType, ReasonCode
from cfin_agents.services import ApprovalStore, DeterministicWorkflow
from cfin_agents.synthetic_generator import generate_staged_failures
from cfin_agents.ticket_models import OwnerRole
from cfin_agents.ticket_narratives import enrich_ticket
from cfin_agents.ticketing import create_ticket, dashboard_summary, role_routing_for_reason


def test_role_routing_matches_finance_ownership_model() -> None:
    assert role_routing_for_reason(ReasonCode.MD_COST_CENTER_MASTER_DATA_MISSING) == (
        OwnerRole.MANAGEMENT_ACCOUNTING_PROCESS_OWNER,
        [OwnerRole.MASTER_DATA_GOVERNANCE_LEAD],
        OwnerRole.MASTER_DATA_GOVERNANCE_LEAD,
    )
    assert role_routing_for_reason(ReasonCode.MD_PROFIT_CENTER_MASTER_DATA_MISSING) == (
        OwnerRole.MANAGEMENT_ACCOUNTING_PROCESS_OWNER,
        [OwnerRole.MASTER_DATA_GOVERNANCE_LEAD],
        OwnerRole.MASTER_DATA_GOVERNANCE_LEAD,
    )
    assert role_routing_for_reason(ReasonCode.MD_VENDOR_MASTER_DATA_MISSING) == (
        OwnerRole.ACCOUNTS_PAYABLE_LEAD,
        [OwnerRole.PROCURE_TO_PAY_PROCESS_OWNER, OwnerRole.MASTER_DATA_GOVERNANCE_LEAD],
        OwnerRole.MASTER_DATA_GOVERNANCE_LEAD,
    )
    assert role_routing_for_reason(ReasonCode.DC_POSTING_PERIOD_CLOSED) == (
        OwnerRole.FINANCE_CONTROLLER,
        [OwnerRole.GENERAL_LEDGER_ACCOUNTING_MANAGER],
        OwnerRole.FINANCE_CONTROLLER,
    )


def test_generated_records_can_be_diagnosed_and_ticketed() -> None:
    records = generate_staged_failures(count=12, seed=7)
    repository = StagedDocumentRepository(records)
    workflow = DeterministicWorkflow(repository=repository, approval_store=ApprovalStore())

    tickets = [
        create_ticket(
            record,
            workflow.run(record.document.document_id, execution_mode="test_batch"),
        )
        for record in records
    ]
    summary = dashboard_summary(tickets)

    assert len(tickets) == 12
    assert summary.total_tickets == 12
    assert summary.tickets_by_owner_role
    assert all(ticket.timeline for ticket in tickets)


def test_ticket_narratives_use_plain_english(monkeypatch) -> None:
    monkeypatch.setenv("SUMMARY_USE_LLM", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    records = generate_staged_failures(count=12, seed=7)
    repository = StagedDocumentRepository(records)
    workflow = DeterministicWorkflow(repository=repository, approval_store=ApprovalStore())

    tickets = [
        create_ticket(
            record,
            workflow.run(record.document.document_id, execution_mode="test_batch"),
        )
        for record in records
    ]

    mapping_ticket = next(
        ticket
        for ticket in tickets
        if ticket.workflow_run.remediation_plan.action == ActionType.MAINTAIN_SOURCE_MAPPING
    )
    master_data_ticket = next(
        ticket
        for ticket in tickets
        if ticket.workflow_run.remediation_plan.action == ActionType.CREATE_TARGET_MASTER_DATA
    )

    assert "Document posting failed because" in mapping_ticket.agent_summary
    assert mapping_ticket.title.endswith("Missing-GL-account-mapping")
    assert mapping_ticket.title.startswith(mapping_ticket.created_at.strftime("%d%m%y"))
    assert "No approval is required" in mapping_ticket.agent_summary
    assert "approval before target master data can be created" in master_data_ticket.agent_summary
    assert "mapping maintenance require" not in master_data_ticket.policy_summary.lower()
    assert all(event.summary for event in mapping_ticket.timeline)

    enriched = enrich_ticket(master_data_ticket)
    assert enriched.agent_summary == master_data_ticket.agent_summary


def test_bootstrap_demo_does_not_reload_existing_tickets_when_resetting(
    tmp_path, monkeypatch
) -> None:
    from cfin_agents import document_store

    monkeypatch.setattr(document_store, "DB_PATH", tmp_path / "finhub.db")

    tickets = bootstrap_demo(count=8, seed=99)
    assert len(tickets) == 8


def test_ticket_comment_is_persisted(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from cfin_agents import document_store
    from cfin_agents.api import app

    monkeypatch.setattr(document_store, "DB_PATH", tmp_path / "finhub.db")

    bootstrap_demo(count=3, seed=11)
    ticket_id = load_tickets()[0].ticket_id
    client = TestClient(app)

    response = client.post(
        f"/api/tickets/{ticket_id}/comments",
        json={"text": "Waiting on MDG approval.", "author": "Priya Shah"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["text"] == "Waiting on MDG approval."

    reloaded = client.get(f"/api/tickets/{ticket_id}")
    assert reloaded.json()["comments"][0]["author"] == "Priya Shah"


def test_ticket_description_can_be_edited(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from cfin_agents import document_store
    from cfin_agents.api import app

    monkeypatch.setattr(document_store, "DB_PATH", tmp_path / "finhub.db")

    bootstrap_demo(count=3, seed=11)
    ticket_id = load_tickets()[0].ticket_id
    client = TestClient(app)
    custom = "280626-ERP-NA-Custom-vendor-master-data-issue"

    response = client.patch(
        f"/api/tickets/{ticket_id}/description",
        json={"description": custom},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == custom
    assert payload["title_edited"] is True

    reloaded = client.get(f"/api/tickets/{ticket_id}")
    assert reloaded.json()["title"] == custom

    listed = client.get("/api/tickets")
    match = next(row for row in listed.json() if row["ticket_id"] == ticket_id)
    assert match["description"] == custom


def test_ticket_status_can_be_updated(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from cfin_agents import document_store
    from cfin_agents.api import app

    monkeypatch.setattr(document_store, "DB_PATH", tmp_path / "finhub.db")

    bootstrap_demo(count=3, seed=11)
    ticket_id = load_tickets()[0].ticket_id
    client = TestClient(app)

    response = client.post(
        f"/api/tickets/{ticket_id}/transition",
        json={"status": "in_progress", "actor": "Priya Shah"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operator_status"] == "in_progress"
    assert payload["timeline"][-1]["action"] == "manual_transition"

    blocked = client.post(
        f"/api/tickets/{ticket_id}/transition",
        json={"status": "blocked", "actor": "Priya Shah"},
    )
    assert blocked.status_code == 400

    blocked_with_note = client.post(
        f"/api/tickets/{ticket_id}/transition",
        json={
            "status": "blocked",
            "actor": "Priya Shah",
            "note": "Waiting on MDG to create vendor master.",
        },
    )
    assert blocked_with_note.status_code == 200
    payload = blocked_with_note.json()
    assert payload["operator_status"] == "blocked"
    assert payload["comments"][-1]["text"] == "Blocked: Waiting on MDG to create vendor master."
    assert payload["timeline"][-1]["details"]["note"] == "Waiting on MDG to create vendor master."


def test_resolved_status_requires_proof_attachment(tmp_path, monkeypatch) -> None:
    from io import BytesIO

    from fastapi.testclient import TestClient

    from cfin_agents import document_store
    from cfin_agents.api import app

    monkeypatch.setattr(document_store, "DB_PATH", tmp_path / "finhub.db")

    bootstrap_demo(count=3, seed=11)
    ticket_id = load_tickets()[0].ticket_id
    client = TestClient(app)

    rejected = client.post(
        f"/api/tickets/{ticket_id}/transition",
        json={"status": "resolved", "actor": "Priya Shah"},
    )
    assert rejected.status_code == 400

    upload = client.post(
        f"/api/tickets/{ticket_id}/attachments",
        files={"file": ("proof.png", BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
    )
    assert upload.status_code == 200
    attachment_id = upload.json()["attachments"][-1]["attachment_id"]

    resolved = client.post(
        f"/api/tickets/{ticket_id}/transition",
        json={
            "status": "resolved",
            "actor": "Priya Shah",
            "attachment_ids": [attachment_id],
            "note": "Confirmed in CFIN monitor.",
        },
    )
    assert resolved.status_code == 200
    payload = resolved.json()
    assert payload["operator_status"] == "resolved"
    assert payload["attachments"][-1]["attachment_id"] == attachment_id
    assert "reprocessing proof attached" in payload["comments"][-1]["text"]
    assert payload["timeline"][-1]["details"]["attachment_ids"] == [attachment_id]

    download = client.get(f"/api/tickets/{ticket_id}/attachments/{attachment_id}")
    assert download.status_code == 200
    assert download.content.startswith(b"\x89PNG")
