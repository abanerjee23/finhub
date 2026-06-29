#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Starting backend on http://127.0.0.1:8000"
uv run cfin-api &
API_PID=$!

cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT

for _ in {1..30}; do
  if curl -sf http://127.0.0.1:8000/api/health >/dev/null; then
    break
  fi
  sleep 0.2
done

echo "Starting frontend on http://localhost:5173"
npm --prefix frontend run dev
