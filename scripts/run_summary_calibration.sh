#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is required for summary judge calibration."
  exit 1
fi

echo "==> Running summary judge unit tests"
uv run pytest tests/test_summary_cases.py tests/test_summary_judge.py -q

echo "==> Calibrating LLM judge against human pass/fail labels"
PROMPTFOO_CONFIG_DIR=.promptfoo \
PROMPTFOO_DISABLE_WAL_MODE=true \
PROMPTFOO_PYTHON=.venv/bin/python \
npx promptfoo eval -c evals/promptfoo_summary_calibration_config.yaml --no-progress-bar

echo "Summary judge calibration completed successfully."
