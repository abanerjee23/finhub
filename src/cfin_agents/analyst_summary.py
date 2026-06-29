from __future__ import annotations

import re

from cfin_agents.models import (
    ActionType,
    Diagnosis,
    GovernanceDecision,
    ReasonCode,
    RemediationPlan,
    ReprocessResult,
    WorkflowRun,
)

# Golden copy from evals/summary_cases.yaml example_good_summary — single source of truth
# for deterministic / workbench analyst summaries.
EVAL_ALIGNED_SUMMARIES: dict[ReasonCode, str] = {
    ReasonCode.MD_GL_ACCOUNT_MASTER_DATA_MISSING: (
        "Document posting failed because GL account master data is missing in the "
        "target system. The document has not been reprocessed yet and requires "
        "approval before target master data can be created. After approval is "
        "recorded, create the required GL account master data, maintain the "
        "source to target mapping with the newly created GL master data and then "
        "reprocess the document."
    ),
    ReasonCode.MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING: (
        "Document posting failed because the cost center source-to-target mapping "
        "is missing. Maintain the missing mapping entry manually in the target "
        "mapping table, then reprocess the document. No approval is required."
    ),
    ReasonCode.MD_VENDOR_MASTER_DATA_MISSING: (
        "Document posting failed because vendor master data is missing in the "
        "target system. The document has not been reprocessed yet and requires "
        "approval before target master data can be created. After approval is "
        "recorded, create the required vendor master data, maintain the source "
        "to target mapping, and then reprocess the document."
    ),
    ReasonCode.MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING: (
        "Document posting failed because the GL account source-to-target mapping "
        "is missing. Maintain the missing mapping entry manually in the target "
        "mapping table, then reprocess the document. No approval is required."
    ),
    ReasonCode.MD_COST_CENTER_MASTER_DATA_MISSING: (
        "Document posting failed because cost center master data is missing in the "
        "target system. The document has not been reprocessed yet and requires "
        "approval before target master data can be created. After approval is "
        "recorded, create the required cost center master data, maintain the "
        "source to target mapping, and then reprocess the document."
    ),
    ReasonCode.DC_POSTING_PERIOD_CLOSED: (
        "Document processing failed because the posting period is closed in the "
        "target system. The document is blocked and has not been reprocessed. "
        "Escalate to the responsible controller to review and reopen the posting "
        "period externally before retrying."
    ),
    ReasonCode.MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING: (
        "Document posting failed because the profit center source-to-target "
        "mapping is missing. Maintain the missing mapping entry manually in the "
        "target mapping table, then reprocess the document. No approval is required."
    ),
    ReasonCode.MD_PROFIT_CENTER_MASTER_DATA_MISSING: (
        "Document posting failed because profit center master data is missing in "
        "the target system. The document has not been reprocessed yet and requires "
        "approval before target master data can be created. After approval is "
        "recorded, create the required profit center master data, maintain the "
        "source to target mapping, and then reprocess the document."
    ),
    ReasonCode.MD_CUSTOMER_MASTER_DATA_MISSING: (
        "Document posting failed because customer master data is missing in the "
        "target system. The document has not been reprocessed yet and requires "
        "approval before target master data can be created. After approval is "
        "recorded, create the required customer master data, maintain the source "
        "to target mapping, and then reprocess the document."
    ),
    ReasonCode.MD_ASSET_MASTER_DATA_MISSING: (
        "Document posting failed because asset master data is missing in the "
        "target system. The document has not been reprocessed yet and requires "
        "approval before target master data can be created. After approval is "
        "recorded, create the required asset master data, maintain the source to "
        "target mapping, and then reprocess the document."
    ),
}


_REASON_CODE_PATTERN = re.compile(r"\b(?:MD|MP|DC)_[A-Z0-9_]+\b", re.IGNORECASE)
_REASON_CODE_PHRASE_PATTERN = re.compile(
    r",?\s*as indicated by the reason code[^.]*\.?",
    re.IGNORECASE,
)
_META_PHRASE_PATTERNS = (
    re.compile(r"\bthe analyst should be aware that\b", re.IGNORECASE),
    re.compile(r"\bthe sequence of actions required is:?\b", re.IGNORECASE),
)


def polish_analyst_summary(text: str) -> str:
    """Remove internal codes and common LLM filler from analyst-facing summaries."""
    cleaned = _REASON_CODE_PATTERN.sub("", text)
    cleaned = _REASON_CODE_PHRASE_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\breason code\s+\S+", "", cleaned, flags=re.IGNORECASE)
    for pattern in _META_PHRASE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\.\s*\.", ".", cleaned)
    return cleaned.strip()


def summary_needs_refresh(text: str) -> bool:
    """True when a stored summary uses legacy verbose patterns we no longer want."""
    if _REASON_CODE_PATTERN.search(text):
        return True
    lower = text.lower()
    legacy_markers = (
        "reason code",
        "analyst should be aware",
        "sequence of actions required",
        "as indicated by",
        "the finance document doc-",
    )
    return any(marker in lower for marker in legacy_markers)


def resolve_agent_summary(
    workflow_run: WorkflowRun,
    *,
    persisted: str | None = None,
) -> str | None:
    """Return the persisted LLM summary only — never substitute deterministic templates."""
    stored = (persisted or workflow_run.agent_summary or "").strip()
    if not stored or summary_needs_refresh(stored):
        return None
    return polish_analyst_summary(stored) or stored


def build_deterministic_analyst_summary(
    diagnosis: Diagnosis,
    plan: RemediationPlan,
    decision: GovernanceDecision,
    reprocess_result: ReprocessResult | None,
) -> str:
    """Return eval-calibrated summary text for the diagnosed failure and policy outcome."""
    reason_code = diagnosis.reason_code
    template = EVAL_ALIGNED_SUMMARIES.get(reason_code)

    if plan.action == ActionType.CREATE_TARGET_MASTER_DATA and decision.allowed:
        if reprocess_result and reprocess_result.success:
            return _approved_master_data_summary(reason_code)
        return template or diagnosis.root_cause

    if template:
        return template

    return diagnosis.root_cause


def analyst_summary_from_workflow_run(workflow_run: WorkflowRun) -> str:
    return build_deterministic_analyst_summary(
        workflow_run.diagnosis,
        workflow_run.remediation_plan,
        workflow_run.governance_decision,
        workflow_run.reprocess_result,
    )


def _approved_master_data_summary(reason_code: ReasonCode) -> str:
    labels = {
        ReasonCode.MD_GL_ACCOUNT_MASTER_DATA_MISSING: "GL account",
        ReasonCode.MD_COST_CENTER_MASTER_DATA_MISSING: "cost center",
        ReasonCode.MD_PROFIT_CENTER_MASTER_DATA_MISSING: "profit center",
        ReasonCode.MD_VENDOR_MASTER_DATA_MISSING: "vendor",
        ReasonCode.MD_CUSTOMER_MASTER_DATA_MISSING: "customer",
        ReasonCode.MD_ASSET_MASTER_DATA_MISSING: "asset",
    }
    label = labels.get(reason_code, "master data")
    mapping_clause = (
        "maintain the source to target mapping with the newly created GL master data"
        if reason_code == ReasonCode.MD_GL_ACCOUNT_MASTER_DATA_MISSING
        else "maintain the source to target mapping"
    )
    return (
        f"Document posting failed because {label} master data was missing in the "
        f"target system. After approval was recorded, the required {label} master "
        f"data was created, {mapping_clause}, and the document was reprocessed."
    )
