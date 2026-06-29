#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/promptfoo_common.sh"

if ! npx promptfoo auth whoami >/dev/null 2>&1; then
  echo "Not logged in to Promptfoo cloud. Add PROMPTFOO_API_KEY to .env or run:"
  echo "  npx promptfoo auth login -k YOUR_KEY"
  exit 1
fi

echo "Sharing most recent FinHub eval to Promptfoo cloud..."
npx promptfoo share
