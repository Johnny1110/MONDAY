"""Position sizing (A4, §倉位管理) — pure, deterministic, calibratable.

**Risk-budget sizing**: a trade whose stop sits ``atr_stop_pct`` away should risk about
``risk_budget_pct`` of the book if the stop is hit → base weight = ``risk_budget_pct / atr_stop_pct``
(risk parity — a tighter stop earns a larger position for the same dollar risk). That base is scaled by
conviction ∈ [0,1] and a regime scale, then clamped per-name and, across a book, to a total-exposure cap.
There is **no leverage path and no "boost to hit 10%" knob** — decision 4: the monthly target never
relaxes risk. Pure stdlib (no I/O), unit-tested.

Units: ``risk_budget_pct`` / ``*_pct`` / ``suggested_pct`` are **percent of book** (1.0 = 1%);
``atr_stop_pct`` is a **fraction** (0.05 = a 5% stop).
"""

from __future__ import annotations

import math

# Start values (§6-calibratable): shrink new-position size as the regime turns hostile. Accepts both the
# regime labels (regime.py) and the macro risk_state vocabulary (A2/A9), mapped to the same scale.
_REGIME_SCALE = {
    "risk_on": 1.0, "bull_trend": 1.0,
    "neutral": 0.8,
    "choppy": 0.7,
    "high_vol": 0.5,
    "risk_off": 0.4,
}


def regime_scale(state: str | None) -> float:
    """The regime/risk-state size multiplier; unknown/None → neutral (0.8)."""
    return _REGIME_SCALE.get((state or "neutral").lower(), 0.8)


def stop_pct(atr_stop_pct: float | None = None, stop_loss: float | None = None,
             price: float | None = None, floor: float = 0.04) -> float:
    """Resolve the stop distance as a fraction: explicit ``atr_stop_pct``, else derived from a
    ``stop_loss`` vs ``price`` (long), else the conservative ``floor`` (consistent with exits.py when ATR
    is missing). Always returns a positive fraction."""
    if atr_stop_pct:
        return float(atr_stop_pct)
    if stop_loss and price and float(price) > 0:
        d = (float(price) - float(stop_loss)) / float(price)
        if d > 0:
            return d
    return floor


def _lot_qty(pct: float, book_value: float | None, price: float | None, lot_size: int) -> int:
    """Lot-rounded share qty for ``pct`` % of ``book_value`` at ``price`` (floored to a lot multiple, so
    it never exceeds the pct budget). 0 when price/book is unknown."""
    if not (price and price > 0 and book_value and book_value > 0):
        return 0
    return int(math.floor((pct / 100.0 * book_value) / price / lot_size) * lot_size)


def suggest_size(conviction, atr_stop_pct, *, risk_budget_pct, regime_state,
                 max_position_pct, book_value, price, lot_size: int = 1000) -> dict:
    """Size ONE name. ``base = risk_budget_pct / atr_stop_pct``, scaled by conviction and the regime,
    clamped to ``max_position_pct``. Returns a ``sizing_result``: ``{conviction, risk_budget_pct,
    atr_stop_pct, regime_scale, suggested_pct, suggested_qty, capped_by}`` with
    ``capped_by ∈ {None, "max_position", "total_exposure", "sector"}``."""
    conv = max(0.0, min(1.0, float(conviction if conviction is not None else 0.0)))
    stop = float(atr_stop_pct) if atr_stop_pct else 0.0
    scale = regime_scale(regime_state)
    base_pct = (risk_budget_pct / stop) if stop > 0 else 0.0
    pct = base_pct * conv * scale
    capped_by = None
    if pct > max_position_pct:
        pct, capped_by = max_position_pct, "max_position"
    pct = max(0.0, pct)
    return {
        "conviction": round(conv, 4),
        "risk_budget_pct": risk_budget_pct,
        "atr_stop_pct": round(stop, 4) if stop else None,
        "regime_scale": scale,
        "suggested_pct": round(pct, 4),
        "suggested_qty": _lot_qty(pct, book_value, price, lot_size),
        "capped_by": capped_by,
    }


def size_book(candidates: list[dict], *, book_value, regime_state, risk_budget_pct,
              max_position_pct, max_total_exposure_pct, max_per_sector_pct=None,
              lot_size: int = 1000) -> list[dict]:
    """Size a set of candidates (each ``{symbol, conviction, atr_stop_pct, price, sector?}``).
    Applies per-name caps, then an optional per-sector cap, then a total-exposure pro-rata scale-down
    when the summed weight exceeds ``max_total_exposure_pct`` (no leverage). Deterministic + order-stable;
    qty is recomputed after any scaling so it always matches the final ``suggested_pct``."""
    results = []
    for c in candidates:
        r = suggest_size(c.get("conviction"), c.get("atr_stop_pct"),
                         risk_budget_pct=risk_budget_pct, regime_state=regime_state,
                         max_position_pct=max_position_pct, book_value=book_value,
                         price=c.get("price"), lot_size=lot_size)
        r["symbol"] = c.get("symbol")
        r["sector"] = c.get("sector")
        r["_price"] = c.get("price")
        results.append(r)

    if max_per_sector_pct:                          # pro-rata within any over-weight sector
        by_sector: dict[str, list[dict]] = {}
        for r in results:
            by_sector.setdefault(r.get("sector") or "unknown", []).append(r)
        for rows in by_sector.values():
            sec_total = sum(r["suggested_pct"] for r in rows)
            if sec_total > max_per_sector_pct and sec_total > 0:
                f = max_per_sector_pct / sec_total
                for r in rows:
                    r["suggested_pct"] = round(r["suggested_pct"] * f, 4)
                    r["capped_by"] = r["capped_by"] or "sector"

    total = sum(r["suggested_pct"] for r in results)
    if max_total_exposure_pct and total > max_total_exposure_pct and total > 0:
        f = max_total_exposure_pct / total
        for r in results:
            r["suggested_pct"] = round(r["suggested_pct"] * f, 4)
            r["capped_by"] = r["capped_by"] or "total_exposure"

    for r in results:                               # qty reflects the FINAL pct (after scaling)
        r["suggested_qty"] = _lot_qty(r["suggested_pct"], book_value, r.pop("_price"), lot_size)
    return results
