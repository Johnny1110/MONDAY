# A7 — Daily report v2 (6-section) + Telegram + contract

- **Epic**: A (engine foundations) · **Owner**: evva · **Size**: M
- **Status**: Proposed
- **Depends on**: A1 (daily_report table), A2 (macro facts), A3 (holdings/exposure), A4 (sizing), A5 (holdings review)
- **Blocks**: B3 (morgan composes & posts it), C1 (dashboard report view)
- **PRD ref**: PRD-002 §完整的每日 workflow (每日報告 6 段結構), §風險與誠實聲明 (disclaimer), §"cross-cutting contracts" (daily_report v2)
- **Files**: new `engine/monday/report.py`, `engine/monday/routers/reports.py`, `engine/monday/telegram.py`, `engine/monday/manual.md`, new `engine/tests/test_report.py`

## Problem

1.0 reports are a flat `{title, body, kind}`. 2.0's deliverable to the User is a **structured 6-section daily report**
(宏觀定調 / 台股盤勢與新敘事 / 持倉檢視 / 今日新標的 / 倉位與曝險 / 風險提醒). Most **quantitative facts** are
engine-computable (macro numbers, holdings MTM + review action, new ideas with sizing/TP/SL, exposure); the **prose**
(macro read, narrative, rationale, invalidation) is morgan/analyst judgement. A7 builds the factual scaffold, accepts
morgan's prose, validates the whole against the contract, persists it, and pushes it (Telegram + dashboard) with the disclaimer.

## Goal

A `report.py` + `/api/reports/daily*` that (a) serves morgan a **scaffold** of computed facts, (b) accepts the **composed**
6-section report, validates + stores it in `daily_report`, renders `summary_text`, and fires Telegram — all token-free.

## Scope (in)

- `report.py` — `build_scaffold(as_of)` (computed facts) + `validate_report(payload)` + `render_text(report)`.
- `routers/reports.py` — `GET /api/reports/daily/scaffold`, `POST /api/reports/daily`, `GET /api/reports/daily`.
- `telegram.format_daily_report(report)` — concise phone render of the 6 sections + disclaimer.
- manual + tests. Keep the existing generic `/api/reports` endpoints unchanged.

## Out of scope

- The prose itself (morgan/analysts produce it, B3).
- Pushing to the swarm (this is the User channel, invariant 8b).

## Design

### Contract (`daily_report` v2 — normative, from overview §7)

```json
{
  "as_of": "2026-06-19", "regime": "bull_trend", "risk_state": "risk_on",
  "sections": {
    "macro":            {"risk_state":"risk_on", "overnight":[{"symbol":"^SOX","name":"費半","chg_pct":1.8}], "read":"<prose>"},
    "market_narrative": {"regime":"bull_trend","hot_sectors":["半導體"],"new_narratives":["矽光子"],"stance":"進攻","read":"<prose>"},
    "holdings_review":  [{"symbol":"2330","name":"台積電","qty":2000,"avg_entry":1080,"price":1120,"mtm_pct":3.7,"action":"hold","reason":"<prose>","updated_tp":1180,"updated_sl":1060}],
    "new_ideas":        [{"symbol":"3661","name":"世芯","direction":"long","entry_ref":3200,"take_profit":3520,"stop_loss":3000,"suggested_pct":6.0,"suggested_qty":1000,"conviction":0.71,"rationale":"<prose>","risk_notes":"<prose>"}],
    "exposure":         {"gross_pct":72,"net_pct":72,"cash_pct":28,"by_sector":{"半導體":40},"target_exposure_pct":75},
    "risk_notes":       {"events":["台積電法說 6/20"],"landmines":[],"invalidation":"<what flips the view>"}
  },
  "disclaimer": "研究意見，下單與盈虧 User 自負（swarm 不下單）。"
}
```

### `report.py`

```python
def build_scaffold(as_of) -> dict:
    """Engine-computed facts morgan fills prose into:
      macro.overnight  ← macro.read_macro_snapshot (A2)
      holdings_review  ← book.list_book + latest marks/price → qty/avg_entry/price/mtm_pct + review.review_book mechanical baseline (A5)
      new_ideas        ← signals_today candidates + sizing.suggest_size (A4) (prose blank for morgan)
      exposure         ← book.exposure (A3)
    Returns the contract shell with prose fields empty."""
def validate_report(payload) -> list[str]   # [] when valid; messages naming missing/!typed sections (used by POST 422)
def render_text(report) -> str              # plain-text/markdown summary for daily_report.summary_text + dashboard fallback
```

### Endpoints (token-free; `routers/reports.py`)

- `GET /api/reports/daily/scaffold?as_of=` — the computed facts (morgan reads, fills prose).
- `POST /api/reports/daily` — body = the v2 contract. `validate_report` → 422 on a malformed report. Persist via `store.add_daily_report`; `render_text` → `summary_text`; also `store.add_report(kind="recommendation")` for the generic feed (back-compat); fire `telegram.send(format_daily_report(...))` (no-op if unset). Returns the stored report.
- `GET /api/reports/daily?as_of=` — the latest structured report for the day (dashboard + audit).

### `telegram.format_daily_report(report)`

6 short blocks (macro one-liner → stance → holdings actions → top new ideas with TP/SL/size → exposure → risk one-liner), ending with the disclaimer. Reuse `send`/`enabled`; never raise (invariant 8).

## Acceptance criteria

- `GET /api/reports/daily/scaffold` returns macro/holdings/new-ideas/exposure facts pulled from A2/A3/A4/A5 (prose fields empty), even on a "no new ideas" day (holdings_review still populated).
- `POST /api/reports/daily` rejects a report missing a section/disclaimer (422 with which); on success stores it, sets `summary_text`, and (when Telegram configured) sends a message; returns the stored row.
- `GET /api/reports/daily` returns the persisted v2 report; the **disclaimer is always present** (invariant 11).
- Existing `/api/reports` (generic) endpoints unchanged.
- Telegram unconfigured → `POST` still succeeds (no-op send).

## Test plan (`engine/tests/test_report.py`)

- `test_build_scaffold` — with seeded book + macro snapshot + signals, scaffold has correct holdings MTM + exposure + new-idea sizing.
- `test_validate_report` — missing section / missing disclaimer flagged; valid passes.
- `test_render_text` — all six sections + disclaimer appear.
- `test_post_daily_persists_and_renders` — POST stores, `GET /daily` round-trips, `summary_text` set.
- `test_telegram_format_daily` — concise, includes disclaimer; no-op when unconfigured (monkeypatch `enabled`).

## Invariant & discipline checklist

- [ ] **Disclaimer mandatory** in every stored/pushed report (invariant 11, §風險聲明).
- [ ] Token-free; one reports router; lists paginated where applicable (2,3,4).
- [ ] Telegram fire-and-forget, no-op unset, never raises (8).
- [ ] Scaffold computed deterministically; pure shaping unit-tested (6).

## Risks / edge cases

- **Prose injection**: morgan composes prose from analyst input which itself derives from external news/podcast — the *report* is internal, but keep the injection discipline upstream (B1/B2/B4). No raw external text is executed.
- **Partial day** (GATE 1/GATE 2 blocked new ideas): report still ships holdings_review + macro + a clear "今日不發新標的" note in `new_ideas` (empty) — never a blank report.

## Rollout notes

Lands after A2–A5. B3 makes morgan call scaffold → compose → `POST /api/reports/daily` as the round's final step. C1 renders it.
