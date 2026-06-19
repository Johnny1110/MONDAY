# ADR 0007 — Macro benchmark fallback: TWSE for `^TWII` when Yahoo is unavailable

- **Status**: Accepted
- **Date**: 2026-06-20
- **Author**: evva (resident engineer), at the User's direction
- **Context source**: D1 dry-run finding (`a076cb2`) — Yahoo returned HTTP 429 for every macro ticker, so
  `macro/refresh` produced an empty snapshot; PRD-002 decision 6 (macro data layer) + invariant 9 (PIT).

## Context

The 2.0 round is **top-down**: STEP 0 reads world indices to set the day's risk-on/off, and GATE-1
checks macro-data quality before the committee runs. The macro plane's only source was the Yahoo v8
chart API. Yahoo rate-limits aggressively — in the D1 dry-run **every** ticker came back HTTP 429, so
the snapshot was empty (`as_of=null, n=0`). The engine degraded correctly (it never crashed), but an
empty macro means:

- **GATE-1 sees a fully degraded-data day** → the round falls back to a holdings-only report, every time
  Yahoo throttles the host. The macro 定調 — the heart of 2.0 — is starved.
- **A9 macro-call scoring has no benchmark.** Macro calls are scored against `^TWII` (TAIEX) read from
  the snapshot; no snapshot → calls can never settle → that calibration dimension never accumulates.

Of the 14 configured indices, exactly one is indispensable to the round running at all: the home index /
macro-call benchmark `^TWII`. The global proxies (`^SOX`, `^VIX`, `^GSPC`, …) enrich the brief but the
macro-analyst already covers the world via `web_search` (PRD-002 decision 6) — they are not load-bearing.

Stooq (the usual free CSV fallback) was evaluated and **rejected**: it now gates downloads behind a
JavaScript proof-of-work challenge, infeasible from the stdlib-urllib ingest layer (invariant 6).

## Decision

Add a **benchmark-only fallback**: when Yahoo can't serve `^TWII`, fill it from **TWSE**
(`indicesReport/MI_5MINS_HIST`, the TAIEX daily OHLC) — key-less JSON, a *different source family*, behind
the same `base.fetch_json` cache/rate-limit/retry. Gated by config `macro_fallback_source` (default
`"twse"`, `""` disables).

- `ingest/macro.py`: `fetch_taiex()` + pure parsers `parse_taiex_hist` / `_roc_to_iso` (民國/ROC dates,
  thousands-separated closes) / `_months_for` (queries the as_of month + prior month so a `prev_close`
  survives a month boundary). Never raises — TWSE unreachable too → `[]`, caller degrades.
- `macro.refresh()`: after the Yahoo pull, if the benchmark is absent and the fallback is enabled, inject
  the TWSE bars into `raw[^TWII]` **before** `as_of` resolution, so the snapshot anchors on the TAIEX
  trading day even on a total Yahoo blackout.

Scope is deliberately **the benchmark only**. Only `^TWII` has a TWSE equivalent; the global proxies stay
Yahoo-best-effort + the analyst's `web_search` overlay. PIT discipline is unchanged: the fallback bars are
stamped `as_of` and archived append-only, identical to the Yahoo path (invariant 9).

## Consequences

- A Yahoo outage now **degrades the global brief but never starves the round** of the home index: GATE-1
  sees a real (if minimal) macro snapshot, and A9 macro-call scoring always has its `^TWII` benchmark.
  Verified live (Yahoo 429 on every ticker): `refresh` → `{as_of:'2026-06-18', n:1}`, `^TWII` 46465.2
  (+1.28%), where before it returned `n=0`.
- One more source dependency (TWSE) on the macro path — but TWSE is already a core price source, so no new
  key, host-trust, or operational surface. Cost is ≤2 cached GETs/day, only when Yahoo misses the benchmark.
- The dry-run harness's macro step goes from a soft "degraded" note to a real snapshot when Yahoo is down.
- Tests: `parse_taiex_hist` / `_roc_to_iso` / `_months_for` are pure (run anywhere); the `refresh`-wiring
  tests (fallback fires on blank Yahoo / is skipped when Yahoo serves it / respects the disable flag) are
  pyarrow-gated like the rest of `test_macro.py`.

## When to revisit

- If the empty-global-brief days prove too frequent to set a useful risk-on/off, add a second *global*
  fallback (a JSON index source, or FinMind US ETF proxies — quota permitting) as a future ticket; this
  ADR only guarantees the benchmark.
- If TWSE changes the `MI_5MINS_HIST` shape/symbol, `parse_taiex_hist` degrades to `[]` (no crash); update
  the parser and its fixture.
- If a paid PIT/market-data source is ever adopted, this fallback is retired in its favour.
