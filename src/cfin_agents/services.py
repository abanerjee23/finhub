from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from cfin_agents.analyst_summary import (
    build_deterministic_analyst_summary,
    polish_analyst_summary,
)
from cfin_agents.models import (
    ActionType,
    AuditEvent,
    Diagnosis,
    FailureScenario,
    FinancialDocument,
    GovernanceDecision,
    ReasonCode,
    RemediationPlan,
    ReprocessResult,
    ValidationIssue,
    WorkflowRun,
    WorkflowStatus,
)
from cfin_agents.observability import summary_generation_observation
from cfin_agents.repository import SyntheticRepository

MASTER_DATA_OBJECT_LABELS: dict[FailureScenario, str] = {
    FailureScenario.MISSING_GL_ACCOUNT_MASTER: "GL account",
    FailureScenario.MISSING_COST_CENTER_MASTER: "cost center",
    FailureScenario.MISSING_PROFIT_CENTER_MASTER: "profit center",
    FailureScenario.MISSING_VENDOR: "vendor",
    FailureScenario.MISSING_CUSTOMER: "customer",
    FailureScenario.MISSING_ASSET_MASTER: "asset",
}


class AuditLog:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, actor: str, action: str, **details) -> None:
        self.events.append(AuditEvent(actor=actor, action=action, details=details))


@dataclass
class ApprovalStore:
    approvals: set[str] = field(default_factory=set)

    def approve(self, document_id: str) -> None:
        self.approvals.add(document_id)

    def is_approved(self, document_id: str) -> bool:
        return document_id in self.approvals


class Validator:
    def __init__(self, repository: SyntheticRepository) -> None:
        self.repository = repository

    def validate(self, document: FinancialDocument) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        target = self.repository.target_master_data()

        self._validate_single_mapping(issues, "gl_account", document.gl_account)
        self._validate_single_mapping(issues, "profit_center", document.profit_center)
        self._validate_single_mapping(issues, "cost_center", document.cost_center)
        self._validate_single_mapping(issues, "business_partner", document.business_partner)

        posting_period = document.posting_date[:7]
        if posting_period not in target.open_periods:
            issues.append(
                ValidationIssue(
                    code="POSTING_PERIOD_CLOSED",
                    field="posting_date",
                    message=f"Posting period {posting_period} is closed in the target.",
                )
            )

        return issues

    def _validate_single_mapping(
        self, issues: list[ValidationIssue], mapping_type: str, source_value: str | None
    ) -> None:
        mappings = self.repository.find_mappings(mapping_type, source_value)
        if not mappings:
            issues.append(
                ValidationIssue(
                    code=f"MISSING_{mapping_type.upper()}_MAPPING",
                    field=mapping_type,
                    message=f"No active {mapping_type} mapping exists for {source_value}.",
                )
            )


class DiagnosisService:
    def __init__(self, validator: Validator) -> None:
        self.validator = validator

    RC = ReasonCode
    REASON_CODE_MAP: dict[FailureScenario, ReasonCode] = {
        FailureScenario.GL_SOURCE_MAPPING_MISSING: (
            RC.MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING
        ),
        FailureScenario.COST_CENTER_SOURCE_MAPPING_MISSING: (
            RC.MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING
        ),
        FailureScenario.PROFIT_CENTER_SOURCE_MAPPING_MISSING: (
            RC.MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING
        ),
        FailureScenario.MISSING_GL_ACCOUNT_MASTER: RC.MD_GL_ACCOUNT_MASTER_DATA_MISSING,
        FailureScenario.MISSING_COST_CENTER_MASTER: RC.MD_COST_CENTER_MASTER_DATA_MISSING,
        FailureScenario.MISSING_PROFIT_CENTER_MASTER: RC.MD_PROFIT_CENTER_MASTER_DATA_MISSING,
        FailureScenario.MISSING_VENDOR: RC.MD_VENDOR_MASTER_DATA_MISSING,
        FailureScenario.MISSING_CUSTOMER: RC.MD_CUSTOMER_MASTER_DATA_MISSING,
        FailureScenario.MISSING_ASSET_MASTER: RC.MD_ASSET_MASTER_DATA_MISSING,
        FailureScenario.CLOSED_POSTING_PERIOD: RC.DC_POSTING_PERIOD_CLOSED,
    }
    MASTER_DATA_SCENARIOS = {
        FailureScenario.MISSING_GL_ACCOUNT_MASTER,
        FailureScenario.MISSING_COST_CENTER_MASTER,
        FailureScenario.MISSING_PROFIT_CENTER_MASTER,
        FailureScenario.MISSING_VENDOR,
        FailureScenario.MISSING_CUSTOMER,
        FailureScenario.MISSING_ASSET_MASTER,
    }

    def diagnose(self, document: FinancialDocument) -> Diagnosis:
        issues = self.validator.validate(document)
        evidence = [document.error_message]
        if document.failure_scenario not in self.MASTER_DATA_SCENARIOS:
            evidence.extend(issue.message for issue in issues)
        FS = FailureScenario
        root_cause = {
            FS.GL_SOURCE_MAPPING_MISSING: "GL source-to-target mapping is missing.",
            FS.MISSING_GL_ACCOUNT_MASTER: (
                "GL account master data is missing in target. "
                "Source-to-target mapping must also be maintained before reprocessing."
            ),
            FS.COST_CENTER_SOURCE_MAPPING_MISSING: (
                "Cost center source-to-target mapping is missing."
            ),
            FS.MISSING_COST_CENTER_MASTER: (
                "Cost center master data is missing in target. "
                "Source-to-target mapping must also be maintained before reprocessing."
            ),
            FS.PROFIT_CENTER_SOURCE_MAPPING_MISSING: (
                "Profit center source-to-target mapping is missing."
            ),
            FS.MISSING_PROFIT_CENTER_MASTER: (
                "Profit center master data is missing in target. "
                "Source-to-target mapping must also be maintained before reprocessing."
            ),
            FS.MISSING_VENDOR: (
                "Vendor master data is missing in target. "
                "Source-to-target mapping must also be maintained before reprocessing."
            ),
            FS.MISSING_CUSTOMER: (
                "Customer master data is missing in target. "
                "Source-to-target mapping must also be maintained before reprocessing."
            ),
            FS.MISSING_ASSET_MASTER: (
                "Asset master data is missing in target. "
                "Source-to-target mapping must also be maintained before reprocessing."
            ),
            FS.CLOSED_POSTING_PERIOD: "The target posting period is closed.",
        }[document.failure_scenario]
        confidence = 0.95 if issues else 0.8
        return Diagnosis(
            document_id=document.document_id,
            failure_scenario=document.failure_scenario,
            reason_code=self.REASON_CODE_MAP[document.failure_scenario],
            root_cause=root_cause,
            evidence=evidence,
            confidence=confidence,
        )


class RemediationPlanner:
    def plan(self, document: FinancialDocument, diagnosis: Diagnosis) -> RemediationPlan:
        apply_types = {
            FailureScenario.GL_SOURCE_MAPPING_MISSING,
            FailureScenario.COST_CENTER_SOURCE_MAPPING_MISSING,
            FailureScenario.PROFIT_CENTER_SOURCE_MAPPING_MISSING,
        }
        target_master_data_scenarios = {
            FailureScenario.MISSING_GL_ACCOUNT_MASTER,
            FailureScenario.MISSING_COST_CENTER_MASTER,
            FailureScenario.MISSING_PROFIT_CENTER_MASTER,
            FailureScenario.MISSING_VENDOR,
            FailureScenario.MISSING_CUSTOMER,
            FailureScenario.MISSING_ASSET_MASTER,
        }

        if diagnosis.failure_scenario in apply_types:
            return RemediationPlan(
                document_id=document.document_id,
                action=ActionType.MAINTAIN_SOURCE_MAPPING,
                requires_approval=False,
                proposed_changes={"mapping": "maintain missing source-to-target mapping entry"},
                reprocess_after=True,
                rationale=(
                    "Target master data already exists. Maintain the missing "
                    "source-to-target mapping, then reprocess. No approval is required."
                ),
            )

        if diagnosis.failure_scenario in target_master_data_scenarios:
            object_label = MASTER_DATA_OBJECT_LABELS[diagnosis.failure_scenario]
            return RemediationPlan(
                document_id=document.document_id,
                action=ActionType.CREATE_TARGET_MASTER_DATA,
                requires_approval=True,
                proposed_changes={
                    "master_data": f"create missing {object_label} master data in target",
                    "mapping": (
                        f"maintain {object_label} source-to-target mapping after master data "
                        "creation"
                    ),
                    "sequence": [
                        "obtain approval",
                        f"create missing {object_label} master data in target",
                        f"maintain {object_label} source-to-target mapping",
                        "reprocess document",
                    ],
                },
                reprocess_after=True,
                rationale=(
                    f"Create the missing {object_label} master data in the target system "
                    f"(requires approval), then manually maintain the source-to-target mapping "
                    f"and reprocess. Mapping maintenance does not require approval."
                ),
            )

        if diagnosis.failure_scenario == FailureScenario.CLOSED_POSTING_PERIOD:
            return RemediationPlan(
                document_id=document.document_id,
                action=ActionType.EXTERNAL_CONTROLLER_ACTION_REQUIRED,
                requires_approval=True,
                reprocess_after=False,
                rationale="Reopening a posting period requires external controller approval.",
            )

        return RemediationPlan(
            document_id=document.document_id,
            action=ActionType.NO_ACTION,
            requires_approval=False,
            reprocess_after=False,
            rationale="The failure cannot be safely remediated by an autonomous agent.",
        )


class PolicyEngine:
    def __init__(self, approval_store: ApprovalStore) -> None:
        self.approval_store = approval_store

    def evaluate(self, document: FinancialDocument, plan: RemediationPlan) -> GovernanceDecision:
        reasons: list[str] = []
        allowed = True
        requires_approval = plan.requires_approval
        status = WorkflowStatus.DIAGNOSED

        if plan.action == ActionType.CREATE_TARGET_MASTER_DATA:
            requires_approval = True
            if not self.approval_store.is_approved(document.document_id):
                allowed = False
                status = WorkflowStatus.NEEDS_APPROVAL
                reasons.append(
                    "Target master data creation requires approval before reprocessing."
                )

        if document.failure_scenario == FailureScenario.CLOSED_POSTING_PERIOD:
            allowed = False
            status = WorkflowStatus.BLOCKED
            reasons.append("Closed posting period requires external approval to reopen.")

        if allowed and plan.reprocess_after:
            status = WorkflowStatus.DIAGNOSED

        if not reasons:
            reasons.append("Policy checks passed.")

        return GovernanceDecision(
            document_id=document.document_id,
            status=status,
            allowed=allowed,
            requires_approval=requires_approval,
            policy_reasons=reasons,
            audit_reason=self._audit_reason(allowed, requires_approval, reasons),
        )

    @staticmethod
    def _audit_reason(allowed: bool, requires_approval: bool, reasons: list[str]) -> str:
        if allowed and requires_approval:
            decision = "Allowed after approval"
        elif allowed:
            decision = "Allowed"
        else:
            decision = "Not allowed"
        return f"{decision}: {' '.join(reasons)}"


class ReprocessingService:
    def execute(
        self,
        document: FinancialDocument,
        plan: RemediationPlan,
        decision: GovernanceDecision,
    ) -> ReprocessResult:
        if not decision.allowed or not plan.reprocess_after:
            return ReprocessResult(
                document_id=document.document_id,
                success=False,
                message="Reprocessing skipped by governance policy.",
            )

        target_document_id = f"CFIN-{datetime.utcnow():%Y%m%d}-{uuid4().hex[:8].upper()}"
        return ReprocessResult(
            document_id=document.document_id,
            success=True,
            message="Document reprocessed into the synthetic central finance target.",
            target_document_id=target_document_id,
        )


class DeterministicWorkflow:
    def __init__(
        self,
        repository: SyntheticRepository | None = None,
        approval_store: ApprovalStore | None = None,
    ) -> None:
        self.repository = repository or SyntheticRepository()
        self.approval_store = approval_store or ApprovalStore()
        self.validator = Validator(self.repository)
        self.diagnosis_service = DiagnosisService(self.validator)
        self.planner = RemediationPlanner()
        self.policy = PolicyEngine(self.approval_store)
        self.reprocessor = ReprocessingService()

    def run(self, document_id: str, approve: bool = False, execution_mode: str = "deterministic"):
        audit = AuditLog()
        if approve:
            self.approval_store.approve(document_id)
            audit.record("human_approver", "approval_recorded", document_id=document_id)

        document = self.repository.get_document(document_id)
        audit.record("intake_agent", "document_loaded", document_id=document.document_id)

        diagnosis = self.diagnosis_service.diagnose(document)
        audit.record(
            "diagnosis_agent",
            "diagnosis_completed",
            failure_scenario=diagnosis.failure_scenario,
            confidence=diagnosis.confidence,
        )

        plan = self.planner.plan(document, diagnosis)
        audit.record(
            "remediation_planner",
            "plan_created",
            planned_action=plan.action,
            requires_approval=plan.requires_approval,
        )

        decision = self.policy.evaluate(document, plan)
        audit.record(
            "governance_agent",
            "policy_evaluated",
            allowed=decision.allowed,
            status=decision.status,
            reasons=decision.policy_reasons,
        )

        reprocess_result = None
        final_status = decision.status
        if decision.allowed and plan.reprocess_after:
            reprocess_result = self.reprocessor.execute(document, plan, decision)
            final_status = (
                WorkflowStatus.REPROCESSED if reprocess_result.success else WorkflowStatus.BLOCKED
            )
            audit.record(
                "reprocessing_controller",
                "reprocess_executed",
                success=reprocess_result.success,
                target_document_id=reprocess_result.target_document_id,
            )

        agent_summary = generate_analyst_summary(
            document, diagnosis, plan, decision, reprocess_result
        )

        return WorkflowRun(
            document_id=document.document_id,
            execution_mode=execution_mode,
            status=final_status,
            diagnosis=diagnosis,
            remediation_plan=plan,
            governance_decision=decision,
            reprocess_result=reprocess_result,
            audit_events=audit.events,
            agent_summary=agent_summary,
        )


def _summary_policy_decision(
    plan: RemediationPlan,
    decision: GovernanceDecision,
    reprocess_result: ReprocessResult | None,
) -> str:
    if plan.action == ActionType.MAINTAIN_SOURCE_MAPPING:
        return (
            "No approval required - analyst must manually maintain the mapping "
            "in the target mapping table before reprocessing"
        )

    if plan.action == ActionType.EXTERNAL_CONTROLLER_ACTION_REQUIRED:
        return "Blocked - " + "; ".join(decision.policy_reasons)

    if plan.action == ActionType.CREATE_TARGET_MASTER_DATA:
        if decision.allowed and reprocess_result and reprocess_result.success:
            return "Approved - master data created after recorded human approval"
        if decision.requires_approval and not decision.allowed:
            return (
                "Blocked pending human approval - target master data creation requires "
                "sign-off before reprocessing. Mapping maintenance is a manual follow-up "
                "step and does not require its own approval."
            )

    if decision.allowed:
        return "Allowed - action taken"
    return "Blocked - " + "; ".join(decision.policy_reasons)


def generate_analyst_summary(
    document: FinancialDocument,
    diagnosis: Diagnosis,
    plan: RemediationPlan,
    decision: GovernanceDecision,
    reprocess_result: ReprocessResult | None,
) -> str:
    """Plain-English analyst summary aligned with eval golden cases.

    Uses eval-calibrated deterministic text by default. LLM generation is opt-in
    via SUMMARY_USE_LLM=1 and requires OPENAI_API_KEY.
    """
    deterministic = build_deterministic_analyst_summary(
        diagnosis, plan, decision, reprocess_result
    )

    use_llm = os.getenv("SUMMARY_USE_LLM", "0").lower() in {"1", "true", "yes"}
    disable_llm = os.getenv("DISABLE_LLM", "0").lower() in {"1", "true", "yes"}
    api_key = os.getenv("OPENAI_API_KEY")
    if disable_llm or not use_llm or not api_key:
        return deterministic

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        outcome = (
            f"successfully reprocessed (target ID: {reprocess_result.target_document_id})"
            if reprocess_result and reprocess_result.success
            else f"outcome: {decision.status}"
        )

        policy_decision = _summary_policy_decision(plan, decision, reprocess_result)

        prompt = f"""Write a brief analyst-facing summary for a failed Central Finance document.

Output exactly 2-3 short sentences for a finance analyst, not an engineer.

STYLE REFERENCE (match this tone and length; keep facts accurate):
{deterministic}

AUTHORITATIVE FACTS:
- Failure scenario: {diagnosis.failure_scenario}
- Root cause: {diagnosis.root_cause}
- Proposed action: {plan.action}
- Policy decision: {policy_decision}
- Outcome: {outcome}

RULES:
- Never include internal reason codes (MD_*, MP_*, DC_*) or the phrase "reason code".
- Do not cite document IDs.
- State root cause once in plain English, then next steps once. Do not restate approval,
  blocking, or policy status in a closing sentence.
- Avoid meta phrases such as "the analyst should be aware", "sequence of actions required",
  or "as indicated by".
- If action is create_target_master_data and approval is not yet recorded: say approval
  is required, then create master data, maintain source-to-target mapping, and reprocess.
- If action is maintain_source_mapping: analyst maintains the mapping manually; no approval.
- If action is external_controller_action_required: document is blocked; controller must
  reopen posting period externally before retry.

Return only the summary text."""

        summary_model = os.getenv("SUMMARY_MODEL", "gpt-4o")
        request_kwargs: dict[str, object] = {
            "model": summary_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 160,
        }
        if not summary_model.startswith("gpt-5"):
            request_kwargs["temperature"] = 0.2

        model_parameters = {
            key: value
            for key, value in request_kwargs.items()
            if key != "model" and key != "messages" and value is not None
        }

        with summary_generation_observation(
            model=summary_model,
            input_payload={"messages": request_kwargs["messages"]},
            model_parameters=model_parameters,
        ) as observation:
            response = client.chat.completions.create(**request_kwargs)
            content = response.choices[0].message.content
            if observation is not None:
                usage_details = None
                usage = getattr(response, "usage", None)
                if usage is not None:
                    usage_details = {
                        "input": usage.prompt_tokens,
                        "output": usage.completion_tokens,
                        "total": usage.total_tokens,
                    }
                observation.update(output=content, usage_details=usage_details)

        if content:
            return polish_analyst_summary(content.strip())
        return deterministic
    except Exception:
        return deterministic
