# Monday — Operations Runbook

How to launch, stop, reset, and re-test the Monday lab. The authoritative design spec is
[`docs/whitepaper.md`](docs/whitepaper.md); the working guide is [`CLAUDE.md`](CLAUDE.md). This file is
the **operational** companion: the exact commands, in order, with the gotchas that actually bite.

Paper portfolio only — no real money, ever.

---

## 1. Architecture at a glance

Two planes, three long-lived processes, three ports:

| Plane | Process | Port | Start with |
|---|---|---|---|
| Transactional store | `monday-postgres` (Docker) | `5432` | `docker compose up -d` (in `engine/`) |
| **Monday engine** (FastAPI) | `python -m monday` | `7790` | `.venv/bin/python -m monday` (in `engine/`) |
| evva swarm runtime | `evva service start` (**shared daemon**) | `8888` | `evva service start`, then `evva swarm run monday` |

- Engine dashboard: <http://localhost:7790/> · swarm dashboard: <http://localhost:8888/>
- ⚠️ The `evva service` daemon on :8888 is **shared across spaces** (`monday` **and** `sunday`).
  Never `kill` the daemon to stop Monday — stop the *space* instead (`evva swarm stop monday`).

---

## 2. Prerequisites (one-time)

1. **Docker** running (for PostgreSQL).
2. **Python 3.14 venv with deps** — this is the #1 source of boot failures, so use `requirements.txt`:
   ```bash
   cd engine
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
   `requirements.txt` pins `psycopg[binary]` (bundles libpq) so the store imports with no system libpq.
3. **macOS only — OpenMP for LightGBM**: `brew install libomp` (needed before training the GBDT).
4. **`engine/.env`** — copy from `.env.example` and set:
   - `FINMIND_TOKEN=…` — **required** for real TW prices + chips (free tier 402s on a wide backfill).
   - `DATABASE_URL=postgresql://monday:monday@127.0.0.1:5432/monday` — matches the compose default.
   - `EVVA_WEBHOOK_URL=http://127.0.0.1:8888/api/swarm/monday/event` — engine → swarm callbacks.
5. **evva CLI** on `PATH` (`which evva` → `~/go/bin/evva`).

---

## 3. Cold start (full launch)

Run from the repo root unless noted. Order matters: **DB → engine → swarm.**

```bash
# 1. PostgreSQL
cd engine
docker compose up -d
#    wait for healthy + confirm the host port is actually published:
docker inspect monday-postgres --format '{{.State.Health.Status}}'   # → healthy
nc -z localhost 5432 && echo "5432 open"                             # → 5432 open

# 2. Engine (:7790, serves the dashboard at /). Foreground; use a separate shell or `&`.
.venv/bin/python -m monday
#    health check (new shell):
curl -s localhost:7790/health        # → {"ok":true,"service":"monday-engine",...}

# 3. evva swarm (agents). The daemon is shared; start it once, then run the monday space.
evva service start                   # no-op if already running (:8888)
cd ..                                # repo root (where evva-swarm.yml lives)
evva swarm run monday                # restart the existing space ...
# evva swarm .                       # ... or register+start fresh from ./evva-swarm.yml
evva swarm ls                        # confirm: monday → running, N members
```

After launch the loop is **human-triggered (2.0)**: the User wakes morgan once each morning and gets a
6-section report. morgan's primary trigger is the `round_requested` webhook; a **safety-net cron (08:45
Mon–Fri)** backstops a missed wake. Pre-stage crons warm the cache (podcast-listener 17:00, data-engineer
21:15 evening TW prepare). Trigger today's round by clicking **"▶ Run today's round"** in the dashboard, or:

```bash
curl -X POST 'localhost:7790/api/system/run-round'      # wakes morgan; idempotent (409 if already today)
```

morgan then orchestrates the whole DAG: data-engineer prepare + `macro/refresh` → macro/micro-analyst →
定調 + `signals/rescope` → quant → analyst overlay (candidates + holdings) → sizing + holdings review →
risk gate → **propose fills to the User** → 6-section report. **The swarm never places orders** — morgan
proposes, the User confirms (invariant 11). To prepare signals by hand without a full round:

```bash
curl -X POST 'localhost:7790/api/system/run-pipeline?source=finmind&model=gbdt&finalize=false'
```

### Production model (optional but recommended)
A fresh DB ships with only the `baseline-0` momentum ranker. To put the GBDT into production:
```bash
cd engine
.venv/bin/python -m monday.models.train --source finmind --days 400   # registers a GBDT version
#   (fires hundreds of FinMind calls; resumable via cache if it 402s mid-run — just re-run)
```

---

## 4. Health checks

```bash
curl -s localhost:7790/health                       # engine liveness
curl -s localhost:7790/api/recommendations/today    # latest book (as_of_date, model_version, regime)
curl -s localhost:7790/api/models                    # registry — is a gbdt-* version present?
curl -s localhost:7790/api/portfolio                 # open paper positions
curl -s localhost:7790/api/calibration               # IC / hit-rate / reliability curve
curl -s 'localhost:7790/api/journal?page_size=5'     # recent agent shift notes
evva swarm ls                                        # monday space running? member count?
docker compose -f engine/docker-compose.yml ps       # postgres healthy?
```

---

## 5. Stop / kill

```bash
# Engine — find and stop the python -m monday process:
pkill -f 'python -m monday'          # or: lsof -nP -iTCP:7790 -sTCP:LISTEN  then  kill <PID>

# Swarm — stop the SPACE, never the shared daemon:
evva swarm stop monday               # keeps the space; `evva swarm run monday` brings it back

# PostgreSQL — stop the container, keep the data:
docker compose -f engine/docker-compose.yml down
```

> Do **NOT** `kill` the `evva service` daemon (PID of `evva service start`) — it also hosts the
> `sunday` space. Use `evva swarm stop <ref>` to stop a single space.

---

## 6. Reset to a clean slate

Pick the depth you need. The deeper ones are **destructive** — they drop real recorded history
(the calibration ledger is the lab's whole point, so reset deliberately).

```bash
# (a) Processes only — stop engine + space, keep all data:
pkill -f 'python -m monday'
evva swarm stop monday

# (b) Wipe the database (drops recs / portfolio / ledger / journal / model registry):
cd engine
docker compose down -v               # -v removes the data volume
docker compose up -d                 # next boot re-creates an empty schema
#   re-train + re-run to repopulate (see §3).

# (c) Wipe the swarm (fresh ledger + cleared agent context, same id/URL):
evva swarm reset monday              # then: evva swarm run monday
```

Full clean re-test = (b) + (c), then cold-start §3.

---

## 7. Re-test flow (typical)

```bash
cd engine
.venv/bin/pip install -r requirements.txt          # ensure deps current
../scripts/run-tests.sh                             # pytest incl. pipeline smoke (falls back to unittest)
../scripts/smoke.sh                                 # full chain on a throwaway DB, leaves no artifacts
# one real end-to-end day, stage-by-stage summary:
.venv/bin/python -m monday.pipeline --source finmind --model gbdt --days 200
# 2.0: dry-run the engine half of one manual round against a running engine (PAPER book, safe/idempotent):
BASE=http://127.0.0.1:7790 ../scripts/dryrun-round.sh
```

---

## 8. Troubleshooting (gotchas seen in the wild)

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError: no pq wrapper available … libpq library not found` on engine boot | plain `psycopg` installed without libpq | `.venv/bin/pip install 'psycopg[binary]'` (it's in `requirements.txt`) |
| `[Errno 48] address already in use … 7790` | an engine is **already running** | `lsof -nP -iTCP:7790 -sTCP:LISTEN` → `kill` it, or just use the running one |
| Container `healthy` but `nc -z localhost 5432` fails | stale container with the host port unpublished | `cd engine && docker compose down && docker compose up -d` |
| `No module named 'pandas'` / GBDT training crashes | ML deps missing | `.venv/bin/pip install -r requirements.txt` |
| LightGBM import/runtime error on macOS | missing OpenMP | `brew install libomp` |
| FinMind backfill stops with HTTP 402 | free-tier rate limit | set `FINMIND_TOKEN` in `engine/.env`; re-run — the ingest cache makes it resumable |
| Engine logs `evva webhook reachable` but agents idle | space stopped | `evva swarm run monday` (check `evva swarm ls`) |

---

## 9. The 2.0 manual round, the real book & the cutover gate (D1)

**The round** (human-triggered): `POST /api/system/run-round` (or the dashboard button) wakes morgan, who
runs the DAG and posts a 6-section report (`GET /api/reports/daily`). It is idempotent — one wake per
trading day (409 on a repeat; `?force=true` overrides). If the swarm is down at trigger time, morgan's
safety-net cron (08:45) backstops it.

**The book** (`/api/book`, the User's managed positions — separate from the 1.0 `paper_positions` sim):

```bash
curl -s localhost:7790/api/book                         # holdings + exposure (gross/net/cash/NAV/by-sector)
curl -s localhost:7790/api/book/actions                 # hold/add/trim/exit log
curl -s localhost:7790/api/macro                        # world-index read (top-down 定調 input)
curl -s localhost:7790/api/calibration/macro            # macro-call accuracy (settled vs ^TWII)
curl -s localhost:7790/api/calibration/positions        # position-management value-add
# a fill is ALWAYS the User's decision — morgan proposes, you confirm; the engine only records it:
curl -X POST localhost:7790/api/book/fill -H 'content-type: application/json' \
  -d '{"book":"paper","symbol":"2330","side":"buy","qty":1000,"price":1000,"fill_key":"<unique>"}'
```

**`book_mode`** (config) stays `paper` during the dry-run; the dashboard/report watermark and the
`/api/book` `book` field show which book is live. **The swarm never connects to a broker — it never places
an order** (invariant 11); `/api/book/fill` is bookkeeping that the User confirms.

### Cutover gate — paper → real (decision 3, ADR 0006)

Run `scripts/dryrun-round.sh` (engine side) + the live swarm for **≥ N consecutive trading days** (set N,
e.g. 5–10) and confirm the **12-point checklist** holds each day:

1. `run-round` wakes morgan once (idempotent); dashboard button works.
2. **GATE 1**: a degraded-data day ships a **holdings-only** report with the honest "今日不發新標的" note.
3. macro/micro briefs reach morgan; a `macro_call` is recorded (`GET /api/calibration/macro`).
4. `signals/rescope` → focus-sector candidates **+ all holdings scored** (full-pool ranking preserved).
5. a-tech/a-chips/a-catalyst cover candidates **and holdings**, emitting the A5 review flags.
6. `book/review` returns hold/add/trim/exit per lot; `book/sizing` returns sane sizes; **holdings review runs on a no-new-ideas day**.
7. **GATE 2**: risk-monitor blocks an over-concentrated/over-sized book; morgan revises and re-checks.
8. fills are **proposed for User confirmation** (no auto-order, invariant 11); paper book + ledger update.
9. a 6-section report posts, carries the **disclaimer**, renders on dashboard + Telegram.
10. daily reconcile runs; macro calls settle; the Friday scorecard shows macro-call + position-mgmt dims.
11. **safety-net**: with the swarm down at trigger time, the backstop still produces something; no double-run.
12. quality bar: `./scripts/run-tests.sh` green, `vue-tsc` clean, `/health` ok, no invariant regressions.

**Flip to real only when** the checklist passes ≥ N consecutive days, report quality is User-approved,
position-management looks sound in hindsight on paper, calibration is accumulating, and the per-round
budget is acceptable. Set `BOOK_MODE=real` in `engine/.env`, restart the engine, record a **cutover ADR**.
**Until then, no real money** (invariant 11). The 1.0 `paper_positions`/`finalize` path stays intact in
parallel and is retired only after the real book is trusted.

---

## 10. Quick reference

| What | Where |
|---|---|
| Engine entrypoint | `engine/.venv/bin/python -m monday` (uvicorn, host/port from `config.py`) |
| Full pipeline (CLI) | `python -m monday.pipeline [--source finmind|twse] [--model gbdt] [--days N]` |
| Trigger a 2.0 round | `POST /api/system/run-round` (or the dashboard "▶ Run today's round" button) |
| Dry-run a round (engine) | `BASE=… scripts/dryrun-round.sh` (paper book, safe/idempotent) |
| Cutover gate | RUNBOOK §9 (≥N clean days → `BOOK_MODE=real` + cutover ADR; invariant 11) |
| Train GBDT | `python -m monday.models.train --source finmind --days 400` |
| API manual | `GET /manual` · routers in `engine/monday/routers/` |
| Deps | `engine/requirements.txt` (run/test) · `engine/pyproject.toml` (packaging) |
| DB | `engine/docker-compose.yml` (postgres:16, volume `monday-pgdata`) |
| Swarm manifest | `evva-swarm.yml` (leader `morgan` + workers) |
