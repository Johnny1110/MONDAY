# Monday

> A Taiwan-stock **daily stock-picking + self-calibration laboratory**.
> **Paper portfolio only — research opinion, never investment advice.**

Monday produces **≤20 daily swing-trade ideas** (≤1-month holding window), opens them in a **paper
portfolio**, and marks them to market every day into a **calibration ledger** that scores how well the
predictions actually played out. It is **quant-led, LLM-assist**: machine-learning models do the
objective cross-sectional ranking; the LLM agents only add the qualitative overlay (themes, institutional
flow, landmines, narrative) and a veto. The whole point is the feedback loop — *no ledger, no calibration.*

It is the sibling of [Sunday](../sunday), inheriting its engineering DNA (a stateless platform holds the
keys, agents speak only HTTP, webhook wake-ups, cron as a safety net, one central decision authority) —
but the asset class is **TW equities**.

> Names (`Monday` / `Monday engine` / leader `morgan`) are placeholders pending whitepaper §11 sign-off.

## Architecture — two planes, two HTTP boundaries

```
  evva swarm  (Go · :8888 · .vero)                Monday engine  (Python · :7790 · FastAPI)
  ┌───────────────────────────────┐               ┌──────────────────────────────────────────┐
  │ morgan  (leader = CIO / PM)    │  http_request │  /api/*   token-free; full contract at     │
  │  + 11 workers (data-engineer,  │ ────────────► │           GET /manual                       │
  │  quant, a-tech, a-chips,       │               │  PostgreSQL (transactional) + parquet (big) │
  │  a-catalyst, risk-monitor,     │ ◄──────────── │  data-source adapters — keys live ONLY here  │
  │  reviewer-calibrator, …)       │   webhook     │  (calibration_drift / portfolio_drawdown /  │
  └───────────────────────────────┘ events.post   │   pipeline_failed / factor_decay …)         │
                                                   └──────────────────────────────────────────┘
```

- **The engine** (this repo, `engine/`) is deterministic, testable, and holds every credential. It does
  the scraping, cleaning, point-in-time alignment, feature store, model training/inference, paper
  mark-to-market, calibration math, and the webhook/Telegram/dashboard outputs.
- **The swarm** (an [evva](../evva) workstation, driven via `evva-swarm.yml`) does the judgment:
  whether to trust today's ranking, whether a theme is already priced-in, catching landmines, writing
  human-readable rationale, and — at review time — deciding to retrain / swap factors / reorganize.
- Agents only ever use generic `http_request` against token-free APIs; they **never see a data-source
  key**. "Only morgan decides" is prompt discipline, not enforcement — acceptable because it is a **paper
  portfolio, no real money**.

## The three disciplines (why Monday is a *lab*, not a tip sheet)

1. **The LLM never predicts prices directly.** The model owns breadth + objective ranking; the LLM only
   overlays / vetoes within the model's candidate set.
2. **No ledger, no calibration.** Every idea is recorded *at birth* (model version, feature snapshot,
   regime, predicted return, TP/SL, factors, rationale) → daily mark-to-market → settlement at exit.
3. **Look-ahead bias is the #1 threat.** Free data has no paid point-in-time history, so every post-close
   the platform archives the raw data visible *that day* (append-only parquet, stamped `as_of`); the
   1-month label overlap is handled with **purged + embargo** time-series CV. Cold-start backtests are
   explicitly downgraded to "hypotheses" — real validation comes from the live PIT paper portfolio.

## Quickstart

Full launch / stop / reset / troubleshooting lives in **[RUNBOOK.md](RUNBOOK.md)**. The short path:

```bash
cd engine
docker compose up -d                                   # 1. PostgreSQL (:5432)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # 2. deps (psycopg[binary], lightgbm, …)
# 3. set FINMIND_TOKEN in engine/.env  (cp .env.example .env)
.venv/bin/python -m monday                             # 4. engine :7790 — dashboard at /
cd .. && evva service start && evva swarm run monday   # 5. the agent swarm :8888
```

Produce a day by hand instead of waiting for morgan's nightly run:

```bash
curl -X POST 'localhost:7790/api/system/run-pipeline?source=finmind&model=gbdt&finalize=false'
curl localhost:7790/api/recommendations/today
```

## Repository layout

| Path | What |
|------|------|
| `engine/`          | Python platform — FastAPI, ingest, feature store, models, portfolio, calibration ([engine/README.md](engine/README.md)) |
| `engine/monday/web/` | Vue 3 + TS dashboard (Today / Signals / Portfolio / Calibration / Ledger / Reports), served at `/` |
| `agents/`          | evva agent definitions — `main/morgan/` (leader) + `sub/*` (workers): persona + profile + tools |
| `evva-swarm.yml`   | swarm manifest (roster, schedules, models) |
| `docs/`            | spec + decision/ticket/bug records (see below) |

## Documentation map

| Doc | Purpose |
|-----|---------|
| [CLAUDE.md](CLAUDE.md)              | Working dev guide — the 8 invariants, structure, disciplines (loaded every session) |
| [RUNBOOK.md](RUNBOOK.md)            | Operations — launch / stop / reset / re-test / troubleshoot |
| [EVVA.md](EVVA.md)                  | Resident-engineer (`evva`) brief + engineering SOP |
| [docs/whitepaper.md](docs/whitepaper.md) | **Authoritative spec** (v0.1) — all `§` design detail (**in Chinese**) |
| [docs/adr/](docs/adr/)              | Architecture Decision Records (e.g. 0001 SQLite→Postgres, 0002 live pipeline defaults) |
| [docs/PRD/](docs/PRD/)              | Engineering tickets for `evva` to build |
| [docs/BUG/](docs/BUG/)              | Bug reports + triage |

## Tech stack

- **Engine**: Python ≥ 3.11, FastAPI + uvicorn, **PostgreSQL** (psycopg 3 + pool), **parquet** (pyarrow)
  for large feature/price tables. Pure indicator/calibration math is stdlib/numpy and unit-tested.
- **ML**: LightGBM 3-head (Ranker / Regressor / Classifier), scikit-learn, SHAP attribution. DL must beat
  GBDT on walk-forward OOS IC before it ships.
- **Dashboard**: Vite + Vue 3 + TS (built to `web/dist/`, served by FastAPI).
- **Swarm runtime**: [evva](../evva) (Go) — a separate project; this repo is only a *consumer* of it.

## Status

**PRODUCTION** (cutover 2026-06-15) — live on real FinMind data (prices + 法人/margin chips + sector),
TWSE fallback, full 11-worker roster active. Still **paper portfolio only** — the output is a research
hypothesis and a calibration record, **not investment advice**.

---

*Tests: `./scripts/run-tests.sh` (pytest + pipeline smoke) · `./scripts/smoke.sh` (full chain, throwaway DB).*
