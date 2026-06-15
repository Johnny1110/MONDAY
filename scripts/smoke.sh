#!/usr/bin/env bash
# Offline smoke (the exit gate): run one full chain on the RECORDED REAL-DATA fixture
# (no network, no fake data) and assert it produced a book + ledger marks. Throwaway in-memory
# store + temp data dir, so it leaves no artifacts behind.
set -euo pipefail
cd "$(dirname "$0")/../engine"
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"

echo "→ running one full chain on the real-data fixture: tests.realdata.run_smoke"
"$PY" -c "from tests.realdata import run_smoke; run_smoke()"
