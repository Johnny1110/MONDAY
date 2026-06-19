# ADR 0006 — Cutover gate: paper book → real book

- **Status**: Accepted (gate defined) — **`book_mode` stays `paper` until the gate passes**
- **Date**: 2026-06-20
- **Author**: evva (resident engineer), implementing PRD-002 / v2-sub-tickets D1 at the User's direction
- **Context source**: [`docs/PRD/PRD-002-big-refactor.md`](../PRD/PRD-002-big-refactor.md) §遷移計畫 Stage D / §風險與誠實聲明; [`docs/PRD/v2-sub-tickets/D1-e2e-dryrun-and-rollout.md`](../PRD/v2-sub-tickets/D1-e2e-dryrun-and-rollout.md)

## Context

The 1.0→2.0 engine + swarm pieces (A1–A9, B1–B5, C1) have landed. Before the User puts **real money**
behind the swarm's advice — the trust-model change at the heart of 2.0 (invariant 11: the swarm advises,
the User trades) — the whole manual round must be proven end-to-end on a **paper book** for several days,
then deliberately cut over. This ADR records the **gate**; the flip itself is a future, dated decision.

## Decision

**`book_mode` defaults to `paper` (A1 config) and does not change until this gate passes.** The 1.0
autonomous `paper_positions`/`finalize` path stays intact in parallel throughout, so calibration keeps
accumulating and there is no regression window.

**Gate criteria** — flip `book_mode=real` only when ALL hold:

1. The **12-point dry-run checklist** (RUNBOOK §9) passes for **≥ N consecutive trading days** (set N at
   gate time, e.g. 5–10). `scripts/dryrun-round.sh` covers the engine half each day; the live swarm covers
   the agent half (GATE-1 degraded-data day, analyst review flags, GATE-2 block, safety-net with swarm down).
2. **Report quality is User-approved** — the 6-section reports are useful and honest over the window.
3. **Position-management decisions look sound in hindsight on paper** — `GET /api/calibration/positions`
   trends non-negative; trims/exits aren't churn.
4. **Calibration is accumulating** — stock-pick ledger + macro-call accuracy + position-mgmt value-add are
   populating (don't flip on a thin/over-fit sample; **10% monthly is an aspiration, not a license to
   over-risk** — §9 honesty, decision 4).
5. **Per-round budget is acceptable** — measured across the dry-run days (the committee fan-out costs more
   than the 1.0 waterfall; B5/settings note).

**On pass**: set `BOOK_MODE=real` in `engine/.env`, restart the engine, and record a **cutover ADR**
(date, the N achieved, the evidence, the User's sign-off). Even after cutover, **the swarm never places an
order** — `/api/book/fill` remains the User's confirmed bookkeeping; there is no broker integration, ever.

## Consequences

- The trust escalation (paper → real) is **gated and reversible** (flip `BOOK_MODE` back to `paper`),
  recorded, and User-signed — not an implicit side effect of shipping the code.
- A clear, runnable acceptance bar exists (the harness + the 12-point checklist) instead of a vibe check.
- Known honesty caveats carried into the gate: paper fills are optimistic (no real slippage — revisit
  `round_trip_cost_pct` after the first real fills); cost-basis split/dividend adjustment is still a future
  ticket (A3 limitation); macro/position calibration needs enough settled samples before it's read hard.

## When to revisit

At the cutover decision itself (a new ADR). If the dry-run surfaces a blocking defect, fix it (engine →
evva PRD; agent → prompt) and restart the N-day count. If real fills reveal slippage/cost gaps, retune
`round_trip_cost_pct` and re-examine sizing — recorded as follow-up ADRs.
