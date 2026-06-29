#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Running pytest deterministic suite"
uv run pytest tests/test_deterministic_cases.py tests/test_services.py -q

echo "==> Running workflow smoke check"
uv run python scripts/smoke_check.py

echo "==> Running Promptfoo deterministic evals"
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/promptfoo_common.sh"
npx promptfoo eval -c evals/promptfooconfig.yaml --no-progress-bar "${PROMPTFOO_SHARE_FLAG[@]}"

echo "Deterministic eval suite completed successfully."
