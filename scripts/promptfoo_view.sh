#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/promptfoo_common.sh"

echo "Opening FinHub Promptfoo viewer (project-local .promptfoo/)"
echo "Cloud org: run 'npx promptfoo auth whoami' — local viewer stays separate from ~/.promptfoo"
echo

npx promptfoo view
