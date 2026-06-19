# ADR 0004 — morgan's manual-round orchestration (2.0 top-down DAG)

- **Status**: Accepted
- **Date**: 2026-06-19
- **Author**: evva (resident engineer), implementing PRD-002 / v2-sub-tickets B3 at the User's direction
- **Context source**: [`docs/PRD/PRD-002-big-refactor.md`](../PRD/PRD-002-big-refactor.md) §flow / §倉位管理 / §完整 workflow; [`docs/PRD/v2-sub-tickets/B3-morgan-orchestration-rewrite.md`](../PRD/v2-sub-tickets/B3-morgan-orchestration-rewrite.md)

## Context

1.0 morgan was a **nightly-cron integrator**: an alarm woke it post-close, it ran an automated waterfall
(data-engineer prepare → analysts overlay → finalize ≤20 → push), and the output was a paper portfolio.
2.0 changes the operating model to a **human-triggered, top-down investment committee** that manages the
**User's real book** (invariant 11: the swarm advises, the User trades). The orchestration is **prompt
discipline** — morgan is the sole synchronizer (§flow) — so its system_prompt must encode the exact step
sequence, the new engine endpoints (A2–A9), the barriers/gates, and position management, precisely.

## Decision

Rewrite `agents/main/morgan/system_prompt.md` to the **manual-round DAG** (steps 0–9), triggered by the
`round_requested` webhook (A8) with a safety-net cron (B5):

- **STEP 0** data-engineer prepare (`run-pipeline?finalize=false`) + `macro/refresh`; **GATE 1** (data
  quality / `degraded_factors`) → no new ideas that day, **but holdings review still runs**.
- **TIER 1** macro-analyst + micro-analyst (+ podcast brief) → **SYNC A** (barrier ①): morgan sets the
  day's 定調 (risk_state / TW regime / 操作基調 / focus sectors) → `POST /api/signals/rescope`.
- **STEP A1** quant reviews the rescoped inference (holdings scored).
- **TIER 2** a-tech/a-chips/a-catalyst overlay **candidates + holdings**, emitting the A5 review flags →
  **SYNC B** (barrier ②): compose draft book — new ideas (`/api/book/sizing`) + holdings review
  (`/api/book/review`, **always runs**).
- **GATE 2** risk-monitor clears combined sizing/exposure/concentration (revise-and-recheck, no skip).
- **FINALIZE**: propose fills to the **User** (recorded via `/api/book/fill` only on the User's confirm —
  **swarm never orders**), set targets, post the **6-section daily report** (`/api/reports/daily`, carries
  the disclaimer). Reconcile daily; Friday folds in the macro-call + position-mgmt calibration dims (A9).

`constitution.md` is updated (v0.5) with the focus-sector-first flow, the sizing/exposure policy
(risk-budget × conviction × regime scale, caps, cash-up in risk_off), **"10% is aspiration, not a license
to over-risk,"** and the sole-decider / no-swarm-orders rules.

## Consequences

- **Two barriers (SYNC A/B) + two gates (GATE 1 data, GATE 2 risk)** are now explicit, sequential, and
  non-skippable; the position-review path runs even on a no-new-ideas day.
- morgan is unambiguously the **only synchronizer and the only finalizer**; analysts advise. Invariant 11
  is in the wording: morgan proposes fills, the User executes — the prompt never has morgan place an order.
- The leader `schedule`/`prompt` block in `evva-swarm.yml` (B5) must mirror this SOP — kept in sync there.
- Exercised end-to-end in D1's dry-run (a forced degraded-data day must ship a holdings-only report).

## When to revisit

If the manual round proves too heavy per day (token cost / latency, measured in D1), prune the fan-out
(e.g. fold TIER-1 reads) — recorded as a new ADR. If the User wants morgan to auto-record paper fills
without per-fill confirmation in dry-run, that stays **paper-only**; real `book_mode` never auto-orders.
