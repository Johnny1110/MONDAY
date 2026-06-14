# Monday — Claude Code Development Guide

> **Status (2026-06-13): Phase 0, platform not yet started.** The repo currently holds only the whitepaper.
> Authoritative spec = **[docs/whitepaper.md](docs/whitepaper.md) (v0.1, in Chinese)** — all design detail,
> `§` numbering, and the DDL/JSON contracts live there; this file is the **distilled working guide** loaded
> every session (invariants + structure + disciplines). **All names are placeholders** (project Monday /
> engine Monday engine / leader morgan), to be settled once the User signs off on whitepaper §11. Before
> starting work, read whitepaper §0.1 (the four locked architecture decisions) and §11 (open decisions).

## What we're building

A **Taiwan-stock daily stock-picking + self-regression-calibration laboratory.** It's the sibling of
[Sunday](../sunday/CLAUDE.md), inheriting its engineering DNA (stateless platform holds the keys, agents
speak only HTTP, webhook wake-ups, cron as safety net, centralized decision authority), but the asset class
is **TW equities** and the output is **≤20 daily swing-trade ideas with a ≤1-month holding window + a paper
portfolio + a daily mark-to-market calibration ledger**.

Two planes, two HTTP boundaries:

```
swarm (evva :8888 · Go · .vero)            Monday engine (Python · :7790 · FastAPI)
  morgan(leader=CIO/PM) + 11 workers
        │  http_request ─────────────────►  /api/*  (all token-free; full contract at GET /manual)
        ◄──────── webhook ───────────────  events.post (calibration_drift / portfolio_drawdown
                                            / pipeline_failed / factor_decay …)
                                            └── data-source adapters (keys live only in this layer)
```

**Prediction engine = quant-led, LLM-assist**: ML models do cross-sectional ranking / probability / expected
return; the LLM only does the qualitative overlay (themes / institutional flow / landmines / narrative) and
veto. Output is **paper-portfolio only — no real money, ever.**

## Inviolable invariants (whitepaper §1; confirm each before starting work)

1. **Data = read-only external sources (keys held by the platform); output = platform-internal state.**
   Agents only ever use generic `http_request` against Monday engine, and **never see any data-source API
   key / CMoney credentials.**
2. **All Monday engine APIs are token-free.** The platform holds the keys; agents hold only HTTP.
3. **Any list returning bulk data is paginated**, using the unified envelope `{items,page,page_size,total,has_more}`
   (reuse Sunday's `pagination`).
4. **API prefixes split by module**, one `routers/` module each: `/api/universe` `prices` `factors`
   `features` `models` `signals` `recommendations` `portfolio` `ledger` `calibration` `news` `sentiment`
   `memory` `journal` `reports` `system` `admin` (admin is operator-only, never advertised to agents).
5. **No Postgres/Redis.** Transactional persistent state = **sqlite** (recommendations / paper_portfolio /
   ledger / calibration / model_registry / memory / journal / reports / kv); large feature/price tables =
   **parquet** (read-only, analysis-friendly). The sqlite wrapper reuses **RLock write-lock + WAL/busy_timeout**
   (Sunday's `store.py` pattern — multi-threaded writes won't deadlock).
6. **Pure logic is stdlib-only and unit-testable** (factor calc / indicators / pagination / calibration math
   IC·calibration·hit-rate·attribution / signal rules / mark-to-market). **Heavy deps (pandas/numpy/lightgbm/
   fastapi) are lazily imported** — never at module top level.
7. **Calibration triggers use webhook + cron safety net — not polling.** The platform detects "moments worth
   an agent's attention" (drawdown breach / calibration drift / pipeline failure / factor IC turning negative)
   → webhook wakes the relevant agent; cron only backstops a missed webhook.
8. **Two outbound channels, both fire-and-forget, never raise, keys only on the engine side**: (a) swarm
   webhook (agent-facing: engine → evva, payload `{title,body,data,to}` carrying its own `suggested_action`);
   (b) User channel (Telegram + dashboard: daily ideas / review summaries / major alerts; no-op if Telegram
   keys are unset).

## Platform vs swarm: what goes where (whitepaper §2 criterion)

- **Into the platform (Monday engine, Python, deterministic, testable, holds keys)**: scraping / cleaning /
  split-adjustment / point-in-time alignment / quality gates, feature-store computation, model training and
  daily inference, paper-portfolio mark-to-market, calibration metrics, webhook/Telegram/dashboard.
- **Into the swarm (evva agents, judgment, narrative, orchestration)**: whether to trust a model ranking
  today, whether a theme is fresh or already-priced-in, catching landmines the model can't see, writing ideas
  into human-readable rationale, deciding at review time to retrain / swap factors / redirect / reorganize,
  conversing with the User.
- **Criterion**: anything where "same input must yield same output, and it needs a unit test" → platform;
  anything needing "judgment, trade-offs, narrative, external communication" → swarm. The model **training
  scripts** are authored by the quant-family agents and run via the platform's repl/bash, but the **training
  flow and artifacts (model registry) land in the platform**, not in agent conversation.

## Three cardinal disciplines (Monday's scientific lifeline)

1. **The LLM never predicts stock prices directly** (locked in §0.1). The model owns breadth and objective
   ranking; the LLM only overlays/vetoes within the model's candidate set. If it spots a major catalyst the
   model missed, it files a `task_propose` for an audit trail — it does not conjure tips out of thin air.
2. **No ledger, no calibration (§6).** Every idea is **fully recorded at birth** (model_version /
   feature_snapshot_id / regime / predicted_return / prob_tp / TP·SL / factors / analysts / rationale) →
   daily mark-to-market → settlement at exit. Calibration is the core, not an afterthought. The
   regression-optimization loop is **explicitly not a fixed cycle**: a layered review SOP (daily/weekly/
   monthly/quarterly) plus event-driven off-cycle adjustments.
3. **⚠️ Look-ahead bias is the #1 threat (§4.2).** The free sources have no paid point-in-time data. The cure:
   **from Day 1, every post-close the platform archives the raw data visible that day, as-is (append-only
   parquet, stamped `as_of`)**; calibration and post-launch walk-forward use only the PIT view rebuilt from
   snapshots. Cold-start historical backtests are explicitly **downgraded to "hypotheses"**; real validation
   comes from the post-launch PIT paper portfolio. The 1-month holding window overlaps sample labels →
   **purged + embargo** time-series CV, or IC inflates and the live model collapses.

## Project structure (P0 complete: full chain + real FinMind/TWSE ingest + Vue/Vite dashboard)

```
monday/
├── CLAUDE.md                 this file (loaded every session)
├── docs/whitepaper.md        authoritative spec (v0.1); docs/PRD/ docs/BUG/ hold tickets
├── evva-swarm.yml            swarm manifest (whitepaper appendix A draft)        ← to build
├── agents/                   evva agents                                          ← to build
│   ├── main/morgan/                                  leader (sole decider)
│   └── sub/{data-engineer,quant,quant-researcher,a-tech,a-chips,
│            a-catalyst,strategy-researcher,risk-monitor,
│            reviewer-calibrator,watchdog,evva}/   # evva = resident-engineer persona (§7.1 lab-engineer)
│       each holds system_prompt.md (persona only) + profile.yml (model/effort/schedule)
│       + optional tools/active.yml (list only generic tools; collab tools are auto-injected, never relisted)
└── engine/monday/            Python platform (FastAPI)                            ← to build
    ├── app.py                assembly (lifespan + router mounts + scheduler start/stop)
    ├── config.py             pydantic-settings (data-source keys live only here)
    ├── store.py              sqlite + RLock write-lock + WAL
    ├── pagination.py         unified pagination envelope
    ├── ingest/               scraper adapters (TWSE/TPEx/FinMind/CMoney/Yahoo/Trends/news) + rate-limit + cache
    ├── clean.py              cleaning / split-adjustment / PIT alignment / quality gates
    ├── snapshot.py           daily PIT snapshot (append-only parquet, stamped as_of) ← look-ahead cure
    ├── featurestore/         factor computation (momentum/flow/fundamentals/events/sentiment/regime), pure → parquet
    ├── models/               model registry + training scripts + daily inference (lightgbm lazily imported)
    ├── portfolio.py          paper portfolio + ledger daily mark-to-market
    ├── calibration.py        IC / hit-rate / calibration curve / attribution (pure math, testable)
    ├── triggers.py           drawdown/drift/failure/factor-decay detection → events.post
    ├── events.py             evva webhook builders + post (stdlib urllib)
    ├── telegram.py           User-facing push (no-op if unset)
    ├── routers/              one file per module (see invariant 4)
    ├── manual.md             agent API manual (GET /manual)
    └── web/                  dashboard (daily 20 ideas / calibration scorecard / portfolio curve)
```

## Tech stack

- Engine: Python ≥ 3.11, FastAPI + uvicorn, stdlib `sqlite3`, **parquet** (pyarrow) for large tables.
- ML: LightGBM/XGBoost (GBDT is the workhorse: Ranker/Regressor/Classifier three heads), numpy/pandas, SHAP
  attribution; DL (LSTM/GRU/TFT) **must beat GBDT on walk-forward OOS IC before it joins the ensemble** —
  otherwise it does not ship (§5.2).
- Webhooks use stdlib urllib (no httpx); keep pure indicator/calibration math stdlib/numpy-testable.
- Frontend dashboard: mirror Sunday (Vite + Vue 3 + TS, build → `dist/` committed), self-served by the engine.

## Relationship to evva / Sunday (important)

- **evva** is the swarm runtime, a standalone Go project at [`../evva`](../evva). This project is a **consumer**
  of an evva swarm: agents drive Monday engine using only generic `http_request` + the `/manual` doc. **We do
  not change evva from here**; if the swarm lacks a capability, file a refine-plan in evva. This is exactly the
  multi-agent completeness oracle thesis (continued from Sunday).
- **Sunday** ([`../sunday`](../sunday)) is the proven engineering blueprint — sqlite RLock store, pagination
  envelope, fire-and-forget events/telegram, agents-directory conventions, the `/manual` contract. **Copy what
  you can copy; don't reinvent.**
- **Trust-model boundary (honest version)**: "only morgan decides" is **prompt discipline, not a technical
  enforcement** (APIs are token-free; any worker can technically reach them). That boundary is acceptable
  because **this is a paper portfolio, no real money** (continuing Sunday's testnet-fake-money logic).

## Conventions

- Data-source keys (CMoney/FinMind…) go in `engine/.env`, **never committed** (already gitignored).
- Commits use conventional prefixes (`feat`/`fix`/`chore`/`docs`/`refactor`/`test`).
- Tests sit next to the code (`tests/test_*.py`); pure logic runs anywhere, scrapers/ML/dashboard verify on host.
- Every strategy/org adjustment = one **ADR** (decision, rationale, expected effect, when to revisit). **Over-tuning
  on the calibration set is itself treated as an error** (§6.4) — explicitly logging "no change this week" is a
  valid output.
- **evva SOP** (resident engineer, the §7.1 lab-engineer role): take ticket (docs/PRD/) → confirm no invariant is violated →
  implement → tests green → commit → deploy and verify health → report back (ticket # + commit hash + test
  evidence). Does not pick stocks, does not touch the strategy constitution.

## Status / next steps (whitepaper §10 roadmap)

- ✅ Whitepaper v0.1 (`docs/whitepaper.md`); the four architecture decisions are locked (§0.1).
- ⬜ **Awaiting User sign-off on §11** (naming / cold-start history depth / universe scope / long-only vs
  short / repo location / Telegram).
- ✅ **P0 platform foundation — COMPLETE.** `engine/monday/` runs the full chain (ingest → clean +
  universe gate → PIT snapshot → featurestore → empty baseline model → ≤20 recommendations →
  mark-to-market) on **synthetic OR real free-core data** — `--source finmind|twse` pulls live TW prices
  through a cached, rate-limited, retrying ingest layer; idempotent re-runs. 17 token-free routers +
  `/manual`; sqlite (appendix B schema) + parquet. **Vue 3 + TS dashboard** (Today / Signals / Portfolio /
  Calibration / Ledger / Reports / System / Manual; black-gold, SVG equity curve + calibration reliability
  diagram) built to `web/dist/` (committed) and served by FastAPI at `/`. `evva-swarm.yml` skeleton +
  `morgan` + `evva` (resident engineer). **34 unit tests green** + `vue-tsc` clean. Run: `python -m monday`
  (:7790, dashboard at `/`), `python -m monday.pipeline [--source finmind]`, `./scripts/run-tests.sh`,
  `./scripts/smoke.sh`; details in `engine/README.md`.
- 🟡 **P1 MVP loop** (in progress on branch `p1-mvp`): ✅ cold-start **GBDT** — LightGBM 3-head in
  `models/{gbdt,train,cv,labels}.py`, purged walk-forward CV reports honest OOS rank IC (momentum-only
  cold start ≈ 0 — the discipline working), registered with provenance; `--model gbdt` +
  `POST /api/models/train`. ✅ **6-worker roster built + activated** in `evva-swarm.yml` (data-engineer /
  quant / a-chips / a-catalyst / reviewer-calibrator / watchdog, + leader `morgan` nightly finalize +
  `evva`), each domain-tools-only with §8 cron cadence. ✅ **human-in-the-loop decomposition** —
  `run-pipeline?finalize=false` prepares signals only, `POST /api/recommendations/finalize` lets morgan
  compose the ≤20 book from the analyst overlay (§5.6/§5.7), `POST /api/ledger/reconcile` is
  reviewer-calibrator's daily mark. **44 tests green.** ⬜ Remaining: the ≥4-week live-run gate (§10) —
  operational (launch the swarm with `evva swarm .` and let it run).
- 🟡 **P2 depth** (branch `p2-depth`): ✅ **regime classifier** (§5.3, `regime.py`) — rule-based label
  (bull_trend / choppy / risk_off / high_vol) from index trend/breadth/vol, stamped on every idea so
  per-regime attribution is real. ✅ **portfolio risk gate** (§5.7, `risk.py`) — sector-concentration /
  name-count / liquidity checks (FinMind sector data); advisory on morgan's `/finalize` +
  `GET /api/portfolio/risk` + a dashboard panel. ⬜ Next: regime-aware ensemble, monthly retrain +
  factor-decay→retire ADR. New agents (a-tech / risk-monitor / quant-researcher) get activated
  after the P1 live run shows where judgment is most lacking (§7.2 data-driven staging).
- ⬜ **P3 optimization** (+strategy-researcher, quarterly org review, event-driven adjustments fully on).

> **Staffing philosophy**: don't hire the full roster at once (a year of 24/7 tokens is a real cost). Prove the
> **closed loop** with a minimal roster first, then let the calibration ledger reveal "where judgment is most
> lacking" to differentiate roles — **letting the org evolve data-driven** is itself an expression of §6.
