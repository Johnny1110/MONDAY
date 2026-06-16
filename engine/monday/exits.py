"""Take-profit / stop-loss prices (whitepaper §5.5 — calibratable, Imp #2).

A fixed ±8% band ignores each name's volatility: an 8% stop whipsaws a high-ATR small-cap and is too loose
on a calm large-cap. Scale the stop to ATR so the exit reflects *intended* risk per name; keep the TP at
the model's expected return but floored. Pure stdlib + unit-testable. Falls back to the fixed band when
ATR is unavailable (thin history) — so a missing factor never breaks the book.
"""

from __future__ import annotations


def tp_sl_prices(entry: float, predicted_return: float | None, atr: float | None,
                 direction: str = "long", *, sl_atr_mult: float = 2.0, tp_atr_mult: float = 3.0,
                 tp_floor_pct: float = 0.08, sl_pct_floor: float = 0.04, sl_pct_cap: float = 0.15,
                 fixed_sl_pct: float = 0.08) -> tuple[float, float, str]:
    """Return ``(take_profit_price, stop_loss_price, basis)`` where ``basis`` ∈ {"atr", "fixed"}.

    ATR path: SL distance = ``sl_atr_mult × atr/entry`` clamped to ``[sl_pct_floor, sl_pct_cap]``;
    TP distance = ``max(predicted_return, tp_atr_mult × atr/entry, tp_floor_pct)``.
    Fallback (atr None/≤0 or entry≤0): SL = ``fixed_sl_pct``, TP = ``max(predicted_return, tp_floor_pct)``
    — i.e. the original fixed ±8% behaviour exactly.
    """
    pr = predicted_return or 0.0
    if atr and atr > 0 and entry > 0:
        sl_pct = min(sl_pct_cap, max(sl_pct_floor, sl_atr_mult * atr / entry))
        tp_pct = max(pr, tp_atr_mult * atr / entry, tp_floor_pct)
        basis = "atr"
    else:
        sl_pct, tp_pct, basis = fixed_sl_pct, max(pr, tp_floor_pct), "fixed"
    if direction == "long":
        return round(entry * (1 + tp_pct), 2), round(entry * (1 - sl_pct), 2), basis
    return round(entry * (1 - tp_pct), 2), round(entry * (1 + sl_pct), 2), basis
