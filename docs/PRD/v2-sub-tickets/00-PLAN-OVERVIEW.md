# Monday 2.0 — Plan Overview & Ticket Index

> **Source of truth**: [`docs/PRD/PRD-002-big-refactor.md`](../PRD-002-big-refactor.md) (the 2.0 design).
> This folder decomposes that PRD into **independently-shippable tickets**, one focused implementation
> session each. Read this overview first, then pick a ticket. Each ticket is self-contained: problem →
> goal → scope → design (real file paths) → acceptance criteria → test plan → invariant checklist →
> rollout. **Production-grade is the bar — no compromise.** A ticket is "done" only when its full
> Definition of Done (below) is green.

- **Date**: 2026-06-19
- **Owner of engine tickets (A/C/D-engine)**: `evva` (resident engineer), per CLAUDE.md "durable capability → PRD → evva".
- **Owner of swarm tickets (B)**: whoever edits `agents/` + `evva-swarm.yml` (config/prompt work, not engine code).
- **Authoritative spec**: whitepaper §1 (invariants), §5 (engine), §6 (calibration), §7 (roster); ADR 0001/0002.

---

## 0. How to use this folder

1. Each `A*/B*/C*/D*` file is **one session**. Implement it end-to-end, satisfy its acceptance criteria, commit.
2. Respect **Depends-on**. The dependency waves in §4 give a safe build order; engine tickets parallelize after `A1`.
3. Every ticket ends in a commit + (for structural/strategy changes) an **ADR** in `docs/adr/`.
4. If a ticket reveals the PRD is wrong/underspecified, **stop and update PRD-002 first** (it is the source of truth), then resume.

---

## 1. Locked assumptions (the PRD §"待定決策" — resolved for this plan)

These are the recommended answers baked into the tickets so they are concrete. **Confirm before starting
Stage A**; if any changes, the affected tickets are noted.

| # | Decision | Locked answer (this plan) | Affects |
| --- | --- | --- | --- |
| 1 | round 時點 | **盤前早晨 07:30–08:30**（primary）；前一晚 pre-stage（podcast + 台股盤後備料）為加速用 | A8, B3, B5 |
| 2 | quant 去留 | **保留為客觀輸入**（降位，不退場）——留住可校準的科學核心 | A6, B4 |
| 3 | 真實 book 接入 | 引擎端點 **decision-agnostic**（接收 fills）；預設流程 = **morgan 提案 → User 確認 fills**，同時支援 User 手動回報。`book_starting_cash` 與 `book_max_position_pct` 進 config | A3, A4, B3 |
| 4 | 月 10% | **aspiration（北極星），非硬 KPI** — 校準數據逐季校正；風控不為衝 KPI 放鬆 | A4, A5, A9, B3, B4 |
| 5 | R&D / 維運 agents | **保留但降頻**：quant-researcher 低頻重訓；watchdog 顧資料新鮮度/引擎健康。strategy-researcher **已併入 micro-analyst** | B2, B4, B5 |
| 6 | macro 資料 | **evva 在 Stage A 做 `/api/macro`**（PIT 紀律 + 生產品質要求真資料端點）；macro-analyst 另用 `web_search` 補世界新聞 | A2, B1 |
| 7 | 專責 PM agent | **不新增**；morgan（決策）+ risk-monitor（sizing/風控閘）兼 | A4, A5, B3, B4 |

**World-news engine ingest is explicitly OUT of MVP scope** (decision 6): macro-analyst reads news via
`web_search`; the platform only **PIT-archives the daily macro brief** (A7/A9). A news adapter can be a
future ticket if the brief proves insufficient.

---

## 2. Invariants every ticket must preserve (whitepaper §1 / CLAUDE.md)

A ticket that breaks any of these is **rejected**, no exceptions:

1. **Data = read-only external (keys engine-side); output = platform state.** Agents use only `http_request`.
2. **All `/api/*` token-free.** New endpoints included. Keys live only in `config.py`/`.env`.
3. **Bulk lists paginated** via `pagination.paginate` → `{items,page,page_size,total,has_more}`.
4. **One router module per prefix** (invariant 4). New module → new `routers/<name>.py` mounted in `app.py`.
5. **Transactional state = PostgreSQL** (`store.py`); large analysis tables = **parquet** (`parquetio`/`snapshot`).
6. **Pure logic stdlib-only + unit-tested**; heavy deps (pandas/numpy/lightgbm/fastapi) **lazily imported**, never at module top level.
7. **Triggers = webhook + cron safety net, not polling** (`events.py` + `triggers.py`).
8. **Two outbound channels fire-and-forget, never raise** (`events.post` to swarm; `telegram.send` to User; no-op when unset).
9. **PIT snapshot discipline** (§4.2): any new external data (macro indices/news) is archived `as_of`, append-only.
10. **sole decider** = morgan (prompt discipline); new analysts advise, never finalize.
11. **No real money in the swarm**: the engine records the User's real book but the **swarm never places orders** (User is the air-gap). Reports carry the "研究意見、下單與盈虧 User 自負" disclaimer.

---

## 3. Ticket index

### EPIC A — Engine foundations (Stage A; owner: evva)

| ID | Title | Depends on | Size | Deliverable |
| --- | --- | --- | --- | --- |
| **A1** | Schema, store layer & data contracts | — | M | New PG tables + columns + `store` CRUD + `test_store` |
| **A2** | Macro data layer + `GET /api/macro` | — | L | `ingest/macro.py` + macro PIT snapshot + `routers/macro.py` + manual |
| **A3** | Real book & position-lifecycle API (`/api/book`) | A1 | M | `book.py` + `routers/book.py` + fills/holdings/actions |
| **A4** | Position sizing engine (pure) + API | A1, A3 | M | `sizing.py` (pure) + endpoint + `test_sizing` |
| **A5** | Daily position-review engine (pure) + API | A1, A3 | M | `review.py` (pure hold/add/trim/exit) + endpoint + `test_review` |
| **A6** | Focus-scoped inference + holdings scoring | — | M | `signals`/`pipeline` scoping by sector + score current holdings |
| **A7** | Daily report v2 (6-section) + Telegram + contract | A1, A2, A3, A4, A5 | M | `report.py` builder + `routers/reports` v2 + telegram v2 |
| **A8** | Manual round trigger (`POST /api/system/run-round`) | — | S | round trigger + `round_requested` webhook + idempotency |
| **A9** | Calibration extensions (macro-call + position-mgmt) | A1, A2, A3, A5 | M | new calibration math + endpoints + triggers |

### EPIC B — Swarm roster (Stage B; owner: agents/config)

| ID | Title | Depends on | Size | Deliverable |
| --- | --- | --- | --- | --- |
| **B1** | Agent: macro-analyst (new) | A2 | S | `agents/sub/macro-analyst/{system_prompt,profile,tools}` |
| **B2** | Agent: micro-analyst (+ retire/merge strategy-researcher) | A2 | M | new agent + memory migration + strategy-researcher retired |
| **B3** | morgan orchestration rewrite (manual round, DAG, gates, report v2, position mgmt) | A3,A4,A5,A6,A7,A8,B1,B2,B4 | L | morgan `system_prompt` + leader schedule/prompt rewrite |
| **B4** | Existing-agent adjustments (quant/risk-monitor/reviewer/data-engineer/a-*/podcast) | A4,A5,A6,A9 | M | per-agent prompt + tools deltas |
| **B5** | `evva-swarm.yml` rewrite (manual-trigger model + roster) | B1,B2,B3,B4 | M | manifest: leader anchor, pre-stage crons, roster, retire strategy-researcher |

### EPIC C — Dashboard (Stage A/D; owner: evva)

| ID | Title | Depends on | Size | Deliverable |
| --- | --- | --- | --- | --- |
| **C1** | Dashboard v2 (macro / book / report v2 / calibration v2) | A2,A3,A7,A9 | L | new Vue views + `vue-tsc` clean + built `dist/` |

### EPIC D — Integration, migration & rollout (Stage D)

| ID | Title | Depends on | Size | Deliverable |
| --- | --- | --- | --- | --- |
| **D1** | End-to-end dry-run, rollout & gating to real book | ALL | M | dry-run harness + RUNBOOK update + ADRs + go/no-go gate |

---

## 4. Dependency waves (safe build order)

```
Wave 1 (foundation)        A1
Wave 2 (parallel, post-A1) A2 · A3 · A6 · A8          ← engine breadth; A2/A6/A8 need only main + A1-stable store
Wave 3 (engine depth)      A4 · A5  (post-A3)         ┐
                           A9       (post-A1+A2+A3)   ├ A7 (post-A2+A3+A4+A5) closes the engine
                           A7                          ┘
Wave 4 (swarm)             B1 (post-A2) · B2 (post-A2) · B4 (post-A4/A5/A6/A9)
                           B3 (post-A7+A8+B1+B2+B4)   ← the big integrator
                           B5 (post-B3)
Wave 5 (surface + gate)    C1 (post engine) · D1 (post everything)
```

- **Engine (A) parallelizes** once `A1` lands — A2/A6/A8 are independent of A3's book; A4/A5/A7/A9 chain off A3.
- **B3 (morgan)** is the integration keystone — schedule it after every engine capability it orchestrates exists.
- **D1** is the final go/no-go: dry-run on a paper book for several days, confirm report + position-mgmt quality, **then** connect the User's real book (PRD Stage D).

This maps to PRD-002 §"遷移計畫": **Stage A = EPIC A (+C engine)**, **Stage B = EPIC B**, **Stage C = B5 (cron→manual)**, **Stage D = D1**.

---

## 5. Global Definition of Done (every ticket)

A ticket is complete only when **all** hold:

- [ ] Code matches the surrounding style (naming, lazy-import discipline, docstrings citing the §/B-id like existing modules).
- [ ] **All invariants in §2 preserved** (the ticket's invariant checklist is ticked).
- [ ] New pure logic has unit tests in `engine/tests/test_*.py`; **`./scripts/run-tests.sh` green** (currently 69+ tests — never red).
- [ ] New/changed endpoints documented in `engine/monday/manual.md` (agent-facing contract).
- [ ] Frontend changes: **`vue-tsc` clean** + `npm run build` committed to `web/dist/`.
- [ ] Backward compatible: existing 17 routers + the autonomous `pipeline.run()` still work (don't break the 1.0 path until D1 cuts over).
- [ ] Structural/strategy/roster change → one **ADR** in `docs/adr/` (decision, rationale, expected effect, when to revisit; §6.4).
- [ ] Health verified: engine boots (`python -m monday`), `/health` ok, the new endpoint returns the documented contract.
- [ ] Report back: ticket id + commit hash + test evidence (evva SOP).

---

## 6. Ticket file template

Each ticket follows: **Problem · Goal · Scope (in) · Out of scope · Design (Files / Schema / API / Pure-logic) ·
Acceptance criteria · Test plan · Invariant checklist · Risks/edge cases · Rollout notes.** Keep API request/response
shapes explicit (they are contracts). Cite the real file paths under `engine/monday/`.

---

## 7. Cross-cutting contracts (defined once, referenced by tickets)

To avoid drift across sessions, these shapes are **normative**; tickets implement against them verbatim.

- **`book_position`** (A3): `{position_id, symbol, name, direction, qty, avg_entry, opened_at, status, source, rec_id?, sizing_pct?, take_profit, stop_loss, book}`; `book ∈ {paper, real}`, `source ∈ {model, morgan, user}`, `status ∈ {open, closed}`.
- **`position_action`** (A3/A5): `{action_id, position_id|symbol, action_date, action, delta_qty, reason, decided_by, regime, prev_qty, new_qty}`; `action ∈ {open, hold, add, trim, exit}`.
- **`macro_snapshot` row** (A2): `{as_of, symbol, name, close, prev_close, chg_pct, asset_class}` per index, parquet, stamped `as_of`.
- **`macro_call`** (A9): `{call_id, call_date, risk_state, horizon_days, sectors_favored[], sectors_avoid[], by, rationale, realized_index_fwd_ret?, correct?}`; `risk_state ∈ {risk_on, neutral, risk_off}`.
- **`daily_report` v2** (A7): `{as_of, regime, risk_state, sections:{macro, market_narrative, holdings_review[], new_ideas[], exposure, risk_notes}, disclaimer}` — full schema in A7.
- **`sizing_result`** (A4): `{symbol, conviction, risk_budget_pct, atr_stop_pct, suggested_pct, suggested_qty, regime_scale, capped_by?}`.

> Changing any contract here = update this section **and** every ticket that references it, in the same commit.
