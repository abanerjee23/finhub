#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is required for summary evals (agent_summary generation + judge)."
  echo "Copy .env.example to .env and add your key, or export OPENAI_API_KEY."
  exit 1
fi

export SUMMARY_USE_LLM=1

echo "==> Running summary judge unit tests"
uv run pytest tests/test_summary_cases.py tests/test_summary_judge.py -q

echo "==> Calibrating LLM judge against human pass/fail labels"
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/promptfoo_common.sh"
npx promptfoo eval -c evals/promptfoo_summary_calibration_config.yaml --no-progress-bar "${PROMPTFOO_SHARE_FLAG[@]}"

echo "==> Running live summary evals with LLM judge"
npx promptfoo eval -c evals/promptfoo_summary_config.yaml --no-progress-bar "${PROMPTFOO_SHARE_FLAG[@]}"

echo "Summary eval suite completed successfully."

echo "==> Logging summary eval batch to evals/model_outputs.jsonl"
uv run python scripts/log_summary_eval_results.py
