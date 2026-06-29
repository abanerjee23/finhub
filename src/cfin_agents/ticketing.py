from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from cfin_agents.models import ReasonCode
from cfin_agents.ticket_models import (
    OperatorStatus,
    OwnerRole,
    StagedFailureRecord,
    Ticket,
    TicketDashboardSummary,
    TicketEvent,
    TicketPriority,
    TicketStatus,
)
from cfin_agents.ticket_narratives import build_ticket_narratives, format_ticket_description

TICKET_STAGES: tuple[TicketStatus, ...] = (
    TicketStatus.RECEIVED,
    TicketStatus.DIAGNOSED,
    TicketStatus.ASSIGNED,
    TicketStatus.IN_PROGRESS,
    TicketStatus.RESOLVED,
)

ROLE_ASSIGNEES: dict[OwnerRole, str] = {
    OwnerRole.GENERAL_LEDGER_ACCOUNTING_MANAGER: "Anika Mehta",
    OwnerRole.PROCURE_TO_PAY_PROCESS_OWNER: "Ravi Narayan",
    OwnerRole.ORDER_TO_CASH_PROCESS_OWNER: "Sofia Mendes",
    OwnerRole.ACCOUNTS_PAYABLE_LEAD: "Priya Shah",
    OwnerRole.ACCOUNTS_RECEIVABLES_LEAD: "Daniel Weber",
    OwnerRole.MASTER_DATA_GOVERNANCE_LEAD: "Nisha Patel",
    OwnerRole.FINANCE_CONTROLLER: "Maria Chen",
    OwnerRole.CONSOLIDATION_LEAD: "Thomas Bauer",
    OwnerRole.MANAGEMENT_ACCOUNTING_PROCESS_OWNER: "Leah Okafor",
    OwnerRole.ASSET_ACCOUNTING_PROCESS_OWNER: "Arjun Rao",
}


def role_routing_for_reason(
    reason_code: ReasonCode,
) -> tuple[OwnerRole, list[OwnerRole], OwnerRole]:
    mdg = OwnerRole.MASTER_DATA_GOVERNANCE_LEAD
    gl = OwnerRole.GENERAL_LEDGER_ACCOUNTING_MANAGER
    ma = OwnerRole.MANAGEMENT_ACCOUNTING_PROCESS_OWNER
    fc = OwnerRole.FINANCE_CONTROLLER

    routing: dict[ReasonCode, tuple[OwnerRole, list[OwnerRole], OwnerRole]] = {
        ReasonCode.MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING: (gl, [mdg], gl),
        ReasonCode.MD_GL_ACCOUNT_MASTER_DATA_MISSING: (gl, [mdg], mdg),
        ReasonCode.MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING: (ma, [mdg], ma),
        ReasonCode.MD_COST_CENTER_MASTER_DATA_MISSING: (ma, [mdg], mdg),
        ReasonCode.MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING: (ma, [mdg], ma),
        ReasonCode.MD_PROFIT_CENTER_MASTER_DATA_MISSING: (ma, [mdg], mdg),
        ReasonCode.MD_VENDOR_MASTER_DATA_MISSING: (
            OwnerRole.ACCOUNTS_PAYABLE_LEAD,
            [OwnerRole.PROCURE_TO_PAY_PROCESS_OWNER, mdg],
            mdg,
        ),
        ReasonCode.MD_CUSTOMER_MASTER_DATA_MISSING: (
            OwnerRole.ACCOUNTS_RECEIVABLES_LEAD,
            [OwnerRole.ORDER_TO_CASH_PROCESS_OWNER, mdg],
            mdg,
        ),
        ReasonCode.MD_ASSET_MASTER_DATA_MISSING: (
            OwnerRole.ASSET_ACCOUNTING_PROCESS_OWNER,
            [mdg],
            mdg,
        ),
        ReasonCode.DC_POSTING_PERIOD_CLOSED: (fc, [gl], fc),
    }
    return routing[reason_code]


def create_ticket(record: StagedFailureRecord, workflow_run) -> Ticket:
    owner_role, tagged_roles, policy_owner = role_routing_for_reason(
        workflow_run.diagnosis.reason_code
    )
    now = datetime.utcnow()
    operator_status = OperatorStatus.ASSIGNED
    stage_durations = _fresh_stage_durations()
    timeline = _timeline_for_ticket(record, workflow_run, operator_status, now, owner_role)
    narratives = build_ticket_narratives(record, workflow_run, timeline)

    return Ticket(
        ticket_id=f"FIN-{record.case_id.split('-')[-1]}",
        case_id=record.case_id,
        document_id=record.document.document_id,
        source_system=record.document.source_system,
        source_document_ref=record.document.source_document_ref,
        company_code=record.document.company_code,
        amount=record.document.amount,
        currency=record.document.currency,
        priority=_priority_for_amount(record.document.amount),
        operator_status=operator_status,
        reason_code=str(workflow_run.diagnosis.reason_code),
        reason_description=str(narratives["reason_description"]),
        error_type=workflow_run.diagnosis.failure_scenario.value,
        policy_summary=str(narratives["policy_summary"]),
        title=format_ticket_description(
            created_at=now,
            source_system=record.document.source_system,
            workflow_run=workflow_run,
        ),
        agent_summary=narratives["agent_summary"],
        owner_role=owner_role,
        tagged_roles=tagged_roles,
        policy_owner=policy_owner,
        assignee=ROLE_ASSIGNEES[owner_role],
        current_stage_started_at=now,
        created_at=now,
        updated_at=now,
        sla_due_at=now + _sla_for_priority(_priority_for_amount(record.document.amount)),
        stage_durations_days=stage_durations,
        workflow_run=workflow_run,
        timeline=narratives["timeline"],  # type: ignore[arg-type]
    )


def dashboard_summary(tickets: list[Ticket]) -> TicketDashboardSummary:
    status_counts = Counter(ticket.operator_status.value for ticket in tickets)
    owner_counts = Counter(ticket.owner_role.value for ticket in tickets)
    reason_counts = Counter(ticket.reason_code for ticket in tickets)
    workflow_counts = Counter(ticket.workflow_run.status.value for ticket in tickets)
    stage_totals: dict[str, list[float]] = defaultdict(list)

    for ticket in tickets:
        for stage, days in ticket.stage_durations_days.items():
            if days:
                stage_totals[stage].append(days)

    average_stage_days = {
        stage: round(sum(values) / len(values), 1) for stage, values in stage_totals.items()
    }
    slowest_stage = (
        max(average_stage_days, key=average_stage_days.get) if average_stage_days else None
    )
    resolved = [ticket for ticket in tickets if ticket.operator_status == OperatorStatus.RESOLVED]
    avg_resolution = (
        sum((ticket.updated_at - ticket.created_at).total_seconds() / 86400 for ticket in resolved)
        / len(resolved)
        if resolved
        else 0.0
    )

    return TicketDashboardSummary(
        total_tickets=len(tickets),
        open_tickets=sum(
            1
            for ticket in tickets
            if ticket.operator_status != OperatorStatus.RESOLVED
        ),
        closed_tickets=len(resolved),
        average_resolution_days=round(avg_resolution, 1),
        slowest_stage=slowest_stage,
        tickets_by_operator_status=dict(status_counts),
        tickets_by_owner_role=dict(owner_counts),
        tickets_by_reason_code=dict(reason_counts),
        workflow_status_counts=dict(workflow_counts),
        average_stage_days=average_stage_days,
    )


def _priority_for_amount(amount: float) -> TicketPriority:
    if amount >= 20_000:
        return TicketPriority.CRITICAL
    if amount >= 12_000:
        return TicketPriority.HIGH
    if amount >= 7_500:
        return TicketPriority.MEDIUM
    return TicketPriority.LOW


def _sla_for_priority(priority: TicketPriority) -> timedelta:
    return {
        TicketPriority.CRITICAL: timedelta(days=1),
        TicketPriority.HIGH: timedelta(days=2),
        TicketPriority.MEDIUM: timedelta(days=4),
        TicketPriority.LOW: timedelta(days=7),
    }[priority]


def _fresh_stage_durations() -> dict[str, float]:
    return {stage.value: 0.0 for stage in TICKET_STAGES}


def _path_to_status(operator_status: OperatorStatus) -> list[TicketStatus]:
    if operator_status == OperatorStatus.RESOLVED:
        return [
            TicketStatus.RECEIVED,
            TicketStatus.DIAGNOSED,
            TicketStatus.ASSIGNED,
            TicketStatus.IN_PROGRESS,
            TicketStatus.RESOLVED,
        ]
    return [TicketStatus.RECEIVED, TicketStatus.DIAGNOSED, TicketStatus.ASSIGNED]


def _timeline_for_ticket(
    record: StagedFailureRecord,
    workflow_run,
    operator_status: OperatorStatus,
    ticket_created_at: datetime,
    owner_role: OwnerRole,
) -> list[TicketEvent]:
    events: list[TicketEvent] = [
        TicketEvent(
            timestamp=ticket_created_at,
            actor="staging_ingestion_job",
            action="failed_document_loaded",
            to_status=TicketStatus.RECEIVED,
            details={"source_queue": record.source_queue},
        )
    ]
    previous = TicketStatus.RECEIVED
    for offset_minutes, stage in enumerate(_path_to_status(operator_status)[1:], start=1):
        events.append(
            TicketEvent(
                timestamp=ticket_created_at + timedelta(minutes=offset_minutes),
                actor=_actor_for_stage(stage),
                action=_action_for_stage(stage),
                from_status=previous,
                to_status=stage,
                details=_details_for_stage(stage, workflow_run, owner_role),
            )
        )
        previous = stage
    return events


def _actor_for_stage(stage: TicketStatus) -> str:
    return {
        TicketStatus.DIAGNOSED: "diagnosis_agent",
        TicketStatus.ASSIGNED: "ticket_orchestrator",
        TicketStatus.IN_PROGRESS: "assigned_owner",
        TicketStatus.RESOLVED: "reprocessing_controller",
    }.get(stage, "system")


def _action_for_stage(stage: TicketStatus) -> str:
    return {
        TicketStatus.DIAGNOSED: "diagnosis_completed",
        TicketStatus.ASSIGNED: "ticket_assigned",
        TicketStatus.IN_PROGRESS: "work_started",
        TicketStatus.RESOLVED: "reprocess_completed",
    }.get(stage, "status_changed")


def _details_for_stage(stage: TicketStatus, workflow_run, owner_role: OwnerRole) -> dict[str, str]:
    if stage == TicketStatus.DIAGNOSED:
        return {"reason_code": str(workflow_run.diagnosis.reason_code)}
    if stage == TicketStatus.ASSIGNED:
        return {"owner_role": owner_role.value, "assignee": ROLE_ASSIGNEES[owner_role]}
    return {}
