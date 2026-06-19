# A5 — Daily position-review engine (pure) + API

- **Epic**: A (engine foundations) · **Owner**: evva · **Size**: M
- **Status**: Proposed
- **Depends on**: A1 (position_actions), A3 (book/holdings)
- **Blocks**: A7 (report §3 持倉檢視), B3 (morgan's book review), B4 (risk-monitor)
- **PRD ref**: PRD-002 §倉位管理 (每日持倉檢視：hold/add/trim/exit 的依據), §flow (SYNC B (B) 持倉檢視; "持倉檢視永遠執行"); whitepaper §5.5 (exits)
- **Files**: new `engine/monday/review.py`, `engine/monday/routers/book.py` (add endpoint), `engine/monday/config.py`, `engine/monday/manual.md`, new `engine/tests/test_review.py`

## Problem

2.0 manages a live book: each round, **every** held lot needs a hold/add/trim/exit decision — and the PRD says this runs
**even on days no new ideas ship**. The mechanical part (TP/SL touched, timeout at the ≤1-month window, exposure under risk-off)
must be a **deterministic, testable policy**; the qualitative part (thesis intact? technical break? chips reversal? theme played
out?) is supplied by the analysts/morgan as **flags**. A5 encodes the policy so the recommendation is reproducible and calibratable.

## Goal

A pure `review.py` that maps `(position state + qualitative flags + regime)` → a recommended action with reason, urgency, and
updated TP/SL; plus a token-free endpoint that produces a review for the whole open book. **Advisory** — morgan/User act on it
(executed via A3's `/api/book/fill`); A5 never moves money.

## Scope (in)

- `review.py` pure decision rules (single position + whole book).
- An endpoint that assembles mechanical context (price/tp/sl/days from book + marks) and accepts qualitative flags, returning per-position recommendations.
- Config thresholds; tests for every branch.

## Out of scope

- Executing the action (A3 `/api/book/fill`) and sizing adds (A4).
- The LLM judgement that *produces* the flags (that's a-tech/a-chips/a-catalyst + morgan, B3/B4).

## Design

### `review.py` (pure)

```python
def review_position(pos, ctx, cfg) -> dict:
    """pos: {symbol, avg_entry, qty, take_profit, stop_loss, days_held, holding_window}.
    ctx (flags/scores morgan+analysts supply): {price, model_score, conviction, thesis_intact,
       technical_break, chips_reversal, theme_exhausted, regime_state}.
    Returns {symbol, action, reason, urgency, suggested_delta_pct, updated_tp, updated_sl}.
    Policy (first match wins, conservative):
      EXIT  if sl touched | days_held≥window (timeout) | thesis_intact is False
            | (technical_break AND chips_reversal)
      TRIM  if tp touched (take partial) | (regime_state risk_off AND held in profit)
            | exactly one hard flag (technical_break XOR chips_reversal XOR theme_exhausted)
      ADD   if thesis_intact AND price<take_profit AND conviction≥add_conv AND regime_state in {risk_on,bull_trend}
      HOLD  otherwise.
    urgency ∈ {high,medium,low}; updated_tp/sl trail on strong holds (e.g. raise SL to breakeven after +X%)."""

def review_book(positions, ctx_lookup, cfg) -> list[dict]
```

- Reuse `portfolio.hit_tp_sl` semantics for "touched"; `days_held` from `book_positions.opened_at` vs `as_of`.
- Trailing-stop helper (raise SL toward entry after a configurable gain) — small, testable.

### Endpoint (token-free; add to `routers/book.py`)

- `POST /api/book/review` — body `{as_of?, context:{<symbol>:{flags+score+price}}}`. The engine fills mechanical fields (avg_entry, tp/sl, days_held) from `book_positions` + latest `ledger_marks`/price; merges the caller's qualitative flags; returns `[review]` for the open book. Missing flags default conservatively (`thesis_intact=True`, others `False`) so a bare call still gives a mechanical baseline.
- `GET /api/book/review` — mechanical-only baseline (no flags) for the dashboard / a quick check.

### Config (`config.py`)

```python
review_trim_profit_pct: float = 0.10   # take partial when up ≥ this near TP
review_add_conviction: float = 0.65    # min conviction to recommend adding
review_trail_to_be_pct: float = 0.08   # raise SL toward breakeven after +this
```

## Acceptance criteria

- SL-touched / timeout / `thesis_intact=False` each yield **EXIT** with the correct reason.
- TP-touched yields **TRIM** (partial) with `suggested_delta_pct` < 100; risk_off + in-profit yields **TRIM**.
- `thesis_intact=True` + high conviction + supportive regime + below TP yields **ADD** (with a sane `suggested_delta_pct`).
- Default inputs (no flags) never crash and yield a sensible mechanical baseline.
- Deterministic + order-stable; pure (no DB import in `review.py`).
- Endpoint runs on the **whole open book** and returns one decision per lot — including on a "no new ideas" day.

## Test plan (`engine/tests/test_review.py`)

- One test per branch: `test_exit_on_sl`, `test_exit_on_timeout`, `test_exit_on_broken_thesis`, `test_trim_on_tp`, `test_trim_on_risk_off`, `test_add_on_strong_thesis`, `test_hold_default`.
- `test_trailing_stop` — SL raised toward breakeven after the gain threshold.
- `test_review_book` — mixed book returns the right action per lot, order-stable.

## Invariant & discipline checklist

- [ ] Pure deterministic policy, fully unit-tested (6); thresholds in `config.py`, calibratable (§6).
- [ ] Token-free endpoint; advisory only — actions execute via A3, morgan/User decide (10, 11).
- [ ] "持倉檢視永遠執行": endpoint independent of whether new ideas shipped that day (PRD §flow gate note).

## Risks / edge cases

- **Conflicting flags** (e.g. add-worthy conviction but technical_break): policy order resolves it (EXIT/TRIM before ADD) — document precedence.
- **Garbage-in flags**: the LLM supplies flags; the engine policy is the guardrail (e.g. never ADD into a broken thesis). Keep the policy conservative.
- **Calibration loop**: A9 scores whether trims/exits added value; the weekly review tunes these thresholds via ADR.

## Rollout notes

Safe after A3. Feeds report §3 (A7) and B3/B4. The mechanical baseline is usable immediately; the qualitative flags arrive once B4 (analysts) cover holdings.
