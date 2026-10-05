#!/usr/bin/env bash
# Runs SoBo locally with a simulated Sonos (without Home Assistant).
# Admin UI: http://127.0.0.1:8737  (ingress check relaxed to 127.0.0.1 locally)
set -euo pipefail
cd "$(dirname "$0")/../sobo/backend"
export SOBO_DATA_DIR="${SOBO_DATA_DIR:-$PWD/.data}"
export SOBO_FAKE_SONOS=1
export SOBO_FAKE_SPEED="${SOBO_FAKE_SPEED:-10}"
export SOBO_TRUSTED_INGRESS=127.0.0.1
export SOBO_OPTIONS=/nonexistent
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m sobo
elif command -v uv >/dev/null 2>&1; then
  exec uv run python -m sobo
else
  echo "No .venv found. First run: cd sobo/backend && uv venv && uv pip install -e '.[dev]'" >&2
  exit 1
fi
