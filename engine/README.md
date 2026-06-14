# Monday engine (P0 scaffold)

The platform plane: a stateless TW-equity research platform an evva swarm drives over token-free
HTTP. See [`../CLAUDE.md`](../CLAUDE.md) for invariants and [`../docs/whitepaper.md`](../docs/whitepaper.md)
for the spec. P0 runs the **full chain end to end on synthetic data** — not investable.

## Layout
```
monday/                 package
├── config.py           settings (keys engine-side)        store.py    sqlite + RLock + WAL
├── pagination.py       list envelope                      parquetio.py PIT/feature parquet (lazy pyarrow)
├── ingest/           synthetic + twse + finmind adapters  clean.py    quality gate + liquidity filter
│                      (base: cache/rate-limit/retry; parse: ROC dates/numerics; get_source registry)
├── snapshot.py         daily PIT snapshot (look-ahead cure) featurestore/ factors (pure) + build
├── models/             baseline (empty) + gbdt (LightGBM 3-head) + train/cv/labels  signals.py
├── portfolio.py        paper portfolio + mark-to-market   calibration.py IC / hit / curve / attribution
├── triggers.py         drawdown/drift → events            events.py / telegram.py  outbound (no-op safe)
├── pipeline.py         the full chain (exit gate)         routers/    one file per /api prefix
├── app.py / __main__.py FastAPI assembly + entrypoint     manual.md   GET /manual contract
└── tests/              pure-logic suite + pipeline smoke
```

## Setup
```bash
python3 -m venv --system-site-packages .venv     # numpy from system; rest installed below
.venv/bin/pip install fastapi uvicorn pydantic-settings pyarrow pytest
```

## Run
```bash
# one full chain offline (synthetic) — the P0 exit gate, prints a stage-by-stage summary:
.venv/bin/python -m monday.pipeline --days 180

# real free-core data — FinMind backfill (long history) or TWSE STOCK_DAY (results cached under data/cache):
.venv/bin/python -m monday.pipeline --source finmind --days 200
.venv/bin/python -m monday.pipeline --source twse --days 120

# train + register the cold-start GBDT, then run the chain through it (reports OOS rank IC):
.venv/bin/pip install lightgbm        # macOS also needs OpenMP: `brew install libomp`
.venv/bin/python -m monday.models.train --source finmind --days 400
.venv/bin/python -m monday.pipeline --source finmind --model gbdt --days 200
#   The universe is the top-N listed names by liquidity (config `universe_size`). A WIDE backfill
#   fires hundreds of FinMind calls — set FINMIND_TOKEN in .env (the free tier 402s past ~hundreds/hr).

# the HTTP service (:7790):
.venv/bin/python -m monday
curl localhost:7790/health
curl -X POST 'localhost:7790/api/system/run-pipeline'   # produce a day via the API
curl localhost:7790/api/recommendations/today
curl localhost:7790/api/calibration
```

## Dashboard (web/)

Vue 3 + TS + Vite, served by FastAPI at `/` (and `/ui` assets). The built output `web/dist/` is
**committed**, so the engine runs with no Node step; rebuild only when the UI changes.

```bash
cd monday/web
npm install
npm run build       # → dist/ (committed); FastAPI serves it
npm run dev         # hot-reload dev server (proxies /api → :7790)
npm run typecheck   # vue-tsc --noEmit
```

Views: Today (ideas) · Signals · Portfolio (+ equity curve) · Calibration (reliability diagram +
attribution) · Ledger · Reports · System (run the pipeline, pick source) · Manual.

## Test
```bash
../scripts/run-tests.sh     # venv pytest (incl. pipeline smoke); falls back to stdlib unittest
../scripts/smoke.sh         # full chain on a throwaway db (leaves no artifacts)
```

State (`monday.db*`, `data/`) is regenerated and gitignored. Heavy deps (pyarrow / future
lightgbm) are lazily imported so the pure-logic suite runs on a bare interpreter.
