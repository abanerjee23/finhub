from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, computed_field

from cfin_agents.models import FinancialDocument, WorkflowRun
from cfin_agents.timeutil import UTCDateTime


class StagingRecordStatus(StrEnum):
    NEW = "new"
    DIAGNOSED = "diagnosed"
    TICKETED = "ticketed"
    ERROR = "error"


class TicketStatus(StrEnum):
    """Internal journey stages for timeline events — not the operator-facing status."""

    RECEIVED = "received"
    DIAGNOSED = "diagnosed"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    RESOLVED = "resolved"


class OperatorStatus(StrEnum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    RESOLVED = "resolved"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OwnerRole(StrEnum):
    GENERAL_LEDGER_ACCOUNTING_MANAGER = "General Ledger Accounting Manager"
    PROCURE_TO_PAY_PROCESS_OWNER = "Procure to Pay Process Owner"
    ORDER_TO_CASH_PROCESS_OWNER = "Order to Cash Process Owner"
    ACCOUNTS_PAYABLE_LEAD = "Accounts Payable Lead"
    ACCOUNTS_RECEIVABLES_LEAD = "Accounts Receivables Lead"
    MASTER_DATA_GOVERNANCE_LEAD = "Master Data Governance Lead"
    FINANCE_CONTROLLER = "Finance Controller"
    CONSOLIDATION_LEAD = "Consolidation Lead"
    MANAGEMENT_ACCOUNTING_PROCESS_OWNER = "Management Accounting Process Owner"
    ASSET_ACCOUNTING_PROCESS_OWNER = "Asset Accounting Process Owner"


class ErrorLog(BaseModel):
    error_log_id: str
    document_id: str
    source_system: str
    error_code: str
    error_text: str
    created_at: UTCDateTime
    component: str = "SAP CFIN AIF"


class StagedFailureRecord(BaseModel):
    case_id: str
    document: FinancialDocument
    error_logs: list[ErrorLog]
    status: StagingRecordStatus = StagingRecordStatus.NEW
    created_at: UTCDateTime
    updated_at: UTCDateTime
    source_queue: str = "synthetic_cfin_aif_staging"


class TicketEvent(BaseModel):
    timestamp: UTCDateTime
    actor: str
    action: str
    from_status: TicketStatus | None = None
    to_status: TicketStatus | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


class TicketComment(BaseModel):
    comment_id: str
    author: str
    text: str
    created_at: UTCDateTime


class TicketAttachment(BaseModel):
    attachment_id: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: UTCDateTime
    uploaded_by: str
    purpose: str = "resolution_proof"


class SummaryFeedback(BaseModel):
    rating: str  # "up" | "down"
    actor: str
    note: str = ""
    created_at: UTCDateTime


class Ticket(BaseModel):
    ticket_id: str
    case_id: str
    document_id: str
    source_system: str
    source_document_ref: str
    company_code: str
    amount: float
    currency: str
    priority: TicketPriority
    operator_status: OperatorStatus
    reason_code: str
    reason_description: str = ""
    error_type: str
    policy_summary: str
    title: str = ""
    title_edited: bool = False
    agent_summary: str | None = None
    owner_role: OwnerRole
    tagged_roles: list[OwnerRole]
    policy_owner: OwnerRole
    assignee: str
    current_stage_started_at: UTCDateTime
    created_at: UTCDateTime
    updated_at: UTCDateTime
    sla_due_at: UTCDateTime
    stage_durations_days: dict[str, float]
    workflow_run: WorkflowRun
    timeline: list[TicketEvent] = Field(default_factory=list)
    comments: list[TicketComment] = Field(default_factory=list)
    attachments: list[TicketAttachment] = Field(default_factory=list)
    summary_feedback: SummaryFeedback | None = None

    @computed_field
    @property
    def days_open(self) -> float:
        return round((self.updated_at - self.created_at).total_seconds() / 86400, 1)


class AgingBucket(BaseModel):
    count: int = 0
    value_usd: float = 0.0


class TicketDashboardSummary(BaseModel):
    total_tickets: int
    open_tickets: int
    closed_tickets: int
    average_resolution_days: float
    slowest_stage: str | None
    tickets_by_operator_status: dict[str, int]
    tickets_by_owner_role: dict[str, int]
    tickets_by_reason_code: dict[str, int]
    workflow_status_counts: dict[str, int]
    average_stage_days: dict[str, float]
    # Business-value metrics. USD figures use fixed demo FX rates (fx_rates_to_usd)
    # so mixed-currency documents can be aggregated; raw sums stay in value_by_currency.
    total_value_usd: float = 0.0
    open_value_usd: float = 0.0
    open_value_by_company_code: dict[str, float] = Field(default_factory=dict)
    open_value_by_source_system: dict[str, float] = Field(default_factory=dict)
    value_by_currency: dict[str, float] = Field(default_factory=dict)
    sla_breached_count: int = 0
    sla_breached_value_usd: float = 0.0
    aging_buckets: dict[str, AgingBucket] = Field(default_factory=dict)
    automation_rate: float = 0.0
    fx_rates_to_usd: dict[str, float] = Field(default_factory=dict)
