# B3 — morgan orchestration rewrite (manual round, DAG, gates, report v2, position mgmt)

- **Epic**: B (swarm roster) · **Owner**: agents/config · **Size**: L · **the integration keystone**
- **Status**: Proposed
- **Depends on**: A3, A4, A5, A6, A7, A8 (engine capabilities), B1, B2 (new analysts), B4 (adjusted workers)
- **Blocks**: B5 (manifest leader prompt mirrors this)
- **PRD ref**: PRD-002 §flow (DAG, blocked-by, gates, morgan 編排腳本), §倉位管理, §完整 workflow (6-段報告), §角色 (morgan 改造); invariants 10/11
- **Files**: `agents/main/morgan/system_prompt.md` (rewrite the SOP), `agents/main/morgan/memory/constitution.md` (update standing rules); leader `prompt` in `evva-swarm.yml` is B5

## Problem

morgan changes from "nightly cron integrator" to "**investment-committee chair + PM**" driving a **human-triggered DAG**
with two barriers, two hard gates, position management on a real book, and a 6-section report. The orchestration is prompt
discipline (morgan is the sole synchronizer, §flow), so its system_prompt must encode the exact step sequence, the new
endpoints, and the gate behavior — precisely, no hand-waving.

## Goal

Rewrite morgan's SOP so it executes PRD-002's "morgan 編排腳本 (manual round)" verbatim against the real 2.0 endpoints,
owns position management (hold/add/trim/exit + sizing), composes & posts the 6-section report, and preserves sole-decider +
no-real-money-in-swarm.

## Scope (in)

- Rewrite `agents/main/morgan/system_prompt.md` daily-SOP section to the manual-round DAG (steps 0–9 from PRD §flow).
- Encode SYNC A / SYNC B barriers, GATE 1 / GATE 2, stand-down/timeout handling.
- Position-management authority: read A5 review, decide hold/add/trim/exit, propose fills to the User (A3), set TP/SL targets.
- Report v2: `GET /api/reports/daily/scaffold` → compose prose → `POST /api/reports/daily` (with disclaimer).
- Update `constitution.md` standing rules for 2.0 (focus-sector flow, sizing/exposure policy, the 10%-is-aspiration honesty).
- ADR for the orchestration change.

## Out of scope

- Engine endpoints (A-tickets). The leader `schedule`/`prompt` block in the manifest (B5 — but keep this prompt and that block consistent).
- Worker prompts (B4).

## Design — the SOP morgan's prompt must encode

Triggered by the `round_requested` webhook (A8) or the User in evva web:

0. **Wake** on `round_requested` (or safety-net cron). Read `GET /api/memory/morgan` (constitution / standing rules / 停利損公式).
1. **STEP 0** — `task_assign` **data-engineer**: morning prepare (`POST /api/system/run-pipeline?finalize=false&post=true`) **and** `POST /api/macro/refresh`. End turn; wake on `pipeline_complete`. **GATE 1**: if data-engineer reports quality failure / `degraded_factors` non-empty → **當日不發新標的** (but still do the holdings review, step 6) and say so honestly (§9).
2. **TIER 1** — parallel `task_assign` **macro-analyst · micro-analyst** (podcast brief already in inbox). Wait for all (delivery or stand-down).
3. **SYNC A** — integrate macro brief × micro brief × podcast → set **today's 定調**: risk_state, TW regime, 操作基調, **聚焦板塊/題材**. Then `POST /api/signals/rescope {focus_sectors, holdings}` (A6) to get the focus+holdings candidate set.
4. **STEP A1** — `task_assign` **quant**: review the rescoped inference (ranking sane, OOS IC, holdings scored). Wait.
5. **TIER 2** — parallel `task_assign` **a-tech · a-chips · a-catalyst**: overlay the candidates **and the current holdings** (B4 makes them cover holdings) → each returns scores + the **review flags** (thesis_intact / technical_break / chips_reversal / theme_exhausted) A5 consumes. Wait for all.
6. **SYNC B** — compose the draft book:
   - (A) **new ideas**: candidates × overlay × 定調 → a shortlist; get `POST /api/book/sizing` (A4) for each.
   - (B) **holdings review** (always runs): `POST /api/book/review` (A5) with the analysts' flags → hold/add/trim/exit per lot, with updated TP/SL.
7. **TIER 3 / GATE 2** — `task_assign` **risk-monitor**: combined (new+held) portfolio risk + sizing/exposure/cash check (`GET /api/portfolio/risk`, `/api/book/exposure`, A4 sizing). If not cleared → revise (cut/down-size) and re-check; **don't skip**.
8. **FINALIZE** — commit the book: propose fills to the **User** (A3 `/api/book/fill` happens on User confirm — **swarm never places orders**, invariant 11); set targets (`/api/book/targets`); (paper-mode dry-run also calls `/api/recommendations/finalize` so the calibration ledger keeps running). Then **report**: `GET /api/reports/daily/scaffold` → fill the 6 prose sections (宏觀定調 / 台股盤勢與新敘事 / 持倉檢視 / 今日新標的 / 倉位與曝險 / 風險提醒) → `POST /api/reports/daily` (carries the disclaimer) → User gets it (Telegram + dashboard).
9. **Reconcile / review** — `task_assign` **reviewer-calibrator** for the daily reconcile; Friday: weekly scorecard (incl. macro-call + position-mgmt dims, A9) → adjudicate `task_propose` → dispatch (engine→evva PRD; data→data-engineer; retrain→quant-researcher; strategy/formula→constitution); **one ADR per change** (POST /api/journal author=morgan).

### Standing rules in `constitution.md` (update)

- The focus-sector-first flow (quant after 定調); the sizing/exposure policy (risk-budget, regime scaling, caps); cash-up in risk_off.
- **10% is aspiration, not a license to over-risk** (decision 4) — never loosen GATE 2 to chase it.
- Sole decider; analysts advise; the User executes (no swarm orders).

## Acceptance criteria

- morgan's prompt encodes steps 0–9 with the **real endpoints** (`run-pipeline?finalize=false`, `macro/refresh`, `signals/rescope`, `book/review`, `book/sizing`, `book/fill`, `reports/daily*`), the two barriers, and both gates (incl. "持倉檢視永遠執行" on a no-new-ideas day).
- Position management is explicit: morgan decides hold/add/trim/exit and **proposes fills for User confirmation** (never auto-orders).
- The 6-section report authoring + disclaimer is in the SOP.
- Sole-decider + invariant 11 preserved in wording.
- `constitution.md` updated; ADR committed.

## Test plan

- Config — verified by the D1 dry-run: a full manual round produces a rescoped candidate set, a holdings review, a risk-gated book, and a posted 6-section report; gates demonstrably block (force a degraded-data day → report ships holdings-only with the honest note).

## Invariant & discipline checklist

- [ ] **Invariant 11**: swarm proposes, User executes — the prompt never has morgan place an order.
- [ ] **Invariant 10**: morgan is the sole synchronizer/decider; barriers respected (no fixed-clock waterfall).
- [ ] GATE 1/GATE 2 honest behavior (誠實 > 硬發, §9); position review always runs.
- [ ] Every adjustment → ADR (§6.4).

## Risks / edge cases

- **Prompt drift vs manifest**: the leader `prompt` in `evva-swarm.yml` (B5) must mirror this SOP — keep them in sync (B5 references this ticket).
- **Token cost of a full fan-out**: morgan should stand-down sub-steps when inputs are missing (degraded mode) rather than spin.
- **Over-trading**: position-review policy is conservative (A5) and risk-gated — the prompt must not encourage churn to "do something".

## Rollout notes

Schedule after every engine capability it calls exists (A3–A8) and the analysts are ready (B1/B2/B4). B5 then aligns the manifest leader block. Exercised end-to-end in D1.
