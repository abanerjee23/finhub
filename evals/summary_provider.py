from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from cfin_agents.eval_cases import workflow_summary  # noqa: E402
from cfin_agents.workflow import run_document_workflow  # noqa: E402


def call_api(prompt: str, options: dict | None = None, context: dict | None = None) -> dict:
    vars_ = (context or {}).get("vars", {})
    document_id = vars_.get("document_id") or prompt.strip()
    approve = str(vars_.get("approve", "false")).lower() == "true"

    # Summary evals use the multi-agent orchestration path when OPENAI_API_KEY is set.
    # Policy outcomes remain deterministic via guarded tool services.
    os.environ["DISABLE_LLM"] = "0"

    run = run_document_workflow(
        document_id=document_id,
        approve=approve,
        force_deterministic=False,
    )
    structured = workflow_summary(run)
    payload = {
        **structured,
        "agent_summary": run.agent_summary,
    }
    return {
        "output": json.dumps(payload, default=str),
        "metadata": {
            "case_id": vars_.get("case_id"),
            "document_id": document_id,
            "approve": approve,
            "execution_mode": run.execution_mode,
            "has_agent_summary": bool(run.agent_summary),
        },
    }
