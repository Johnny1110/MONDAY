"""Paper portfolio + ledger mark-to-market (whitepaper §6.1 — platform, deterministic).

Two layers, kept separate so the math is unit-testable without a database:
  * **pure functions** (``mtm_return`` / ``hit_tp_sl`` / ``settle``) — same input → same output;
  * **store-integrating ops** (``open_from_recommendation`` / ``mark_positions`` / ``summary``)
    that drive the ledger (PostgreSQL via ``store``).
No real money ever (cardinal discipline 2 / whitepaper §9): a "position" is a bookkeeping row.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import store


# --------------------------------------------------------------------------
# Pure mark-to-market math (unit-tested; no I/O)
# --------------------------------------------------------------------------

def mtm_return(entry: float, price: float, direction: str = "long") -> float:
    """Mark-to-market return of a position. Long: (price-entry)/entry; short: the negative."""
    if entry == 0:
        return 0.0
    r = (price - entry) / entry
    return r if direction == "long" else -r


def hit_tp_sl(tp: float | None, sl: float | None, high: float | None, low: float | None,
              direction: str = "long") -> tuple[bool, bool]:
    """Did the day's range touch the take-profit / stop-loss? Long checks high≥TP, low≤SL;
    short is mirrored (low≤TP, high≥SL)."""
    if direction == "long":
        return (high is not None and tp is not None and high >= tp,
                low is not None and sl is not None and low <= sl)
    return (low is not None and tp is not None and low <= tp,
            high is not None and sl is not None and high >= sl)


def settle(entry: float, exit_price: float, predicted_return: float | None,
           direction: str = "long", reason: str = "timeout", cost: float = 0.0) -> dict:
    """Final settlement record for an exited idea (error = realized − predicted, §6.1). ``cost`` is the
    round-trip transaction cost in return space (broker + tax + slippage) — ``realized`` is NET of it, and
    ``hit`` means we actually profited after costs (honest paper P&L)."""
    realized = mtm_return(entry, exit_price, direction) - cost
    return {
        "realized_return": round(realized, 4),
        "hit": realized > 0,
        "exit_reason": reason,
        "error": round(realized - (predicted_return or 0.0), 4),
    }


def _days_between(d1: str, d2: str) -> int:
    try:
        return (date.fromisoformat(d2) - date.fromisoformat(d1)).days
    except ValueError:
        return 0


# --------------------------------------------------------------------------
# Store-integrating ops
# --------------------------------------------------------------------------

def open_from_recommendation(rec: dict) -> None:
    """Open a paper position from a freshly-written recommendation (entry = entry_ref_price)."""
    store.open_position(rec["rec_id"], rec["symbol"], rec.get("direction", "long"),
                        rec["entry_ref_price"], rec["as_of_date"])


def mark_positions(mark_date: str, bar_lookup: dict[str, dict],
                   window_days: int, cost_pct: float = 0.0) -> dict:
    """Mark every OPEN position at ``mark_date`` and settle on TP/SL/timeout.

    ``bar_lookup`` maps symbol → {close, high, low}. SL takes precedence over TP when both are
    touched the same day (conservative). ``cost_pct`` nets the round-trip transaction cost out of both the
    daily mark and the settled return, so the ledger + equity curve are honest. Returns {marked, settled}.
    """
    marked = settled = 0
    for pos in store.list_positions(status="open"):
        bar = bar_lookup.get(pos["symbol"])
        if not bar:
            continue
        rec = store.get_recommendation(pos["rec_id"]) or {}
        entry, direction = pos["entry_price"], pos["direction"]
        r = mtm_return(entry, bar["close"], direction) - cost_pct       # net of cost (honest)
        tp_hit, sl_hit = hit_tp_sl(rec.get("take_profit_price"), rec.get("stop_loss_price"),
                                   bar.get("high"), bar.get("low"), direction)
        days_held = _days_between(pos["entry_date"], mark_date)
        store.add_mark({
            "rec_id": pos["rec_id"], "mark_date": mark_date, "close_price": bar["close"],
            "mtm_return": round(r, 4), "max_favorable": round(max(r, 0.0), 4),
            "max_adverse": round(min(r, 0.0), 4), "tp_hit": tp_hit, "sl_hit": sl_hit,
            "days_held": days_held,
        })
        marked += 1

        # Entry is executed at the as_of close, so the entry bar's own intraday high/low must
        # NOT trigger TP/SL (that range happened before the fill) — the first settlement
        # opportunity is the next session. day0 just records the mark (mtm ≈ 0).
        reason = exit_price = None
        if days_held >= 1:
            if sl_hit:
                reason, exit_price = "sl", rec.get("stop_loss_price")
            elif tp_hit:
                reason, exit_price = "tp", rec.get("take_profit_price")
            elif days_held >= window_days:
                reason, exit_price = "timeout", bar["close"]
        if reason:
            oc = settle(entry, exit_price, rec.get("predicted_return"), direction, reason, cost=cost_pct)
            oc.update({"rec_id": pos["rec_id"], "exit_date": mark_date,
                       "exit_price": exit_price, "tp_hit": reason == "tp",
                       "sl_hit": reason == "sl"})
            store.add_outcome(oc)
            store.close_position(pos["rec_id"])
            settled += 1
    return {"marked": marked, "settled": settled}


def summary() -> dict:
    """Portfolio scorecard from the ledger: open/closed counts + realized win stats."""
    open_pos = store.list_positions(status="open")
    outcomes = store.list_outcomes()
    realized = [o["realized_return"] for o in outcomes if o.get("realized_return") is not None]
    wins = [r for r in realized if r > 0]
    return {
        "open": len(open_pos),
        "closed": len(outcomes),
        "win_rate": round(len(wins) / len(realized), 4) if realized else None,
        "avg_realized": round(sum(realized) / len(realized), 4) if realized else None,
    }


# --------------------------------------------------------------------------
# Real equity curve + performance (Imp #3) — replaces the "mean mtm per day" proxy
# --------------------------------------------------------------------------

def equity_curve(marks: list[dict], base: float = 1.0) -> list[dict]:
    """An equal-weight, daily-marked book NAV (pure). Each position's cumulative ``mtm_return`` is
    differenced into daily increments (day0 ≈ 0, so entry doesn't jump the curve); the portfolio's daily
    return is the mean increment across the positions marked that day; NAV compounds from ``base``. A
    settled name simply stops contributing after its exit mark. Returns ``[{date, equity, ret, drawdown}]``
    (``equity`` = NAV; ``drawdown`` ≤ 0). This is a real NAV — the ``portfolio_drawdown`` trigger and the
    dashboard curve both read it (vs. the old "1 + mean mtm" proxy that never compounded)."""
    by_rec: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for m in marks:
        if m.get("mtm_return") is not None:
            by_rec[m["rec_id"]].append((m["mark_date"], m["mtm_return"]))
    daily: dict[str, list[float]] = defaultdict(list)
    for series in by_rec.values():
        series.sort()
        prev = 0.0
        for d, cum in series:
            daily[d].append(cum - prev)        # daily increment in return space
            prev = cum
    out, nav, peak = [], base, base
    for d in sorted(daily):
        rets = daily[d]
        r = sum(rets) / len(rets) if rets else 0.0
        nav *= 1 + r
        peak = max(peak, nav)
        out.append({"date": d, "equity": round(nav, 4), "ret": round(r, 4),
                    "drawdown": round((nav - peak) / peak, 4) if peak else 0.0})
    return out


def current_drawdown_pct(marks: list[dict]) -> float:
    """The book's CURRENT peak-to-now drawdown as a positive percent (0 if flat/empty) — drives the risk
    gate's graduated throttle (Imp #3)."""
    curve = equity_curve(marks)
    return round(abs(curve[-1]["drawdown"]) * 100, 2) if curve else 0.0


def performance(curve: list[dict]) -> dict:
    """Headline metrics from an equity curve (pure): cumulative return (vs base 1.0), max drawdown,
    daily-return vol, and an annualized Sharpe (rf=0, 252d). All None on an empty curve."""
    if not curve:
        return {"days": 0, "cum_return": None, "max_drawdown": None, "vol": None, "sharpe": None}
    rets = [p["ret"] for p in curve]
    mean_r = sum(rets) / len(rets)
    vol = (sum((x - mean_r) ** 2 for x in rets) / len(rets)) ** 0.5
    return {
        "days": len(curve),
        "cum_return": round(curve[-1]["equity"] - 1.0, 4),
        "max_drawdown": round(min(p["drawdown"] for p in curve), 4),
        "vol": round(vol, 4),
        "sharpe": round(mean_r / vol * (252 ** 0.5), 3) if vol else None,
    }
