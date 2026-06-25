from __future__ import annotations

import pytest

from cfin_agents.eval_cases import evaluate_case, load_deterministic_cases
from cfin_agents.workflow import run_document_workflow


@pytest.mark.parametrize("case", load_deterministic_cases(), ids=lambda case: case.id)
def test_deterministic_case_matrix(case) -> None:
    run = run_document_workflow(
        case.document_id,
        approve=case.approve,
        force_deterministic=True,
    )
    passed, checks, actual = evaluate_case(run, case)

    assert passed, f"Case '{case.id}' failed checks {checks}. Actual: {actual}"
