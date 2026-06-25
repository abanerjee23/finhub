#!/usr/bin/env python3
"""Run live summary evals for all golden cases and append results to model_outputs.jsonl."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from cfin_agents.eval_results import (  # noqa: E402
    export_records_to_excel,
    run_summary_eval_batch,
    summarize_records,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and log summary eval results.")
    parser.add_argument(
        "--excel",
        type=Path,
        help="Optional path to Excel workbook (Model_Outputs tab will be appended).",
    )
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Skip LLM judge (smoke checks only). Useful without OPENAI_API_KEY.",
    )
    args = parser.parse_args()

    if not args.skip_judge and not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required unless --skip-judge is set.", file=sys.stderr)
        return 1

    run_id, records = run_summary_eval_batch(skip_judge=args.skip_judge)
    summary = summarize_records(records)
    print(json.dumps({"run_id": run_id, **summary}, indent=2))

    if args.excel:
        export_records_to_excel(records, args.excel)
        print(f"Appended {len(records)} rows to {args.excel}")

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
