# ADR 0002 — Live pipeline defaults + triage of BUG_01 (Day-2)

- **Status**: Accepted
- **Date**: 2026-06-16
- **Author**: evva (resident engineer), at the User's direction
- **Context source**: [`docs/BUG/BUG_01.md`](../BUG/BUG_01.md) (morgan, Day-2 v2.1) — 7 new + 5 carried obstacles.

## Context

morgan's Day-2 report lists 12 obstacles. Each was triaged **against the engine source + live data**
(direct FinMind probe, the ledger, the marks). The headline finding: several "Critical" items are
**not engine bugs** — they are operational state (a stopped swarm space, an operator `down -v`), evva-
runtime concerns (out of scope here), or **measurement mistakes** (assuming ±8% exits when the system
moved to ATR-scaled exits). Three are genuine engine defaults worth changing.

## Decision

### Fixed in the engine (this ADR)

1. **B1 — `mark_forward` live default 1 → 0** (`routers/system.py` `/run-pipeline`).
   `mark_forward=N` reserves the last N trading days as "future" to immediately mark-to-market against —
   correct for **backtests**, wrong for **live post-close picking**, where it made `as_of = dates[-2]`
   (e.g. 2026-06-15) even though the latest close (6/16, FinMind close=2400 confirmed) was available.
   The live API now defaults to `0` (as_of = latest close); the CLI (`python -m monday.pipeline`) keeps
   `1` for backtests. Forward marking in live is the **next day's** job (reviewer-calibrator's reconcile).

2. **B15 — `post` default false → true** (`routers/system.py` `/run-pipeline`).
   `post=true` fires the `pipeline_complete` webhook so the swarm leader wakes on completion instead of
   polling. The mechanism always worked (`tasks.py:_fire_complete`, independent of `finalize`); only the
   default was wrong for swarm mode. A `log.warning` now fires on any `post=false` run. Tests pass
   `post=false` explicitly for isolation.

3. **B17 — sector concentration default 5 → 6** (`config.py` `max_per_sector`).
   The constitution allows ≤30% of 20 names = **6** per sector; the engine flagged at 5 (25%). Aligned;
   still env-overridable via `MAX_PER_SECTOR`.

### Triaged as NOT engine bugs (no code change)

| ID | morgan's claim | Verdict | Evidence |
|----|----------------|---------|----------|
| **B3/as_of** | as_of stuck at 6/15 | **= B1 symptom** | not a data gap — 6/16 exists; `mark_forward=1` held it back |
| **B14** | morgan 21:15 cron didn't fire | **Operational + evva** | the `monday` swarm space was **stopped** at 21:15 (started 22:43); a stopped space has no scheduler. evva cron reliability is out of scope (we don't modify evva). Engine-side safety-net → PRD (see below) |
| **B16** | a-chips self-started | **evva (out of scope)** | swarm message dispatch — file in evva |
| **B18** | DB not persisting Day-1 | **Operational, not a bug** | Day-1 data WAS persisted to Postgres; it was wiped by an operator `docker compose down -v` (clean-slate reset). Named volume `monday-pgdata` persists across `down`. `/api/system/status` already exposes row counts for visibility |
| **B19** | entry price ±1-3pt cross-table mismatch | **Reconstruction artifact** | `entry_price` is always the as_of close (`entry_ref_price`), consistent. Marks store `mtm_return` **net of** `round_trip_cost_pct=0.6%`; reconstructing entry from net mtm is off by ≈ entry×0.6% (≈1-3pt on a 200-600 stock). Ledger is correct |
| **B20** | TP/SL didn't trigger (7/20 crossed ±8%) | **Misdiagnosis** | exits are **ATR-scaled** (§5.5): real bands are TP +20-28% / SL −13-15%, not ±8%. No name reached its real band (max mtm +9.4%). `tp_hit=0/sl_hit=0/settled=0` is correct; `days_held≥1` so settlement is enabled |
| **B5** | API lacks `universe_size` | **Already present** | `run-pipeline?universe_size=` exists; `null` → env default (intended) |
| **B10** | async pipeline / HTTP timeout | **Already implemented** | endpoint returns 202 + `task_id`, runs in a thread |
| **B11** | pipeline mutex on SQLite | **Obsolete** | store is Postgres (ADR 0001) + `acquire_pipeline_lock` single-flight |
| **B6** | factor homogeneity (all momentum) | **Expected** | cold-start baseline; resolved by training the GBDT (roadmap), not a bug |
| **B13** | finalized signals overwritten | **Guard exists** | `force`-gated B9/B13 guard preserves finalized days; per-date archive at `/api/signals/{date}` |

### Deferred to a PRD (durable new capability)

- **B14 engine-side cron safety-net** — invariant 7 ("cron backstops a missed webhook") is currently
  implemented **only** swarm-side; the engine has no scheduler. A platform-level daily backstop (always-on,
  triggers the pipeline with `post=true` if the day hasn't run) is the robust fix. → `docs/PRD/`.

## Consequences

- Live daily runs now anchor on the latest close and auto-notify the leader — the everyday path is correct
  by default; backtests must pass `--mark-forward 1` explicitly.
- morgan's SOP trigger (which omits `mark_forward` and sets `post=true`) now gets the right behavior for free.
- The "no-bug" items free the team from chasing phantom fixes; B19/B20 in particular were measurement errors.
- Changes are config/default-level and covered by the existing suite (114 passed). Engine must be **restarted**
  to load them.

## When to revisit

- If a backtest path starts using the live API default by mistake (watch for as_of = latest on historical runs).
- When the B14 safety-net PRD lands (then invariant 7 is fully realized platform-side).
