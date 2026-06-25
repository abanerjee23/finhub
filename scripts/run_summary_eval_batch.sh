#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is required for summary eval batch logging."
  exit 1
fi

echo "==> Running live summary eval batch for all golden cases"
uv run python scripts/log_summary_eval_results.py "$@"

echo "Summary eval batch logging completed."
