#!/usr/bin/env bash
# Startet SoBo lokal mit simuliertem Sonos (ohne Home Assistant).
# Admin-UI: http://127.0.0.1:8737  (Ingress-Prüfung lokal auf 127.0.0.1 gelockert)
set -euo pipefail
cd "$(dirname "$0")/../sobo/backend"
export SOBO_DATA_DIR="${SOBO_DATA_DIR:-$PWD/.data}"
export SOBO_FAKE_SONOS=1
export SOBO_FAKE_SPEED="${SOBO_FAKE_SPEED:-10}"
export SOBO_TRUSTED_INGRESS=127.0.0.1
export SOBO_OPTIONS=/nonexistent
exec python -m sobo
