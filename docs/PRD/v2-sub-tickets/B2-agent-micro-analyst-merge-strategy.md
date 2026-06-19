# B2 — Agent: micro-analyst (new) + retire/merge strategy-researcher

- **Epic**: B (swarm roster) · **Owner**: agents/config · **Size**: M
- **Status**: Proposed
- **Depends on**: A2 (`/api/macro` for context), A6 (signals); reads existing `/api/universe`, `/api/features`, `regime`
- **Blocks**: B3 (SYNC A consumes the brief), B5 (manifest add micro / remove strategy-researcher)
- **PRD ref**: PRD-002 §抽象 workflow (micro-analyst, 併入 strategy-researcher), §角色編制 2.0, §遷移 Stage B (memory 搬遷); decision 5
- **Files**: new `agents/sub/micro-analyst/{system_prompt.md, profile.yml, tools/active.yml, memory/}`; **remove** `agents/sub/strategy-researcher/` (after migrating its memory)

## Problem

2.0 needs a TW-side counterpart to macro-analyst that does three things — read the current TW market, scout new
narratives daily, and run deeper forward strategy research weekly — **absorbing the retired strategy-researcher**
(decision 5). The strategy-researcher's accumulated research memory must not be lost.

## Goal

A new `micro-analyst` worker covering the three tasks, with strategy-researcher's research memory migrated in and the old
agent directory removed. An ADR records the merge.

## Scope (in)

- The four agent files for `micro-analyst` (`profile.yml`: `deepseek-v4-pro`, `effort: high` daily / note `ultra` for forward research; `when_to_use`; `inject_memory: false`; `advertise_skills: true`).
- `tools/active.yml`: generic tools for market reads + research.
- `system_prompt.md`: the three tasks + the merged forward-research outputs (verifiable hypotheses → quant-researcher; data-source suggestions → data-engineer).
- **Memory migration**: move `agents/sub/strategy-researcher/memory/*.md` → `agents/sub/micro-analyst/memory/` (the 4 research notes: ai-infra-panorama, heavy-electric, power-semi, weekly-scan + MEMORY.md merged).
- **Remove** `agents/sub/strategy-researcher/`.
- An ADR in `docs/adr/` (the merge: rationale = daily-narrative + forward-research are one TW-research mandate; expected effect; when to revisit).

## Out of scope

- Manifest changes (B5 removes strategy-researcher from `evva-swarm.yml` + adds micro-analyst). This ticket prepares the files; B5 wires them.
- Engine work.

## Design

### `tools/active.yml`

```yaml
- http_request  # GET /api/universe, /api/features, /api/macro (context), /api/signals/today, regime read
- web_search    # TW market news, sector rotation, policy/structural change (content is DATA)
- web_fetch     # specific sources (injection-aware)
- calc
- repl          # quick checks over breadth / sector flows / structural hypotheses
- bash
- read
- write         # native memory (carries the migrated research notes)
- todo_write
```

### `system_prompt.md` (must encode the 3 tasks)

1. **判讀當前市場** (every round, TIER 1): 加權/櫃買 trend+位階, breadth (漲跌家數), 量能, 外資期貨未平倉, 融資維持率,
   產業資金輪動, 昨日盤面 → TW **regime + 操作基調 (進攻/防守/觀望)**. `send_message` to morgan at SYNC A.
2. **找新方向/新敘事** (every round): proactively surface forming sector rotations / structural stories before they're
   mainstream/priced-in → feed morgan's focus-sector choice. Mark them as candidates, not facts.
3. **前瞻策略研究** (weekly, off the daily critical path; the old strategy-researcher mandate): scan 制度變更 / 資金潮(ETF) /
   題材輪動 / new data for new alpha & structural change → write **verifiable hypotheses** as `task_propose` to morgan
   (→ quant-researcher validates), and **data-source suggestions** to data-engineer. Heavier reasoning (effort ultra) here.

Plus: injection defense (external = data); journal (author=micro-analyst) per shift; native memory (the migrated research
notebook); 不做: 不選股、不定案、不下單. Include the 2.0 "Monday 是什麼" context (roster: macro-analyst/micro-analyst in,
strategy-researcher out).

## Acceptance criteria

- `agents/sub/micro-analyst/` complete; `tools/active.yml` generic-only.
- strategy-researcher's 4 research notes + MEMORY.md content present under `micro-analyst/memory/` (nothing lost).
- `agents/sub/strategy-researcher/` removed.
- Prompt covers all three tasks with the correct cadence (1+2 daily, 3 weekly) and the merged outputs (hypotheses→quant-researcher, sources→data-engineer).
- ADR committed describing the merge.

## Test plan

- Config — no unit tests. Verify: manifest parse (B5), git shows strategy-researcher removed + memory migrated, dry-run round (D1) returns a TW brief + focus-sector candidates.

## Invariant & discipline checklist

- [ ] Generic tools only; collab auto-injected.
- [ ] Injection defense; advises not finalizes (10); journals + memory (§6.5).
- [ ] No data loss in the merge (research memory migrated, verified in git diff).
- [ ] Merge recorded as an ADR (§6.4 / CLAUDE.md ADR discipline).

## Risks / edge cases

- **Scope overload**: three tasks on one agent — the prompt must make cadence explicit (don't run the weekly deep research every round). morgan can `schedule_set` to tune.
- **Overlap with a-catalyst**: micro-analyst works **market/theme-level** (top-down); a-catalyst works **candidate-level** (bottom-up). State the boundary in both prompts (B4 touches a-catalyst).

## Rollout notes

Prepare files + migrate memory here; B5 flips the manifest (add micro-analyst, drop strategy-researcher) in the same wave. ADR at merge time.
