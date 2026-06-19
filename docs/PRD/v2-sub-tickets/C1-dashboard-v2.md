# C1 — Dashboard v2 (macro / book / report v2 / calibration v2)

- **Epic**: C (surface) · **Owner**: evva · **Size**: L
- **Status**: Proposed
- **Depends on**: A2 (macro), A3 (book), A7 (report v2), A9 (calibration dims), A8 (round button)
- **Blocks**: D1 (dry-run reviews the dashboard)
- **PRD ref**: PRD-002 §平台改動 (報告 v2 dashboard 呈現), §倉位管理, §workflow (User 收報告); whitepaper §3 (dashboard)
- **Files**: `engine/monday/web/src/views/*.vue` (new: Macro, Book; updated: Today/Reports, Calibration), `web/src/router.ts`, `web/src/App.vue` (nav), `web/src/lib/api.ts`, components as needed; build → `web/dist/` (committed)

## Problem

The 1.0 dashboard (Today / Signals / Portfolio / Calibration / Ledger / Reports / System / Manual) has no macro panel, no
real-book/position view, renders only flat reports, and shows only stock-pick calibration. 2.0's User-facing surface needs the
macro read, the managed book + position actions, the 6-section daily report, the new calibration dims, and a **"Run today's
round"** button (A8).

## Goal

A `vue-tsc`-clean dashboard v2 that surfaces macro, the book, the structured daily report, and calibration v2, plus the
round-trigger button — built to `web/dist/` and served by FastAPI at `/`.

## Scope (in)

- **MacroView** (new) — `GET /api/macro`: index grid (name, close, chg_pct, asset_class) + risk-state banner; PIT date picker (`/api/macro/{date}`).
- **BookView** (new) — `GET /api/book` holdings (qty, avg_entry, price, MTM, TP/SL, sizing_pct) + `GET /api/book/exposure` (by-sector, cash) + `GET /api/book/actions` (the hold/add/trim/exit log).
- **Today / Reports** (update) — render the **6-section daily report** (`GET /api/reports/daily`): macro, market+narrative, holdings review, new ideas (with sizing + TP/SL), exposure, risk notes + the disclaimer.
- **CalibrationView** (update) — add **macro-call accuracy** (`GET /api/calibration/macro`) + **position-mgmt value-add** (`GET /api/calibration/positions`) beside the existing IC/hit/reliability.
- **Round button** — a header action calling `POST /api/system/run-round` with success/already-requested feedback (A8).
- `lib/api.ts` — typed wrappers for the new endpoints; reuse `Pager`/`Sparkline`/`Reliability` components.

## Out of scope

- Auth (dashboard is local/operator). Inbound Telegram (future). Editing the book from the dashboard beyond the round button (fills come via morgan→User confirm; a manual-fill form is optional, note it).

## Design notes

- Follow the existing black-gold theme + view conventions (`SignalsView.vue`/`PortfolioView.vue` as templates); SVG curves like `Sparkline.vue`.
- `router.ts` + `App.vue` nav: add **Macro** and **Book** entries; keep the rest.
- Keep TS strict — `vue-tsc` must be clean (DoD). Build with `npm run build`; **commit `web/dist/`** (served by `app.py`).
- The report view must always show the **disclaimer** prominently (invariant 11).
- Empty/loading/error states for every new panel (no blank screens when an endpoint has no data yet — mirror existing "No pipeline run yet" notes).

## Acceptance criteria

- New **Macro** and **Book** views render live data; **Today/Reports** renders the full 6-section report incl. holdings actions + sizing + disclaimer; **Calibration** shows macro + position-mgmt dims.
- The **Run today's round** button calls A8 and shows requested / already-requested feedback.
- `vue-tsc` clean; `npm run build` succeeds; `web/dist/` committed and served at `/`.
- All new panels have empty/loading/error states; no console errors.
- No existing view regresses.

## Test plan

- `vue-tsc --noEmit` clean (the project's type gate).
- Manual: boot `python -m monday`, open `/`, exercise each new/updated view against a seeded DB; trigger the round button (mock/observe `round_requested`).
- (Optional) a tiny `api.ts` unit if the project has a JS test runner; otherwise type-check + manual is the bar (matches 1.0).

## Invariant & discipline checklist

- [ ] Reads only token-free `/api/*`; no keys in the frontend (2).
- [ ] Disclaimer always shown on the report (11).
- [ ] `vue-tsc` clean + `dist/` committed (DoD frontend rule).
- [ ] No new heavy frontend deps without cause (keep the Vite/Vue 3/TS stack).

## Risks / edge cases

- **Schema coupling**: the report view binds to A7's contract — if A7's shape changes, update `api.ts` types in the same PR (overview §7 is the source).
- **Big tables**: book/actions can grow — paginate (reuse `Pager.vue`).
- **dist drift**: forgetting to rebuild leaves a stale dashboard — the acceptance step rebuilds + commits.

## Rollout notes

Build after the engine endpoints it reads (A2/A3/A7/A9/A8). Part of Stage A's "dashboard 呈現"; reviewed in D1's dry-run as the User-facing surface.
