from __future__ import annotations

from cfin_agents.models import ActionType, ReasonCode, WorkflowStatus
from cfin_agents.repository import SyntheticRepository
from cfin_agents.services import (
    ApprovalStore,
    DiagnosisService,
    PolicyEngine,
    RemediationPlanner,
    ReprocessingService,
    Validator,
)


def test_validator_flags_missing_gl_mapping() -> None:
    repository = SyntheticRepository()
    document = repository.get_document("DOC-1001")
    issues = Validator(repository).validate(document)

    codes = {issue.code for issue in issues}
    assert "MISSING_GL_ACCOUNT_MAPPING" in codes


def test_validator_flags_missing_cost_center_mapping() -> None:
    repository = SyntheticRepository()
    document = repository.get_document("DOC-1005")
    issues = Validator(repository).validate(document)

    codes = {issue.code for issue in issues}
    assert "MISSING_COST_CENTER_MAPPING" in codes


def test_validator_flags_missing_profit_center_mapping() -> None:
    repository = SyntheticRepository()
    document = repository.get_document("DOC-1008")
    issues = Validator(repository).validate(document)

    codes = {issue.code for issue in issues}
    assert "MISSING_PROFIT_CENTER_MAPPING" in codes


def test_validator_flags_closed_posting_period() -> None:
    repository = SyntheticRepository()
    document = repository.get_document("DOC-1006")
    issues = Validator(repository).validate(document)

    codes = {issue.code for issue in issues}
    assert "POSTING_PERIOD_CLOSED" in codes


def test_validator_finds_no_issues_for_apply_cases() -> None:
    """Apply cases have existing mappings — validator should raise no mapping issues."""
    repository = SyntheticRepository()
    validator = Validator(repository)

    for doc_id in ["DOC-1002", "DOC-1004", "DOC-1007"]:
        document = repository.get_document(doc_id)
        issues = validator.validate(document)
        mapping_issue_codes = {i.code for i in issues if "MAPPING" in i.code}
        assert not mapping_issue_codes, (
            f"{doc_id} should have no mapping issues, got {mapping_issue_codes}"
        )


def test_diagnosis_assigns_mp_reason_codes_for_source_mapping_cases() -> None:
    repository = SyntheticRepository()
    diagnosis_service = DiagnosisService(Validator(repository))

    expected = {
        "DOC-1002": ReasonCode.MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING,
        "DOC-1004": ReasonCode.MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING,
        "DOC-1007": ReasonCode.MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING,
    }
    for doc_id, reason_code in expected.items():
        document = repository.get_document(doc_id)
        diagnosis = diagnosis_service.diagnose(document)
        assert diagnosis.reason_code == reason_code, f"{doc_id}: expected {reason_code}"


def test_diagnosis_assigns_md_reason_codes_for_missing_master_data_objects() -> None:
    repository = SyntheticRepository()
    diagnosis_service = DiagnosisService(Validator(repository))

    expected = {
        "DOC-1001": ReasonCode.MD_GL_ACCOUNT_MASTER_DATA_MISSING,
        "DOC-1005": ReasonCode.MD_COST_CENTER_MASTER_DATA_MISSING,
        "DOC-1008": ReasonCode.MD_PROFIT_CENTER_MASTER_DATA_MISSING,
    }
    for doc_id, reason_code in expected.items():
        document = repository.get_document(doc_id)
        diagnosis = diagnosis_service.diagnose(document)
        assert diagnosis.reason_code == reason_code, f"{doc_id}: expected {reason_code}"


def test_diagnosis_assigns_md_reason_codes_for_missing_master_data() -> None:
    repository = SyntheticRepository()
    diagnosis_service = DiagnosisService(Validator(repository))

    expected = {
        "DOC-1003": ReasonCode.MD_VENDOR_MASTER_DATA_MISSING,
        "DOC-1009": ReasonCode.MD_CUSTOMER_MASTER_DATA_MISSING,
        "DOC-1010": ReasonCode.MD_ASSET_MASTER_DATA_MISSING,
    }
    for doc_id, reason_code in expected.items():
        document = repository.get_document(doc_id)
        diagnosis = diagnosis_service.diagnose(document)
        assert diagnosis.reason_code == reason_code, f"{doc_id}: expected {reason_code}"


def test_diagnosis_assigns_dc_reason_code_for_closed_period() -> None:
    repository = SyntheticRepository()
    diagnosis_service = DiagnosisService(Validator(repository))

    document = repository.get_document("DOC-1006")
    diagnosis = diagnosis_service.diagnose(document)
    assert diagnosis.reason_code == ReasonCode.DC_POSTING_PERIOD_CLOSED


def test_remediation_planner_source_mapping_cases() -> None:
    repository = SyntheticRepository()
    planner = RemediationPlanner()
    diagnosis_service = DiagnosisService(Validator(repository))

    for doc_id in ["DOC-1002", "DOC-1004", "DOC-1007"]:
        document = repository.get_document(doc_id)
        diagnosis = diagnosis_service.diagnose(document)
        plan = planner.plan(document, diagnosis)

        assert plan.action == ActionType.MAINTAIN_SOURCE_MAPPING
        assert plan.requires_approval is False
        assert plan.reprocess_after is True


def test_remediation_planner_missing_gl_cost_profit_master_data_cases() -> None:
    repository = SyntheticRepository()
    planner = RemediationPlanner()
    diagnosis_service = DiagnosisService(Validator(repository))

    for doc_id in ["DOC-1001", "DOC-1005", "DOC-1008"]:
        document = repository.get_document(doc_id)
        diagnosis = diagnosis_service.diagnose(document)
        plan = planner.plan(document, diagnosis)

        assert plan.action == ActionType.CREATE_TARGET_MASTER_DATA
        assert plan.requires_approval is True
        assert plan.reprocess_after is True


def test_remediation_planner_missing_master_data_cases() -> None:
    repository = SyntheticRepository()
    planner = RemediationPlanner()
    diagnosis_service = DiagnosisService(Validator(repository))

    for doc_id in ["DOC-1003", "DOC-1009", "DOC-1010"]:
        document = repository.get_document(doc_id)
        diagnosis = diagnosis_service.diagnose(document)
        plan = planner.plan(document, diagnosis)

        assert plan.action == ActionType.CREATE_TARGET_MASTER_DATA
        assert plan.requires_approval is True
        assert plan.reprocess_after is True


def test_policy_blocks_master_data_mutation_without_approval() -> None:
    repository = SyntheticRepository()
    planner = RemediationPlanner()
    diagnosis_service = DiagnosisService(Validator(repository))
    policy = PolicyEngine(ApprovalStore())

    for doc_id in ["DOC-1001", "DOC-1003", "DOC-1009"]:
        document = repository.get_document(doc_id)
        diagnosis = diagnosis_service.diagnose(document)
        plan = planner.plan(document, diagnosis)
        decision = policy.evaluate(document, plan)

        assert decision.allowed is False
        assert decision.status == WorkflowStatus.NEEDS_APPROVAL
        assert decision.requires_approval is True
        assert any("Target master-data creation" in r for r in decision.policy_reasons)


def test_policy_allows_master_data_mutation_with_approval() -> None:
    repository = SyntheticRepository()
    planner = RemediationPlanner()
    diagnosis_service = DiagnosisService(Validator(repository))
    approval_store = ApprovalStore()
    approval_store.approve("DOC-1001")
    policy = PolicyEngine(approval_store)

    document = repository.get_document("DOC-1001")
    diagnosis = diagnosis_service.diagnose(document)
    plan = planner.plan(document, diagnosis)
    decision = policy.evaluate(document, plan)

    assert decision.allowed is True


def test_policy_always_blocks_closed_posting_period() -> None:
    repository = SyntheticRepository()
    planner = RemediationPlanner()
    diagnosis_service = DiagnosisService(Validator(repository))
    approval_store = ApprovalStore()
    approval_store.approve("DOC-1006")
    policy = PolicyEngine(approval_store)

    document = repository.get_document("DOC-1006")
    diagnosis = diagnosis_service.diagnose(document)
    plan = planner.plan(document, diagnosis)
    decision = policy.evaluate(document, plan)

    assert decision.allowed is False
    assert decision.status == WorkflowStatus.BLOCKED


def test_reprocessor_skips_when_not_allowed() -> None:
    repository = SyntheticRepository()
    planner = RemediationPlanner()
    diagnosis_service = DiagnosisService(Validator(repository))
    policy = PolicyEngine(ApprovalStore())
    reprocessor = ReprocessingService()

    document = repository.get_document("DOC-1001")
    diagnosis = diagnosis_service.diagnose(document)
    plan = planner.plan(document, diagnosis)
    decision = policy.evaluate(document, plan)
    result = reprocessor.execute(document, plan, decision)

    assert result.success is False
    assert "skipped" in result.message.lower()


def test_reprocessor_succeeds_for_apply_case() -> None:
    repository = SyntheticRepository()
    planner = RemediationPlanner()
    diagnosis_service = DiagnosisService(Validator(repository))
    policy = PolicyEngine(ApprovalStore())
    reprocessor = ReprocessingService()

    document = repository.get_document("DOC-1002")
    diagnosis = diagnosis_service.diagnose(document)
    plan = planner.plan(document, diagnosis)
    decision = policy.evaluate(document, plan)
    result = reprocessor.execute(document, plan, decision)

    assert decision.allowed is True
    assert plan.reprocess_after is True
    assert result.success is True
    assert result.target_document_id is not None


def test_diagnosis_failure_scenario_matches_document_metadata() -> None:
    repository = SyntheticRepository()
    diagnosis_service = DiagnosisService(Validator(repository))

    all_docs = [f"DOC-{i}" for i in range(1001, 1011)]
    for document_id in all_docs:
        document = repository.get_document(document_id)
        diagnosis = diagnosis_service.diagnose(document)
        assert diagnosis.failure_scenario == document.failure_scenario
