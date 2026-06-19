# ADR 0005 — Swarm cadence: cron-waterfall → human-triggered round + safety-net

- **Status**: Accepted
- **Date**: 2026-06-20
- **Author**: evva (resident engineer), implementing PRD-002 / v2-sub-tickets B5 at the User's direction
- **Context source**: [`docs/PRD/PRD-002-big-refactor.md`](../PRD/PRD-002-big-refactor.md) §workflow 啟動時機 / §遷移 Stage C; [`docs/PRD/v2-sub-tickets/B5-swarm-manifest-rewrite.md`](../PRD/v2-sub-tickets/B5-swarm-manifest-rewrite.md)

## Context

1.0's `evva-swarm.yml` was built around **morgan's nightly anchor cron** (~21:15) carrying an automated
post-close waterfall. 2.0 is a **human-triggered** committee: the User wakes morgan each morning
(`POST /api/system/run-round` → `round_requested` webhook, A8) and morgan orchestrates the DAG on demand
(B3). The manifest must switch to the manual-trigger model, add the two new analysts, retire
strategy-researcher, and reflect the new cadences — this is PRD Stage C.

## Decision

Rewrite `evva-swarm.yml`:

- **Leader trigger model** (invariant 7 — webhook primary + cron safety-net): morgan's **primary** wake is
  the `round_requested` webhook; it keeps **one safety-net cron** (`45 8 * * 1-5`, after the 07:30–08:30
  round window, decision 1) whose prompt first checks `last_round_requested` and **stands down if the round
  already ran today** (no double-run), else executes the B3 SOP. The cron is the floor, not the path.
- **Roster**: add `macro-analyst` (B1) + `micro-analyst` (B2); **remove `strategy-researcher`** (merged
  into micro-analyst, ADR 0003). 13 workers total.
- **Pre-stage crons** (acceleration only, decision 1): `podcast-listener` 17:00 (kept) + `data-engineer`
  21:15 evening TW prepare (warms cache after chips/margin settle; `post=false` so it doesn't wake morgan).
  `macro/refresh` runs **in-round** (needs the US overnight close) via morgan's STEP 0 task_assign.
- **Task-driven** (no cron, morgan task_assigns in the round): macro-analyst, micro-analyst (tasks 1+2),
  quant, a-tech, a-chips, a-catalyst, risk-monitor.
- **R&D / ops cadence** (decision 5): `quant-researcher` weekend retrain (kept); `micro-analyst` carries a
  **weekly** cron (Thu 08:00) for its task-3 forward research (the absorbed strategy-researcher mandate);
  `watchdog` widened to `*/15 7-22` to cover the morning round + evening pre-stage, with a missed-round
  backstop.
- Header comment rewritten to document the 2.0 DAG + trigger model + roster.

## Consequences

- The day starts when the **User** triggers it; the engine no longer auto-waterfalls at night. A missed
  trigger is caught by morgan's safety-net cron and watchdog (a missed wake is worse than a late one).
- **No double-run**: A8 idempotency (`round_requested:{day}`) + the safety-net's `last_round_requested`
  check are belt-and-suspenders.
- **Budget**: the committee fan-out (macro + micro + quant + 3 analysts + risk-monitor) costs more tokens
  per day than the 1.0 waterfall. Left at the `-1` exemption for now; **measure across D1's dry-run and set
  a real `daily_budget_tokens` if needed** (noted in `settings`).

## When to revisit

After D1 measures per-round token cost and latency: if too heavy, set a per-member cap or fold TIER-1
reads. If the User wants a fully-scheduled (non-human-triggered) round again, re-add a primary leader cron
— recorded as a new ADR. Behavior verified end-to-end in D1 (round_requested wakes morgan; swarm-down at
trigger time → safety-net still produces a report).
