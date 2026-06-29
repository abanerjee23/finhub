from __future__ import annotations

from cfin_agents.analyst_summary import (
    EVAL_ALIGNED_SUMMARIES,
    build_deterministic_analyst_summary,
    polish_analyst_summary,
    resolve_agent_summary,
)
from cfin_agents.eval_cases import load_summary_cases
from cfin_agents.repository import SyntheticRepository
from cfin_agents.services import ApprovalStore, DeterministicWorkflow


def test_eval_templates_cover_all_ten_reason_codes() -> None:
    cases = load_summary_cases()
    for case in cases:
        assert case.golden.expected_reason_code in {
            code.value for code in EVAL_ALIGNED_SUMMARIES
        }


def test_deterministic_summaries_match_eval_golden_examples() -> None:
    repository = SyntheticRepository()
    workflow = DeterministicWorkflow(repository=repository, approval_store=ApprovalStore())

    for case in load_summary_cases():
        run = workflow.run(case.document_id, approve=case.approve)
        summary = build_deterministic_analyst_summary(
            run.diagnosis,
            run.remediation_plan,
            run.governance_decision,
            run.reprocess_result,
        )
        expected = EVAL_ALIGNED_SUMMARIES[run.diagnosis.reason_code]
        golden_example = " ".join(case.golden.example_good_summary.split())

        assert summary == expected
        assert summary == golden_example
        assert run.diagnosis.reason_code.value == case.golden.expected_reason_code
        assert run.remediation_plan.action.value == case.golden.expected_action
        assert run.status.value == case.golden.expected_status

        for phrase in case.golden.must_not_say:
            assert phrase.lower() not in summary.lower(), (
                f"{case.document_id} must not say '{phrase}'"
            )


def test_resolve_agent_summary_returns_none_for_legacy_or_missing_text() -> None:
    run = DeterministicWorkflow(
        repository=SyntheticRepository(),
        approval_store=ApprovalStore(),
    ).run("DOC-1005", execution_mode="test")
    assert resolve_agent_summary(run.model_copy(update={"agent_summary": None})) is None

    legacy = (
        "The finance document DOC-GEN-00002 failed because the cost center master data is "
        "missing, as indicated by the reason code MD_COST_CENTER_MASTER_DATA_MISSING."
    )
    assert resolve_agent_summary(run.model_copy(update={"agent_summary": legacy})) is None

    current = "Document posting failed because cost center master data is missing in the target system."
    assert resolve_agent_summary(run.model_copy(update={"agent_summary": current})) == current


def test_polish_analyst_summary_strips_internal_codes_and_meta_phrases() -> None:
    raw = (
        "The finance document DOC-GEN-00002 failed because cost center master data is "
        "missing, as indicated by the reason code MD_COST_CENTER_MASTER_DATA_MISSING. "
        "The sequence of actions required is: obtain approval and reprocess. "
        "The analyst should be aware that the process is currently blocked pending approval."
    )
    polished = polish_analyst_summary(raw)
    assert "MD_COST_CENTER" not in polished
    assert "reason code" not in polished.lower()
    assert "analyst should be aware" not in polished.lower()
    assert "sequence of actions required" not in polished.lower()
