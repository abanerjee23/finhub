from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from cfin_agents.eval_cases import load_summary_calibration_cases  # noqa: E402


def generate_tests() -> list[dict]:
    tests: list[dict] = []
    for case in load_summary_calibration_cases():
        tests.append(
            {
                "description": f"Calibration {case.id} expected_pass={case.expected_pass}",
                "vars": {
                    "case_id": case.id,
                    "summary_case_id": case.summary_case_id,
                    "document_id": case.document_id,
                    "expected_pass": case.expected_pass,
                    "generated_summary": case.generated_summary,
                },
                "assert": [
                    {
                        "type": "python",
                        "value": "file://summary_assertions.py:expect_calibration_judge",
                    },
                ],
            }
        )
    return tests
