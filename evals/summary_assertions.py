from __future__ import annotations

import json
import os

from cfin_agents.eval_cases import load_summary_cases
from cfin_agents.summary_judge import grade_agent_summary


def _structured_stub(document_id: str, case_id: str) -> dict[str, str | bool | None]:
    case = next(item for item in load_summary_cases() if item.id == case_id)
    golden = case.golden
    return {
        "document_id": document_id,
        "status": golden.expected_status,
        "reason_code": golden.expected_reason_code,
        "action": golden.expected_action,
        "reprocessed": golden.expected_status == "reprocessed",
        "agent_summary": None,
    }


def expect_summary_smoke(output: str, context: dict) -> dict:
    """Structured smoke checks before the LLM judge runs."""
    actual = json.loads(output)
    case_id = context.get("vars", {}).get("case_id")
    cases = {case.id: case for case in load_summary_cases()}
    case = cases[case_id]
    golden = case.golden

    checks = {
        "status": actual.get("status") == golden.expected_status,
        "reason_code": actual.get("reason_code") == golden.expected_reason_code,
        "action": actual.get("action") == golden.expected_action,
        "agent_summary_present": bool(actual.get("agent_summary")),
    }

    if not os.getenv("OPENAI_API_KEY"):
        checks["agent_summary_present"] = True

    if all(checks.values()):
        return {
            "pass": True,
            "score": 1.0,
            "reason": f"Case '{case_id}' passed summary smoke checks.",
        }

    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Case '{case_id}' failed summary smoke checks: {checks}. Actual: {actual}",
    }


def expect_summary_judge(output: str, context: dict) -> dict:
    """LLM-as-judge using golden truth and the dual gate rubric."""
    if os.getenv("SKIP_SUMMARY_JUDGE", "").lower() in {"1", "true", "yes"}:
        return {
            "pass": True,
            "score": 1.0,
            "reason": "Summary judge skipped via SKIP_SUMMARY_JUDGE.",
        }

    vars_ = context.get("vars", {})
    case_id = vars_.get("summary_case_id") or vars_.get("case_id")
    cases = {case.id: case for case in load_summary_cases()}
    case = cases[case_id]

    if vars_.get("generated_summary"):
        agent_summary = vars_["generated_summary"]
        structured = _structured_stub(case.document_id, case.id)
    else:
        actual = json.loads(output)
        agent_summary = actual.get("agent_summary")
        structured = {key: value for key, value in actual.items() if key != "agent_summary"}

    if not agent_summary:
        return {
            "pass": False,
            "score": 0.0,
            "reason": f"Case '{case_id}' has no agent_summary to judge.",
        }

    result = grade_agent_summary(case, agent_summary, structured)
    passed = bool(result["overall_pass"])
    score = (result["accuracy_score"] + result["actionability_score"]) / 10.0
    reason = (
        f"accuracy={result['accuracy_score']}, actionability={result['actionability_score']}, "
        f"audience_fit={result.get('audience_fit_score')}, "
        f"conciseness={result.get('conciseness_score')}. "
        f"{result['reasoning']}"
    )

    return {"pass": passed, "score": score, "reason": reason}


def expect_calibration_judge(output: str, context: dict) -> dict:
    """Judge a fixed calibration summary and compare to the human pass/fail label."""
    vars_ = context.get("vars", {})
    expected_pass = str(vars_.get("expected_pass", "false")).lower() == "true"
    result = expect_summary_judge(output, context)
    judge_pass = result["pass"]

    if judge_pass is expected_pass:
        return {
            "pass": True,
            "score": 1.0,
            "reason": (
                f"Calibration '{vars_.get('case_id')}' matched human label "
                f"(expected_pass={expected_pass}, judge_pass={judge_pass}). "
                f"{result['reason']}"
            ),
        }

    return {
        "pass": False,
        "score": 0.0,
        "reason": (
            f"Calibration '{vars_.get('case_id')}' disagreed with human label "
            f"(expected_pass={expected_pass}, judge_pass={judge_pass}). "
            f"{result['reason']}"
        ),
    }
