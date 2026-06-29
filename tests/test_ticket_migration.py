from __future__ import annotations

from cfin_agents.ticket_migration import migrate_ticket_payload
from cfin_agents.ticket_models import OperatorStatus


def test_migrate_legacy_ticket_payload() -> None:
    raw = {
        "ticket_id": "FIN-1001",
        "case_id": "CASE-1001",
        "document_id": "DOC-1001",
        "source_system": "ECC_US",
        "source_document_ref": "REF-1",
        "company_code": "US01",
        "amount": 1000.0,
        "currency": "USD",
        "priority": "medium",
        "status": "diagnosed",
        "is_pending_approval": True,
        "is_blocked": False,
        "policy_status": "needs_approval",
        "reason_code": "MD_GL_ACCOUNT_MASTER_DATA_MISSING",
        "error_type": "missing_gl_account_master",
        "policy_summary": "Needs approval.",
        "owner_role": "General Ledger Accounting Manager",
        "tagged_roles": ["Master Data Governance Lead"],
        "policy_owner": "Master Data Governance Lead",
        "assignee": "Anika Mehta",
        "current_stage_started_at": "2026-01-01T00:00:00",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "sla_due_at": "2026-01-05T00:00:00",
        "stage_durations_days": {"received": 0.0},
        "workflow_run": {
            "document_id": "DOC-1001",
            "execution_mode": "deterministic",
            "status": "needs_approval",
            "diagnosis": {
                "reason_code": "MD_GL_ACCOUNT_MASTER_DATA_MISSING",
                "failure_scenario": "missing_gl_account_master",
                "root_cause": "Missing GL account master data",
                "evidence": [],
                "confidence": 1.0,
            },
            "remediation_plan": {
                "action": "create_target_master_data",
                "requires_approval": True,
                "rationale": "Create master data",
                "proposed_changes": {},
                "reprocess_after": True,
            },
            "governance_decision": {
                "allowed": False,
                "requires_approval": True,
                "policy_reasons": ["Approval required"],
                "audit_reason": "Needs approval",
            },
            "audit_events": [],
        },
        "timeline": [],
    }

    migrated = migrate_ticket_payload(raw)

    assert migrated["operator_status"] == OperatorStatus.ASSIGNED.value
    assert "status" not in migrated
    assert "policy_status" not in migrated
    assert "is_pending_approval" not in migrated
    assert "is_blocked" not in migrated
