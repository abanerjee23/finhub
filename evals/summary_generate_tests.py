from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from cfin_agents.eval_cases import load_summary_cases  # noqa: E402


def generate_tests() -> list[dict]:
    tests: list[dict] = []
    for case in load_summary_cases():
        tests.append(
            {
                "description": case.description,
                "vars": {
                    "case_id": case.id,
                    "document_id": case.document_id,
                    "approve": case.approve,
                },
                "assert": [
                    {"type": "contains-json"},
                    {
                        "type": "python",
                        "value": "file://summary_assertions.py:expect_summary_smoke",
                    },
                    {
                        "type": "python",
                        "value": "file://summary_assertions.py:expect_summary_judge",
                    },
                ],
            }
        )
    return tests
