#!/usr/bin/env bash
# P0 smoke (the exit gate): run one full chain offline on synthetic data and assert it produced
# a book + ledger marks. Uses a throwaway sqlite/data dir so it leaves no artifacts behind.
set -euo pipefail
cd "$(dirname "$0")/../engine"
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"

export SQLITE_PATH="$(mktemp -u /tmp/monday-smoke-XXXXXX.db)"
export DATA_DIR="$(mktemp -d /tmp/monday-smoke-XXXXXX)"
OUT="$(mktemp)"
trap 'rm -rf "$DATA_DIR" "$OUT" "$SQLITE_PATH" "$SQLITE_PATH"-wal "$SQLITE_PATH"-shm 2>/dev/null || true' EXIT

echo "→ running one full chain: python -m monday.pipeline"
"$PY" -m monday.pipeline --days 180 >"$OUT" 2>/dev/null

python3 - "$OUT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
w = d["stages"]["recommendations"]["written"]
m = d["stages"]["mark_to_market"]["day0"]["marked"]
assert w > 0 and m > 0, d
print("OK  as_of=%s  universe=%s  recommendations=%s  ledger_marks=%s  portfolio=%s" % (
    d["as_of"], d["stages"]["clean"]["universe"], w, m, d["portfolio"]))
PY
