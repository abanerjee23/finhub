from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from cfin_agents.eval_cases import load_deterministic_cases  # noqa: E402
from cfin_agents.workflow import run_document_workflow  # noqa: E402


def call_api(prompt: str, options: dict | None = None, context: dict | None = None) -> dict:
    vars_ = (context or {}).get("vars", {})
    document_id = vars_.get("document_id") or prompt.strip()
    approve = str(vars_.get("approve", "false")).lower() == "true"

    os.environ["DISABLE_LLM"] = "1"
    run = run_document_workflow(
        document_id=document_id,
        approve=approve,
        force_deterministic=True,
    )
    output = run.promptfoo_summary()
    normalized = {
        key: str(value) if hasattr(value, "value") else value
        for key, value in output.items()
    }
    return {
        "output": json_dumps(normalized),
        "metadata": {
            "case_id": vars_.get("case_id"),
            "document_id": document_id,
            "approve": approve,
            "execution_mode": run.execution_mode,
        },
    }


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, default=str)


def generate_tests() -> list[dict]:
    tests: list[dict] = []
    for case in load_deterministic_cases():
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
                        "value": "file://assertions.py:expect_document_outcome",
                    },
                ],
            }
        )
    return tests
