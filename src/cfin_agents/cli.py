from __future__ import annotations

import argparse
import json

from cfin_agents.workflow import run_document_workflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a synthetic CFIN document workflow.")
    parser.add_argument("document_id", help="Synthetic document ID, for example DOC-1002.")
    parser.add_argument("--approve", action="store_true", help="Record human approval first.")
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Force deterministic execution even if OPENAI_API_KEY is configured.",
    )
    args = parser.parse_args()

    run = run_document_workflow(
        args.document_id,
        approve=args.approve,
        force_deterministic=args.deterministic,
    )
    print(json.dumps(run.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
