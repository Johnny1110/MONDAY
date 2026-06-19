# A4 — Position sizing engine (pure) + API

- **Epic**: A (engine foundations) · **Owner**: evva · **Size**: M
- **Status**: Proposed
- **Depends on**: A1 (config knobs + book), A3 (book value/exposure)
- **Blocks**: A7 (report shows suggested sizing), B3 (morgan sizes the book), B4 (risk-monitor owns sizing)
- **PRD ref**: PRD-002 §倉位管理 (單檔 sizing：信心度加權 × 風險預算 × regime 縮放; 整體曝險與現金); decision 4 (10% = aspiration, sizing must NOT loosen for KPI)
- **Files**: new `engine/monday/sizing.py`, `engine/monday/routers/book.py` (add endpoint) or `routers/portfolio.py`, `engine/monday/config.py`, `engine/monday/manual.md`, new `engine/tests/test_sizing.py`

## Problem

The PRD makes **position sizing** a first-class deliverable (the report's §4 carries "建議 sizing", §5 carries total exposure /
cash). 1.0 has none — `paper_positions.qty` is hard-coded to 1 (equal weight). We need deterministic, testable, calibratable
sizing: **risk-budget per trade × conviction × regime scale**, capped per name and in aggregate.

## Goal

A pure `sizing.py` (no I/O, unit-tested) plus a token-free endpoint that turns `{conviction, atr_stop_pct, price}` + book
context into a `sizing_result` (% of book + lot-rounded qty), honouring per-name and total-exposure caps and a regime scale.

## Scope (in)

- `sizing.py` pure functions (single-name + whole-book).
- One endpoint to size today's candidates against the current book.
- Config knobs (risk budget, lot size, regime scales).
- Unit tests.

## Out of scope

- Deciding *which* names to size (that's morgan/quant/analysts) — A4 sizes a given set.
- Executing fills (A3) and reviewing existing lots (A5).

## Design

### `sizing.py` (pure)

```python
def regime_scale(state: str) -> float:
    """risk_on/bull_trend→1.0, neutral→0.8, choppy→0.7, high_vol→0.5, risk_off→0.4 (start values, §6-calibratable)."""

def suggest_size(conviction, atr_stop_pct, *, risk_budget_pct, regime_state,
                 max_position_pct, book_value, price, lot_size=1000) -> dict:
    """Risk-budget sizing: a name whose stop is `atr_stop_pct` away should risk ~`risk_budget_pct` of the
    book → base_pct = risk_budget_pct / atr_stop_pct. Scale by conviction (∈[0,1]) and regime_scale; clamp
    to [0, max_position_pct]. Convert to lot-rounded qty = floor(pct% * book_value / price / lot)*lot.
    Returns sizing_result {symbol?, conviction, risk_budget_pct, atr_stop_pct, suggested_pct,
    suggested_qty, regime_scale, capped_by}."""

def size_book(candidates, *, book_value, regime_state, risk_budget_pct, max_position_pct,
              max_total_exposure_pct, max_per_sector_pct=None, lot_size=1000) -> list[dict]:
    """Size a set; if the sum of suggested_pct exceeds max_total_exposure_pct, scale all down pro-rata
    (record capped_by="total_exposure"); optional per-sector cap. Deterministic + order-stable."""
```

- `atr_stop_pct` is the stop distance as a fraction (from the rec's `stop_loss` vs entry, or `atr_14`-derived as `exits.py` does). When ATR is missing, fall back to `settings.sl_pct_floor` (consistent with `exits.py`).
- `capped_by ∈ {None, "max_position", "total_exposure", "sector"}` — transparency for the report + risk-monitor.

### Endpoint (token-free; add to `routers/book.py`)

- `POST /api/book/sizing` — body `{candidates:[{symbol, conviction, atr_stop_pct?|stop_loss?, price}], regime_state?, book_value?}` → `[sizing_result]`. `book_value` defaults to `book.exposure(...).total` (A3) or `settings.book_starting_cash`; `regime_state` defaults to today's regime/risk_state.

### Config (`config.py`)

```python
risk_budget_pct_per_trade: float = 1.0   # % of book risked if the stop is hit (decision 4: do NOT raise to chase 10%)
max_total_exposure_pct: float = 100.0    # sum of position weights cap (≤100 = no leverage; swarm never levers)
lot_size: int = 1000                     # TW board lot
# book_max_position_pct comes from A1
```

## Acceptance criteria

- Higher conviction → larger `suggested_pct` (monotone), all else equal; risk_off regime shrinks every size vs bull_trend.
- A name with a **tighter** stop (`atr_stop_pct` smaller) gets a **larger** `suggested_pct` for the same risk budget (risk-parity behaviour), but never above `max_position_pct` (`capped_by="max_position"`).
- `size_book` pro-rata scales down when total exceeds `max_total_exposure_pct` (sum of results ≤ cap; `capped_by="total_exposure"`).
- `suggested_qty` is lot-rounded (multiple of `lot_size`) and never exceeds the pct budget.
- Pure: `sizing.py` imports no engine I/O; endpoint is token-free.

## Test plan (`engine/tests/test_sizing.py`)

- `test_risk_budget_monotonicity` — conviction↑ ⇒ size↑; tighter stop ⇒ size↑.
- `test_regime_scaling` — risk_off < neutral < bull_trend for identical inputs.
- `test_caps` — per-name cap and total-exposure pro-rata cap both bind correctly; `capped_by` set.
- `test_lot_rounding` — qty is a `lot_size` multiple and ≤ budget.
- `test_missing_atr_fallback` — uses `sl_pct_floor` when atr/stop absent.

## Invariant & discipline checklist

- [ ] Pure stdlib math, unit-tested; no heavy deps (6).
- [ ] Token-free endpoint; one router module reuse (2,4).
- [ ] **Decision 4**: defaults are conservative; sizing has no "boost to hit 10%" knob — the 10% target never relaxes risk.
- [ ] No leverage path (`max_total_exposure_pct ≤ 100`; invariant 11 spirit — swarm advises a cash-real book).

## Risks / edge cases

- **Over-sizing illiquid names**: pair with risk-monitor's liquidity/`adv_20d` check (B4) — sizing alone doesn't know liquidity; document the hand-off.
- **Stale book_value**: if exposure can't be priced, fall back to `book_starting_cash` and flag it in the result.
- **Calibration**: `risk_budget_pct_per_trade`, `regime_scale` values are start points — A9 + the weekly review tune them; record changes as ADRs (§6.4).

## Rollout notes

Independent compute — safe anytime after A3. risk-monitor (B4) becomes the agent owner of sizing; morgan (B3) reads `suggested_pct` into report §4/§5.
