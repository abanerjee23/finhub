from __future__ import annotations

from cfin_agents.eval_cases import load_summary_cases
from cfin_agents.summary_judge import GATE_MIN_SCORE, build_judge_prompt, parse_judge_response


def test_parse_judge_response_applies_gate_rule() -> None:
    result = parse_judge_response(
        """
        {
          "accuracy_score": 5,
          "actionability_score": 3,
          "audience_fit_score": 4,
          "conciseness_score": 4,
          "overall_pass": true,
          "reasoning": "ignored by parser"
        }
        """
    )
    assert result["accuracy_score"] == 5
    assert result["actionability_score"] == 3
    assert result["overall_pass"] is False


def test_parse_judge_response_passes_when_both_gates_met() -> None:
    result = parse_judge_response(
        """
        {
          "accuracy_score": 4,
          "actionability_score": 4,
          "audience_fit_score": 3,
          "conciseness_score": 3,
          "overall_pass": false,
          "reasoning": "both gates met"
        }
        """
    )
    assert result["overall_pass"] is True
    assert GATE_MIN_SCORE == 4


def test_build_judge_prompt_includes_golden_fields() -> None:
    case = next(item for item in load_summary_cases() if item.document_id == "DOC-1001")
    prompt = build_judge_prompt(
        case,
        "Sample summary text.",
        {"status": "needs_approval", "reason_code": "MD_GL_ACCOUNT_MASTER_DATA_MISSING"},
    )
    assert "MD_GL_ACCOUNT_MASTER_DATA_MISSING" in prompt
    assert "missing mapping is the root cause" in prompt
    assert "Sample summary text." in prompt
