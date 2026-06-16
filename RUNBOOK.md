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

After launch the loop is **agent-driven**: morgan's only cron is the nightly anchor at **21:15
Mon–Fri** (after chips/margin settle); it leads the pipeline and finalizes the ≤20-name book. To
produce a day by hand instead of waiting:

```bash
# prepare signals only (morgan still finalizes the book — respects the constitution):
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

## 9. Quick reference

| What | Where |
|---|---|
| Engine entrypoint | `engine/.venv/bin/python -m monday` (uvicorn, host/port from `config.py`) |
| Full pipeline (CLI) | `python -m monday.pipeline [--source finmind|twse] [--model gbdt] [--days N]` |
| Train GBDT | `python -m monday.models.train --source finmind --days 400` |
| API manual | `GET /manual` · routers in `engine/monday/routers/` |
| Deps | `engine/requirements.txt` (run/test) · `engine/pyproject.toml` (packaging) |
| DB | `engine/docker-compose.yml` (postgres:16, volume `monday-pgdata`) |
| Swarm manifest | `evva-swarm.yml` (leader `morgan` + workers) |
