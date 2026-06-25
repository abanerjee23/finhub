from __future__ import annotations

import json

from cfin_agents.eval_cases import load_deterministic_cases


def expect_document_outcome(output: str, context: dict) -> dict:
    actual = json.loads(output)
    case_id = context.get("vars", {}).get("case_id")
    cases = {case.id: case for case in load_deterministic_cases()}
    case = cases[case_id]

    # Re-run is avoided; compare Promptfoo provider output against shared expectations.
    checks = {
        "status": actual.get("status") == case.expected.status,
        "failure_scenario": actual.get("failure_scenario") == case.expected.failure_scenario,
        "reason_code": actual.get("reason_code") == case.expected.reason_code,
        "action": actual.get("action") == case.expected.action,
        "requires_approval": actual.get("requires_approval") is case.expected.requires_approval,
        "allowed": actual.get("allowed") is case.expected.allowed,
        "reprocessed": actual.get("reprocessed") is case.expected.reprocessed,
    }

    if all(checks.values()):
        return {
            "pass": True,
            "score": 1.0,
            "reason": f"Case '{case_id}' matched deterministic expectations.",
        }

    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Case '{case_id}' mismatch: {checks}. Actual output: {actual}",
    }
