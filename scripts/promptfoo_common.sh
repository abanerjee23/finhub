#!/usr/bin/env bash
# Shared Promptfoo env for FinHub (source from other scripts — do not execute directly).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PROMPTFOO_CONFIG_DIR=.promptfoo
export PROMPTFOO_DISABLE_WAL_MODE=true
export PROMPTFOO_PYTHON="${PROMPTFOO_PYTHON:-.venv/bin/python}"

# Default: local-only eval runs. Set PROMPTFOO_SHARE=1 in .env to upload to your cloud org.
PROMPTFOO_SHARE_FLAG=(--no-share)
if [[ "${PROMPTFOO_SHARE:-0}" =~ ^(1|true|yes)$ ]]; then
  PROMPTFOO_SHARE_FLAG=(--share)
fi
