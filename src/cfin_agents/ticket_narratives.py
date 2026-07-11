from __future__ import annotations

from cfin_agents.analyst_summary import resolve_agent_summary
from cfin_agents.models import ActionType, ReasonCode, WorkflowRun, WorkflowStatus
from cfin_agents.ticket_models import StagedFailureRecord, Ticket, TicketEvent

REASON_CODE_DESCRIPTIONS: dict[ReasonCode, str] = {
    ReasonCode.MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING: (
        "GL account source-to-target mapping is missing"
    ),
    ReasonCode.MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING: (
        "Cost center source-to-target mapping is missing"
    ),
    ReasonCode.MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING: (
        "Profit center source-to-target mapping is missing"
    ),
    ReasonCode.MD_GL_ACCOUNT_MASTER_DATA_MISSING: (
        "GL account master data is missing in the target system"
    ),
    ReasonCode.MD_COST_CENTER_MASTER_DATA_MISSING: (
        "Cost center master data is missing in the target system"
    ),
    ReasonCode.MD_PROFIT_CENTER_MASTER_DATA_MISSING: (
        "Profit center master data is missing in the target system"
    ),
    ReasonCode.MD_VENDOR_MASTER_DATA_MISSING: (
        "Vendor master data is missing in the target system"
    ),
    ReasonCode.MD_CUSTOMER_MASTER_DATA_MISSING: (
        "Customer master data is missing in the target system"
    ),
    ReasonCode.MD_ASSET_MASTER_DATA_MISSING: (
        "Asset master data is missing in the target system"
    ),
    ReasonCode.DC_POSTING_PERIOD_CLOSED: (
        "Target posting period is closed for this document"
    ),
}

TICKET_TITLES: dict[ReasonCode, str] = {
    ReasonCode.MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING: "Missing GL account mapping",
    ReasonCode.MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING: "Missing cost center mapping",
    ReasonCode.MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING: "Missing profit center mapping",
    ReasonCode.MD_GL_ACCOUNT_MASTER_DATA_MISSING: "Missing GL account master data",
    ReasonCode.MD_COST_CENTER_MASTER_DATA_MISSING: "Missing cost center master data",
    ReasonCode.MD_PROFIT_CENTER_MASTER_DATA_MISSING: "Missing profit center master data",
    ReasonCode.MD_VENDOR_MASTER_DATA_MISSING: "Missing vendor master data",
    ReasonCode.MD_CUSTOMER_MASTER_DATA_MISSING: "Missing customer master data",
    ReasonCode.MD_ASSET_MASTER_DATA_MISSING: "Missing asset master data",
    ReasonCode.DC_POSTING_PERIOD_CLOSED: "Closed posting period",
}


def describe_reason_code(reason_code: ReasonCode | str) -> str:
    code = ReasonCode(reason_code) if isinstance(reason_code, str) else reason_code
    return REASON_CODE_DESCRIPTIONS.get(code, str(reason_code).replace("_", " ").lower())


def format_ticket_title(workflow_run: WorkflowRun) -> str:
    code = workflow_run.diagnosis.reason_code
    return TICKET_TITLES.get(code, describe_reason_code(code).capitalize())


def format_ticket_description(
    *,
    created_at,
    source_system: str,
    workflow_run: WorkflowRun,
) -> str:
    date_part = created_at.strftime("%d%m%y")
    brief = format_ticket_title(workflow_run).replace(" ", "-")
    return f"{date_part}-{source_system}-{brief}"


def ticket_title(ticket: Ticket) -> str:
    if ticket.title_edited and ticket.title.strip():
        return ticket.title.strip()
    return format_ticket_description(
        created_at=ticket.created_at,
        source_system=ticket.source_system,
        workflow_run=ticket.workflow_run,
    )


def format_policy_summary(workflow_run: WorkflowRun) -> str:
    plan = workflow_run.remediation_plan
    decision = workflow_run.governance_decision

    if plan.action == ActionType.MAINTAIN_SOURCE_MAPPING:
        return (
            "Allowed without approval. The analyst can maintain the missing "
            "source-to-target mapping and reprocess the document."
        )

    if plan.action == ActionType.CREATE_TARGET_MASTER_DATA:
        if not decision.allowed:
            return (
                "Waiting for approval. Creating target master data requires sign-off "
                "before reprocessing. Mapping maintenance is a separate manual step "
                "and does not require its own approval."
            )
        if workflow_run.reprocess_result and workflow_run.reprocess_result.success:
            return (
                "Approved and completed. Master data creation was approved and the "
                "document was successfully reprocessed."
            )
        return (
            "Approved. Master data creation is permitted after recorded approval; "
            "mapping maintenance remains a manual follow-up step."
        )

    if plan.action == ActionType.EXTERNAL_CONTROLLER_ACTION_REQUIRED:
        return (
            "Blocked. The posting period is closed and must be reopened by the "
            "Finance Controller before this document can be posted."
        )

    if decision.allowed:
        return "Allowed. Policy checks passed and the planned action can proceed."
    return f"Blocked. {' '.join(decision.policy_reasons)}"


def format_timeline_summary(event: TicketEvent, workflow_run: WorkflowRun | None = None) -> str:
    if event.summary and not _is_legacy_timeline_summary(event.summary):
        return event.summary

    if event.action == "failed_document_loaded":
        return "Failed document ingested from the staging queue."

    if event.action == "diagnosis_completed" and workflow_run:
        failure = describe_reason_code(workflow_run.diagnosis.reason_code)
        return f"Root cause identified: {failure}."

    if event.action == "ticket_assigned":
        assignee = event.details.get("assignee", "the assigned analyst")
        return f"Ticket assigned to {assignee}."

    if event.action == "work_started":
        if workflow_run and workflow_run.status == WorkflowStatus.NEEDS_APPROVAL:
            return "Remediation underway — awaiting master data approval."
        if workflow_run and workflow_run.status == WorkflowStatus.BLOCKED:
            return "Blocked — waiting on external controller action."
        return "Owner started remediation work."

    if event.action == "reprocess_completed":
        if workflow_run and workflow_run.reprocess_result and workflow_run.reprocess_result.success:
            return (
                "Document reprocessed successfully. "
                "Ready for the ticket owner to review and resolve."
            )
        return "Document reprocessing completed."

    if event.action == "master_data_created":
        return "Missing master data created in the target system."

    if event.action == "document_reprocessed":
        if workflow_run and workflow_run.reprocess_result and workflow_run.reprocess_result.success:
            target_id = workflow_run.reprocess_result.target_document_id
            if target_id:
                return f"Document reprocessed successfully as {target_id}."
            return "Document reprocessed successfully."
        return "Document reprocessed."

    if event.to_status:
        stage = event.to_status.replace("_", " ")
        return f"Moved to {stage}."
    return event.action.replace("_", " ").capitalize()


def _is_legacy_timeline_summary(summary: str) -> bool:
    legacy_markers = (
        "The failed document was ingested from",
        "The diagnosis agent identified",
        "Ticket routed to",
        "The assigned owner started",
        "Document was successfully reprocessed into Central Finance",
    )
    return any(summary.startswith(marker) for marker in legacy_markers)


def enrich_ticket(ticket: Ticket) -> Ticket:
    workflow_run = ticket.workflow_run
    reason_description = ticket.reason_description or describe_reason_code(ticket.reason_code)
    policy_summary = format_policy_summary(workflow_run)
    agent_summary = resolve_agent_summary(workflow_run, persisted=ticket.agent_summary)

    timeline = [
        event.model_copy(
            update={
                "summary": format_timeline_summary(event, workflow_run=workflow_run),
            }
        )
        for event in ticket.timeline
    ]

    return ticket.model_copy(
        update={
            "title": ticket.title if ticket.title_edited else ticket_title(ticket),
            "reason_description": reason_description,
            "policy_summary": policy_summary,
            "agent_summary": agent_summary,
            "timeline": timeline,
        }
    )


def build_ticket_narratives(
    record: StagedFailureRecord,
    workflow_run: WorkflowRun,
    timeline: list[TicketEvent],
) -> dict[str, object]:
    return {
        "reason_description": describe_reason_code(workflow_run.diagnosis.reason_code),
        "policy_summary": format_policy_summary(workflow_run),
        "agent_summary": resolve_agent_summary(workflow_run),
        "timeline": [
            event.model_copy(
                update={
                    "summary": format_timeline_summary(event, workflow_run=workflow_run),
                }
            )
            for event in timeline
        ],
    }
