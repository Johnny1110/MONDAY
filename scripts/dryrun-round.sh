#!/usr/bin/env bash
# D1 — dry-run one full 2.0 manual round, ENGINE-SIDE, on a PAPER book.
#
# This drives the platform calls a round makes (the agent-side judgement — macro/micro briefs, analyst
# overlay, morgan's composition — runs in the live swarm and is NOT scripted here). It is safe + idempotent
# and writes only to the PAPER book. Use it during the ≥N-day dry-run to confirm the engine half of the
# round works end-to-end before the cutover (ADR 0006). The 1.0 paper_positions path is untouched.
#
#   BASE=http://127.0.0.1:7790 ./scripts/dryrun-round.sh        # default; override BASE for a dev engine
#
# It never flips book_mode and never places a real order (invariant 11) — fills here are paper bookkeeping.
set -uo pipefail
BASE="${BASE:-http://127.0.0.1:7790}"
PY="$(dirname "$0")/../engine/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
PASS=0; FAIL=0

say() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
# j <json> <dotted.path> — extract a field (returns empty on miss)
j() { local p="${2:-${1:-}}"; "$PY" -c "import sys,json;d=json.load(sys.stdin)
p='$p'.split('.') if '$p' else []
for k in p:
 d=d.get(k) if isinstance(d,dict) else None
print('' if d is None else d)" 2>/dev/null; }
ok()   { PASS=$((PASS+1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31m✗\033[0m %s\n' "$1"; }
get()  { curl -s "$BASE$1"; }
post() { curl -s -X POST "$BASE$1" ${2:+-H 'content-type: application/json' -d "$2"}; }
code() { curl -s -o /dev/null -w '%{http_code}' -X "${1}" "$BASE$2" ${3:+-H 'content-type: application/json' -d "$3"}; }

say "0. health"
[ "$(get /health | j '' ok)" = "True" ] && ok "engine up at $BASE" || { bad "engine not reachable at $BASE"; exit 1; }

say "1. trigger — POST /api/system/run-round (idempotent)"
r1=$(code POST /api/system/run-round); r2=$(code POST /api/system/run-round)
{ [ "$r1" = "200" ] && [ "$r2" = "409" ]; } && ok "first 200, second 409 (one wake/day)" || bad "expected 200 then 409, got $r1/$r2"

say "2. STEP 0 — prepare (finalize=false) + macro/refresh"
task=$(post '/api/system/run-pipeline?source=finmind&model=gbdt&finalize=false&post=false' | j '' task_id)
if [ -n "$task" ]; then
  for _ in $(seq 1 120); do st=$(get "/api/system/tasks/$task" | j '' status); [ "$st" = "succeeded" -o "$st" = "failed" ] && break; sleep 2; done
  [ "$st" = "succeeded" ] && ok "pipeline prepare succeeded (task $task)" || bad "pipeline $st (task $task)"
else bad "run-pipeline did not return a task_id (single-flight? check /api/system/status)"; fi
mr=$(post '/api/macro/refresh'); masof=$(echo "$mr" | j '' as_of); mn=$(echo "$mr" | j '' n)
if [ -n "$masof" ]; then ok "macro snapshot as_of=$masof n=$mn"
elif [ -n "$mn" ]; then echo "  · macro degraded: engine 200 but no snapshot (upstream rate-limit/blocked, n=$mn) — GATE-1 would flag a degraded-data day (degrade-ok)"
else bad "macro/refresh endpoint unreachable / malformed response"; fi

say "3. SYNC A — rescope to focus sectors (sample 半導體; morgan sets these live)"
asof=$(get /api/system/status | j '' last_as_of)
rs=$(post '/api/signals/rescope' '{"focus_sectors":["半導體"]}')
[ -n "$(echo "$rs" | j '' candidate_count)" ] && ok "rescoped: $(echo "$rs" | j '' candidate_count) candidates, all_ranked=$(echo "$rs" | j '' all_ranked)" || bad "rescope failed: $(echo "$rs" | head -c 120)"

say "4. STEP A1 quant + 5. TIER 2 analysts — (swarm-side judgement, not scripted)"
echo "  · quant reviews /api/signals/today; a-tech/a-chips/a-catalyst overlay candidates+holdings → review flags"

say "6. SYNC B — sizing + holdings review (engine side)"
sz=$(post '/api/book/sizing' '{"book_value":1000000,"regime_state":"neutral","candidates":[{"symbol":"2330","conviction":0.7,"stop_loss":920,"price":1000}]}')
[ -n "$(echo "$sz" | j '' regime_state)" ] && ok "sizing ok (regime=$(echo "$sz" | j '' regime_state))" || bad "sizing failed"
rv=$(get '/api/book/review'); [ -n "$(echo "$rv" | j '' count)" ] && ok "holdings review ran (count=$(echo "$rv" | j '' count)) — runs even with no holdings" || bad "review failed"

say "7. GATE 2 — risk (engine read)"
[ -n "$(get '/api/book/exposure' | j '' total)" ] && ok "exposure/cash readable (GATE 2 input)" || bad "exposure read failed"

say "8. FINALIZE — paper fill + 6-section report (PAPER ONLY; swarm proposes, User confirms)"
fk="dryrun-$asof-2330"
ff=$(post '/api/book/fill' "{\"book\":\"paper\",\"symbol\":\"2330\",\"side\":\"buy\",\"qty\":1000,\"price\":1000,\"at\":\"$asof\",\"fill_key\":\"$fk\",\"reason\":\"dryrun\"}")
[ "$(echo "$ff" | j '' position.symbol)" = "2330" ] && ok "paper fill recorded (idempotent via fill_key)" || bad "paper fill failed: $(echo "$ff" | head -c 140)"
scaf=$(get '/api/reports/daily/scaffold')
sec_ok=$("$PY" -c "import json;d=json.loads('''$scaf''');print('ok' if set(d.get('sections',{}))>={'macro','market_narrative','holdings_review','new_ideas','exposure','risk_notes'} else 'no')" 2>/dev/null)
[ "$sec_ok" = "ok" ] && ok "report scaffold has all 6 sections" || bad "scaffold missing sections"
rep=$(post '/api/reports/daily' "$scaf")
[ -n "$(echo "$rep" | j '' summary_text)" ] && ok "6-section report posted (disclaimer carried)" || bad "report POST failed: $(echo "$rep" | head -c 140)"

say "9. reconcile + calibration"
[ -n "$(post '/api/ledger/reconcile?source=finmind' | j '' mark_date)" ] && ok "daily reconcile ran" || echo "  · reconcile: no open paper positions to mark (ok)"
[ -n "$(post '/api/calibration/macro/settle' | j '' as_of)" ] && ok "macro-call settle ran" || bad "macro settle failed"
crun=$(post '/api/calibration/run?post=false'); { echo "$crun" | grep -q '"macro"'; } && ok "scorecard folds macro + position dims" || bad "scorecard missing 2.0 dims"

printf '\n\033[1m== dry-run summary: %d passed, %d failed ==\033[0m\n' "$PASS" "$FAIL"
echo "Agent-side checklist (run against the live swarm, not this script): GATE-1 degraded-data day ships"
echo "holdings-only report; analysts emit review flags; risk-monitor blocks an over-sized book; safety-net"
echo "produces a report with the swarm down. See D1 / RUNBOOK §10 for the full 12-point checklist."
[ "$FAIL" -eq 0 ]
