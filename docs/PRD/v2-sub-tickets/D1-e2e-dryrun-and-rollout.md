# D1 — End-to-end dry-run, rollout & gating to the real book

- **Epic**: D (integration & rollout) · **Owner**: evva (+ morgan/User for the gate) · **Size**: M
- **Status**: Proposed
- **Depends on**: ALL of A* / B* / C1
- **Blocks**: — (final gate before the User trades the real book)
- **PRD ref**: PRD-002 §遷移計畫 Stage D (dry-run 再接真錢), §風險 (10% honesty, real-money trust), invariant 11; whitepaper §10 (live-run gate)
- **Files**: `engine/scripts/smoke.sh` (extend), new `engine/scripts/dryrun-round.sh` (or a `--round` dry harness), `RUNBOOK.md`, `docs/adr/` (cutover ADR), `engine/monday/manual.md` (final pass)

## Problem

The 1.0→2.0 pieces land independently; before the User puts **real money** behind the advice (the trust-model change,
invariant 11 / §風險 2), the whole manual round must be proven end-to-end on a **paper book** for several days — report
quality, position-management logic, gates, and calibration all working — then deliberately cut over.

## Goal

A repeatable dry-run that exercises the full round on `book_mode=paper`, an acceptance checklist proving each stage, an
updated RUNBOOK, and an explicit **go/no-go gate** (with the cutover ADR) to flip `book_mode=real`.

## Scope (in)

- A **dry-run harness** that drives one full manual round end-to-end against the real engine on a paper book:
  `run-round` → (data-engineer) prepare + `macro/refresh` → rescope → analysts → review/sizing → risk gate → finalize →
  `POST /api/reports/daily` → reconcile. Scriptable (`scripts/dryrun-round.sh`) for the engine-side calls; the agent side runs the live swarm.
- An **acceptance checklist** (below) run for **≥ several trading days** on paper.
- **RUNBOOK.md** updated: how to launch 2.0 (manual round), the pre-stage crons, the round button, the book endpoints, and the cutover steps.
- **Cutover gate + ADR**: criteria to flip `book_mode` paper→real (decision 3), recorded as an ADR.
- Final **manual.md** consistency pass (all new endpoints documented).

## Out of scope

- New features (all in A*/B*/C1). This ticket integrates + gates, it doesn't add capability.

## Design — acceptance checklist (the dry-run must show all)

1. **Trigger**: `POST /api/system/run-round` wakes morgan once (idempotent); dashboard button works.
2. **GATE 1**: a forced degraded-data day → morgan ships **holdings-only** report with the honest "今日不發新標的" note (no crash, no forced picks).
3. **Top-down**: macro-analyst + micro-analyst + podcast briefs reach morgan; a `macro_call` is recorded (`GET /api/calibration/macro`).
4. **Focus → quant**: `POST /api/signals/rescope` yields focus-sector candidates **+ all holdings scored** (full-pool ranking preserved).
5. **Overlay**: a-tech/a-chips/a-catalyst cover candidates **and holdings**, emitting the review flags A5 consumes.
6. **Position mgmt**: `POST /api/book/review` returns hold/add/trim/exit per lot; `POST /api/book/sizing` returns sane sizes; **持倉檢視 runs even on a no-new-ideas day**.
7. **GATE 2**: risk-monitor blocks an over-concentrated/over-sized book; morgan revises and re-checks (no skip).
8. **Finalize**: fills are **proposed for User confirmation** (no auto-order, invariant 11); paper book + ledger update; `book=paper` only.
9. **Report v2**: a 6-section report is posted (`GET /api/reports/daily`), carries the **disclaimer**, renders on the dashboard + Telegram.
10. **Calibration**: daily reconcile runs; macro calls settle (`/calibration/macro/settle`); a Friday scorecard shows macro-call + position-mgmt dims.
11. **Safety-net**: with the swarm down at trigger time, the manifest backstop (B5) still produces something; no double-run.
12. **Quality bar**: tests green (`./scripts/run-tests.sh`), `vue-tsc` clean, `/health` ok, no invariant regressions.

## Cutover gate (paper → real, decision 3)

Flip `book_mode=real` **only when**: the checklist passes for **≥ N consecutive trading days** (set N, e.g. 5–10); report
quality is User-approved; position-management decisions look sound in hindsight on paper; calibration is accumulating;
the budget per round is acceptable (B5). Record the decision + criteria + result as a **cutover ADR**. The User confirms.
**Until then, no real money** (invariant 11).

## Acceptance criteria

- The dry-run harness runs a full round end-to-end on paper and the 12-point checklist is demonstrably satisfied (capture evidence: task ids, the posted report, calibration rows).
- RUNBOOK.md documents the 2.0 launch + round + cutover; manual.md covers every new endpoint.
- A go/no-go ADR exists with explicit cutover criteria; `book_mode` stays `paper` until the gate passes.
- Existing 1.0 path still works until cutover (no hard removal of `paper_positions`/`finalize` before the gate).

## Test plan

- Re-run `./scripts/run-tests.sh` (all green) + `vue-tsc`.
- Drive `scripts/dryrun-round.sh` against a dev engine + a live (or permission-bypass) swarm; record outputs per checklist item.
- Negative tests: degraded-data day (GATE 1), over-concentrated book (GATE 2), swarm-down (safety-net), double-trigger (idempotency).

## Invariant & discipline checklist

- [ ] **Invariant 11**: real money only after the explicit gate; swarm never orders; disclaimer everywhere.
- [ ] Honest gating: don't flip to real on a thin/over-fit sample (§9, decision 4 — 10% is aspiration).
- [ ] All invariants 1–11 re-verified end-to-end (this is the integration check).
- [ ] Cutover recorded as an ADR (§6.4).

## Risks / edge cases

- **"Looks good on paper"**: paper fills are optimistic — RUNBOOK notes that real fills/slippage differ; keep `round_trip_cost_pct` honest and revisit after first real fills.
- **Budget blow-up**: a full daily fan-out may exceed `daily_budget_tokens` — measure across the dry-run days and tune in B5.
- **Premature cutover pressure** (chasing 10%): the gate is the guardrail — N consecutive clean days + User sign-off, no shortcuts.

## Rollout notes

The terminal ticket. On success + ADR + User sign-off, flip `book_mode=real`; the 1.0 autonomous path can then be retired in a follow-up once the real book is trusted.
