# ADR 0003 — Merge strategy-researcher into micro-analyst

- **Status**: Accepted
- **Date**: 2026-06-19
- **Author**: evva (resident engineer), implementing PRD-002 / v2-sub-tickets B2 at the User's direction
- **Context source**: [`docs/PRD/PRD-002-big-refactor.md`](../PRD/PRD-002-big-refactor.md) §角色編制 2.0 / §遷移 Stage B; [`docs/PRD/v2-sub-tickets/B2-agent-micro-analyst-merge-strategy.md`](../PRD/v2-sub-tickets/B2-agent-micro-analyst-merge-strategy.md)

## Context

Monday 2.0 turns the swarm into a **top-down investment committee**. The day now opens with two
parallel "set the stage" reads: **macro-analyst** (world indices / overnight → risk-on/off, B1) and a
TW-side counterpart that reads the **current Taiwan market** and scouts **new directions / narratives**
before they are priced in. That TW-side mandate overlaps heavily with the 1.0 **strategy-researcher**,
whose job was forward strategy research (new alpha, structural change, new data sources).

Keeping both would split one coherent "TW research" mandate across two agents — daily narrative scouting
and weekly forward research are the same craft on different cadences, and a year of 24/7 tokens for a
redundant seat is a real cost (the §7.2 staffing philosophy: let the ledger reveal which seats earn their
keep). Decision 5 (locked in the plan overview) resolves this by **merging** them.

## Decision

Create **`micro-analyst`** carrying three tasks:
1. **判讀當前市場** (every round, TIER 1) — TW regime + 操作基調 → morgan at SYNC A.
2. **找新方向 / 新敘事** (every round) — forming sector rotations / structural stories → morgan's focus-sector choice.
3. **前瞻策略研究** (weekly, off the daily critical path) — the retired strategy-researcher mandate:
   verifiable hypotheses → `task_propose` to morgan → quant-researcher OOS-validates; new data sources → data-engineer.

**Retire `strategy-researcher`**: its agent directory is removed; its accumulated research memory
(`heavy-electric`, `power-semi`, `ai-infra-panorama`, `weekly-scan` + the MEMORY index) is **migrated
into `micro-analyst/memory/`** so no research is lost (agent memory is gitignored runtime state, so the
notes move on disk; the tracked `.gitkeep` is `git mv`-renamed). The manifest swap (add micro-analyst,
drop strategy-researcher) lands in **B5**; morgan's SYNC-A consumption in **B3**.

Boundary kept explicit in both prompts: **micro-analyst = market/theme-level (top-down)**; **a-catalyst
= candidate-level (bottom-up)**.

`profile.yml`: `deepseek-v4-pro` / `effort: ultra` (the weekly deep research needs full reasoning; the
runtime tiers are `ultra`/`low`, so the plan's nominal "high" maps to `ultra`, matching the analyst peers).

## Consequences

- One TW-research seat instead of two; the daily narrative read and the weekly hypothesis pipeline share
  one memory/notebook (continuity preserved via the migration).
- **Expected effect**: tighter top-down → focus-sector handoff; fewer redundant tokens; the calibration
  ledger (A9 + the weekly review) now attributes TW-market judgement to a single accountable seat.
- **Risk**: three tasks on one agent can overload a round — the prompt makes cadence explicit (1+2 daily,
  3 weekly); morgan can `schedule_set` to tune.

## When to revisit

If the weekly forward research is consistently crowded out by the daily duties (visible as thin task-3
output over a month), split task 3 back into a dedicated low-frequency researcher — recorded as a new ADR.
