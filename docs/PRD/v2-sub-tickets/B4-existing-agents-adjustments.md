# B4 — Existing-agent adjustments (quant / risk-monitor / reviewer-calibrator / data-engineer / a-* / podcast)

- **Epic**: B (swarm roster) · **Owner**: agents/config · **Size**: M
- **Status**: Proposed
- **Depends on**: A4 (sizing), A5 (review), A6 (rescope), A9 (calibration dims), A2 (macro refresh)
- **Blocks**: B3 (morgan orchestrates these), B5 (manifest)
- **PRD ref**: PRD-002 §角色編制 2.0 (quant 降位 / risk-monitor 擴權 / reviewer 擴充 / data-engineer 擴源), §flow (TIER 1/2/3 roles); decisions 2,4,5
- **Files**: `agents/sub/{quant,risk-monitor,reviewer-calibrator,data-engineer,a-tech,a-chips,a-catalyst,podcast-listener}/system_prompt.md` (+ `tools/active.yml` where new endpoints are needed)

## Problem

The kept workers must learn the 2.0 endpoints and roles: quant runs **after 定調** (rescope) and scores holdings;
risk-monitor **owns sizing + position-risk + exposure/cash**; reviewer-calibrator reads the **new calibration dims**;
data-engineer **refreshes macro**; the three stock analysts now cover **holdings too** and emit the **review flags** A5 needs.

## Goal

Update each kept agent's prompt (and tools where required) to its 2.0 role, against the real endpoints, without breaking
the discipline (advise-not-finalize, injection defense, journal+memory).

## Scope (in) — per-agent deltas

### quant (`a` decision 2: kept as objective input)
- After SYNC A, work on the **rescoped** signals: read `GET /api/signals/today` (now focus+holdings, A6) — or, if morgan
  hasn't rescoped yet, note it. Sanity-check the rescoped ranking + that **holdings are scored**; flag OOS-IC/version issues.
- `tools/active.yml`: ensure `http_request` note covers `/api/signals/rescope` (morgan usually calls it; quant may verify).
- Keep: 不發明候選外標的、不自行重訓 (still input, not driver).

### risk-monitor (擴權: sizing + position risk)
- New duties: `POST /api/book/sizing` (A4) for the day's candidates; `GET /api/book/exposure` + `GET /api/portfolio/risk`
  for combined (new+held) concentration/correlation/liquidity/exposure/cash; raise sizing-down/cut objections to morgan
  (**GATE 2**). Cash-up in risk_off; never loosen to chase 10% (decision 4).
- `tools/active.yml`: `http_request` covers `/api/book/*`, `/api/portfolio/risk`.

### reviewer-calibrator (擴充: new dims)
- Daily reconcile unchanged (`POST /api/ledger/reconcile`) **plus** `POST /api/calibration/macro/settle` (settle matured macro calls).
- Friday scorecard now also reads `GET /api/calibration/macro` + `GET /api/calibration/positions` (A9) and the action log
  (`GET /api/book/actions`) → attribute **macro-call accuracy** and **position-management value-add**; 1–3 `task_propose`.
- `tools/active.yml`: `http_request` covers the new calibration + book endpoints.

### data-engineer (擴源: macro)
- Morning prepare now also `POST /api/macro/refresh` (STEP 0b) before/with the TW prepare run; report macro coverage/quality
  in the same quality gate (GATE 1).
- `tools/active.yml`: `http_request` covers `/api/macro/refresh`.

### a-tech / a-chips / a-catalyst (cover holdings + emit review flags)
- Overlay now spans **candidates ∩ focus + current holdings** (read `GET /api/book?status=open`). For each name return the
  score **and the structured review flags** A5 consumes: `thesis_intact`, `technical_break` (a-tech), `chips_reversal` (a-chips),
  `theme_exhausted` (a-catalyst). a-catalyst keeps the landmine veto + injection defense.
- State the boundary vs micro-analyst: analysts are **candidate/holding-level (bottom-up)**; micro-analyst is **market-level (top-down)**.

### podcast-listener (minor)
- Unchanged role; confirm the brief flows to **morgan + a-tech/a-chips/a-catalyst** in the manual-round timing (pre-staged
  ~17:00, read at TIER 1). Refresh the roster mention (macro/micro in, strategy-researcher out).

## Out of scope

- New agents (B1/B2), morgan (B3), manifest (B5), engine endpoints (A-tickets).

## Acceptance criteria

- Each listed agent's prompt names its 2.0 endpoints + role; `tools/active.yml` updated where a new endpoint is used (generic tools only).
- The three stock analysts explicitly cover **holdings** and emit the four **review flags** with the exact field names A5 expects.
- risk-monitor owns sizing + exposure/cash + GATE 2; reviewer settles macro calls + reports the two new dims.
- data-engineer refreshes macro in the morning prepare.
- All keep: advise-not-finalize (10), injection defense, journal+memory; rosters updated to 2.0.

## Test plan

- Config — verified in D1's dry-run: rescoped signals consumed by quant; risk-monitor returns sizing+exposure; analysts return holding coverage + flags that A5 turns into actions; reviewer's Friday scorecard shows macro + position-mgmt dims.

## Invariant & discipline checklist

- [ ] Generic tools only; collab auto-injected.
- [ ] Advise-not-finalize (10); injection defense (§風險 5); journal + memory (§6.5).
- [ ] Flag field names match A5's `ctx` contract exactly (no silent drift).
- [ ] Decision 4 honesty in risk-monitor (no loosening for 10%).

## Risks / edge cases

- **Flag contract drift**: if a-* emit differently-named flags than A5 reads, review silently degrades to mechanical-only — pin the names in both tickets (cross-checked in D1).
- **quant timing**: if morgan forgets to rescope, quant should flag "signals not rescoped to focus yet" rather than analyze the stale full-pool top-N.

## Rollout notes

Do alongside B1/B2; B3 depends on these flags/endpoints existing in the worker prompts. B5 then wires cadences.
