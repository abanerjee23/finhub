from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from cfin_agents.workflow import run_document_workflow  # noqa: E402


def main() -> None:
    os.environ["DISABLE_LLM"] = "1"

    checks = [
        ("DOC-1002", False, "reprocessed"),
        ("DOC-1001", True, "reprocessed"),
        ("DOC-1006", False, "blocked"),
    ]

    failures: list[str] = []
    for document_id, approve, expected_status in checks:
        run = run_document_workflow(
            document_id,
            approve=approve,
            force_deterministic=True,
        )
        if run.status != expected_status:
            failures.append(
                f"{document_id}: expected {expected_status}, got {run.status}"
            )

    if failures:
        raise SystemExit("\n".join(failures))

    print("Smoke check passed: auto, approved, and blocked scenarios behaved as expected.")


if __name__ == "__main__":
    main()
