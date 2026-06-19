# B5 — `evva-swarm.yml` rewrite (manual-trigger model + 2.0 roster)

- **Epic**: B (swarm roster) · **Owner**: agents/config · **Size**: M
- **Status**: Proposed
- **Depends on**: B1, B2, B3, B4 (the agents must exist before the manifest references them)
- **Blocks**: D1 (dry-run runs the manifest)
- **PRD ref**: PRD-002 §workflow 啟動時機 (manual), §遷移 Stage C (crons → manual), §角色編制 2.0; decisions 1,5; ADR for cadence change
- **Files**: `evva-swarm.yml`, an ADR in `docs/adr/`

## Problem

The 1.0 manifest is built around **morgan's nightly cron anchor** carrying an automated waterfall. 2.0 is **human-triggered**:
the User wakes morgan (A8 `round_requested`), who orchestrates on demand (B3). The manifest must switch to the manual-trigger
model, add macro-analyst + micro-analyst, **remove strategy-researcher**, keep pre-stage crons + a safety-net, and reflect the
decision-5 cadences. This is PRD Stage C.

## Goal

`evva-swarm.yml` reflects the 2.0 roster + the manual-trigger model: morgan primarily wakes on `round_requested` (cron only as
a safety-net backstop), the right pre-stage crons remain, strategy-researcher is gone, and the roster comments document the DAG.

## Scope (in)

- **Leader (morgan)**: primary trigger = `round_requested` webhook (A8); keep a **safety-net cron** (a late backstop so a
  missed wake still produces something, per PRD-001 spirit) with a prompt that mirrors B3's SOP. Make clear the cron is the
  floor, not the primary path.
- **Add** workers `macro-analyst` (B1), `micro-analyst` (B2).
- **Remove** `strategy-researcher` (merged into micro-analyst, B2).
- **Pre-stage crons** (decision 1, 盤前 round): `podcast-listener` ~17:00 (keep); `data-engineer` — evening TW prepare and/or
  a morning `run-pipeline?finalize=false` + `macro/refresh` so data is fresh when the User triggers; analysts/quant/risk-monitor
  stay **task-driven** (no cron — morgan wakes them in the round).
- **R&D / ops cadence** (decision 5): `quant-researcher` low-freq (weekend retrain) kept; `watchdog` kept (data-freshness +
  engine health + missed-wake backstop).
- Update the big header comment block to describe the 2.0 DAG + roster (replace the 1.0 nightly-waterfall description).

## Out of scope

- Agent persona content (B1–B4). Engine (A-tickets).

## Design notes

- Keep `settings` (permission_mode, budgets, timeouts) but revisit `daily_budget_tokens` given the heavier per-round fan-out
  (note it; tune in D1).
- Leader block: `schedule.cron` = a single safety-net time (e.g. a late-morning backstop on weekdays) with a prompt: "if no
  `round_requested` was handled today, run the manual-round SOP (B3)". Primary path is event-driven.
- Worker blocks: `macro-analyst` / `micro-analyst` task-driven (morgan task_assigns in TIER 1) — micro-analyst MAY carry a
  weekly cron for its task-3 forward research. `podcast-listener` keeps its 17:00 cron. `data-engineer` carries the pre-stage
  cron(s). Document each `when_to_use`/prompt to match B1–B4.
- ADR: "cadence change — cron-waterfall → human-triggered round + safety-net" (rationale, expected effect, when to revisit).

## Acceptance criteria

- `evva-swarm.yml` parses/loads (manifest validation / `evva swarm` dry parse) with the 2.0 roster.
- `macro-analyst` + `micro-analyst` present; `strategy-researcher` absent (no dangling reference anywhere in the file).
- morgan's primary trigger is `round_requested`; a safety-net cron remains with a B3-consistent prompt.
- Pre-stage crons (podcast, data-engineer macro/prepare) present; analysts/quant/risk-monitor task-driven; quant-researcher + watchdog retained at decision-5 cadences.
- Header comment documents the 2.0 DAG; ADR committed.

## Test plan

- Manifest parse / load check. Full behavior verified in D1 (dry-run): a `round_requested` wakes morgan and the round runs; with the swarm "down" at trigger time, the safety-net path still produces a report.

## Invariant & discipline checklist

- [ ] Triggers = webhook primary + cron safety-net (invariant 7; PRD-001 lesson — missed wake is worse than late).
- [ ] Roster matches §角色編制 2.0; no orphan agent dirs vs manifest.
- [ ] Cadence change recorded as an ADR (§6.4).
- [ ] `permission_mode`/budgets reviewed for the heavier round (note + tune).

## Risks / edge cases

- **Orphan refs**: removing strategy-researcher must leave no reference (grep the file). The dir removal is B2; this is the manifest.
- **Double-run**: A8 idempotency + the safety-net guard must not both fire a round — the cron prompt checks "already handled today" (mirror PRD-001).
- **Budget**: a full committee fan-out per round costs more tokens than the 1.0 waterfall — watch `daily_budget_tokens`; D1 measures it.

## Rollout notes

Last swarm ticket (needs B1–B4). After it, the swarm is 2.0-shaped; D1 runs the dry-run and gates the cutover to the real book.
