from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from cfin_agents.timeutil import UTCDateTime, utc_now


class FailureScenario(StrEnum):
    # Source-to-target mapping is missing, but the target master data exists.
    GL_SOURCE_MAPPING_MISSING = "gl_source_mapping_missing"
    COST_CENTER_SOURCE_MAPPING_MISSING = "cost_center_source_mapping_missing"
    PROFIT_CENTER_SOURCE_MAPPING_MISSING = "profit_center_source_mapping_missing"
    # Target master data is missing and must be created with approval.
    MISSING_GL_ACCOUNT_MASTER = "missing_gl_account_master"
    MISSING_COST_CENTER_MASTER = "missing_cost_center_master"
    MISSING_PROFIT_CENTER_MASTER = "missing_profit_center_master"
    MISSING_VENDOR = "missing_vendor"
    MISSING_CUSTOMER = "missing_customer"
    MISSING_ASSET_MASTER = "missing_asset_master"
    # Period closed — external approval required
    CLOSED_POSTING_PERIOD = "closed_posting_period"


class ReasonCode(StrEnum):
    # MP — source-to-target mapping missing (target value exists)
    MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING = (  # noqa: E501
        "MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING"
    )
    MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING = (  # noqa: E501
        "MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING"
    )
    MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING = (  # noqa: E501
        "MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING"
    )
    # MD — master data missing in target system
    MD_GL_ACCOUNT_MASTER_DATA_MISSING = "MD_GL_ACCOUNT_MASTER_DATA_MISSING"
    MD_COST_CENTER_MASTER_DATA_MISSING = "MD_COST_CENTER_MASTER_DATA_MISSING"
    MD_PROFIT_CENTER_MASTER_DATA_MISSING = "MD_PROFIT_CENTER_MASTER_DATA_MISSING"
    MD_VENDOR_MASTER_DATA_MISSING = "MD_VENDOR_MASTER_DATA_MISSING"
    MD_CUSTOMER_MASTER_DATA_MISSING = "MD_CUSTOMER_MASTER_DATA_MISSING"
    MD_ASSET_MASTER_DATA_MISSING = "MD_ASSET_MASTER_DATA_MISSING"
    # DC — document/journal posting issue
    DC_POSTING_PERIOD_CLOSED = "DC_POSTING_PERIOD_CLOSED"


class WorkflowStatus(StrEnum):
    NEW = "new"
    DIAGNOSED = "diagnosed"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"
    REPROCESSED = "reprocessed"
    # Workbench-only staged states for the human-in-the-loop pipeline. These are
    # never produced by DeterministicWorkflow.run() (which always resolves a
    # scenario to a final status in one deterministic pass) — they exist purely
    # as ticket-presentation states, assigned and advanced by the API layer to
    # simulate the real-world lag between approval/mapping and reprocessing.
    NEEDS_MAPPING = "needs_mapping"
    APPROVED = "approved"
    MAPPING_MAINTAINED = "mapping_maintained"
    READY_FOR_REPROCESSING = "ready_for_reprocessing"


class ActionType(StrEnum):
    MAINTAIN_SOURCE_MAPPING = "maintain_source_mapping"
    CREATE_TARGET_MASTER_DATA = "create_target_master_data"
    EXTERNAL_CONTROLLER_ACTION_REQUIRED = "external_controller_action_required"
    NO_ACTION = "no_action"


class FinancialDocument(BaseModel):
    document_id: str
    source_system: str
    source_document_ref: str
    company_code: str
    gl_account: str
    profit_center: str
    cost_center: str | None = None
    business_partner: str | None = None
    tax_code: str
    amount: float
    currency: str
    posting_date: str
    failure_scenario: FailureScenario
    error_message: str


class MappingEntry(BaseModel):
    mapping_type: str
    source_value: str
    target_value: str
    status: str = "active"
    confidence: float = Field(default=1.0, ge=0, le=1)


class TargetMasterData(BaseModel):
    gl_accounts: list[str]
    profit_centers: list[str]
    cost_centers: list[str]
    business_partners: list[str]
    open_periods: list[str]
    posted_source_refs: list[str]


class ValidationIssue(BaseModel):
    code: str
    message: str
    field: str | None = None
    severity: str = "error"


class Diagnosis(BaseModel):
    document_id: str
    failure_scenario: FailureScenario
    reason_code: ReasonCode
    root_cause: str
    evidence: list[str]
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)


class RemediationPlan(BaseModel):
    document_id: str
    action: ActionType
    requires_approval: bool
    proposed_changes: dict[str, Any] = Field(default_factory=dict)
    reprocess_after: bool
    rationale: str


class GovernanceDecision(BaseModel):
    document_id: str
    status: WorkflowStatus
    allowed: bool
    requires_approval: bool
    policy_reasons: list[str]
    audit_reason: str


class AuditEvent(BaseModel):
    timestamp: UTCDateTime = Field(default_factory=utc_now)
    actor: str
    action: str
    details: dict[str, Any] = Field(default_factory=dict)


class ReprocessResult(BaseModel):
    document_id: str
    success: bool
    message: str
    target_document_id: str | None = None


class WorkflowRun(BaseModel):
    document_id: str
    execution_mode: str
    status: WorkflowStatus
    diagnosis: Diagnosis
    remediation_plan: RemediationPlan
    governance_decision: GovernanceDecision
    reprocess_result: ReprocessResult | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)
    agent_summary: str | None = None
    langfuse_trace_id: str | None = None
    # Shadow-mode output from the LLM manager agent (informational only; the
    # deterministic controller remains authoritative for all state).
    agent_final_output: str | None = None
    shadow_agreement: bool | None = None

    def promptfoo_summary(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "failure_scenario": self.diagnosis.failure_scenario,
            "reason_code": self.diagnosis.reason_code,
            "action": self.remediation_plan.action,
            "requires_approval": self.governance_decision.requires_approval,
            "allowed": self.governance_decision.allowed,
            "reprocessed": bool(self.reprocess_result and self.reprocess_result.success),
            "policy_reasons": self.governance_decision.policy_reasons,
            "audit_reason": self.governance_decision.audit_reason,
            "agent_summary": self.agent_summary,
        }
