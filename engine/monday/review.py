"""Daily position review (A5, §倉位管理) — pure hold/add/trim/exit policy.

Each round **every** held lot gets a decision — and this runs even on days no new ideas ship (§flow
gate "持倉檢視永遠執行"). The MECHANICAL part (TP/SL touched, ≤1-month timeout, risk-off de-risk) is a
deterministic, testable policy here; the QUALITATIVE part (thesis intact? technical break? chips
reversal? theme exhausted?) is supplied by the analysts/morgan as flags (B3/B4). Advisory only —
morgan/User execute via A3's fill endpoint; review.py never moves money. Pure stdlib, unit-tested;
thresholds live in config (§6-calibratable).

Policy is **first-match-wins and conservative** (EXIT/TRIM before ADD) so a garbage-in flag can never,
say, ADD into a broken thesis — the engine is the guardrail over the LLM's judgement.
"""

from __future__ import annotations

from . import portfolio


def _gain_pct(avg_entry, price) -> float:
    if not avg_entry or price is None:
        return 0.0
    return (price - avg_entry) / avg_entry


def review_position(pos: dict, ctx: dict, cfg: dict) -> dict:
    """``pos``: {symbol, avg_entry, qty, take_profit, stop_loss, days_held, holding_window}.
    ``ctx`` (analyst/morgan flags + price): {price, conviction, thesis_intact, technical_break,
    chips_reversal, theme_exhausted, regime_state}. Returns {symbol, action, reason, urgency,
    suggested_delta_pct, gain_pct, days_held, updated_tp, updated_sl}. Missing flags default
    conservatively (thesis_intact=True, others False) so a bare call still yields a mechanical baseline."""
    price = ctx.get("price")
    avg = pos.get("avg_entry")
    days_held = pos.get("days_held") or 0
    window = pos.get("holding_window") or cfg.get("holding_window_days", 20)
    thesis_intact = ctx.get("thesis_intact", True)
    technical_break = bool(ctx.get("technical_break"))
    chips_reversal = bool(ctx.get("chips_reversal"))
    theme_exhausted = bool(ctx.get("theme_exhausted"))
    conviction = ctx.get("conviction")
    regime = (ctx.get("regime_state") or "neutral").lower()

    tp, sl = pos.get("take_profit"), pos.get("stop_loss")
    tp_hit, sl_hit = portfolio.hit_tp_sl(tp, sl, price, price, "long")   # latest price as the day's range
    gain = _gain_pct(avg, price)
    hard_flags = sum((technical_break, chips_reversal, theme_exhausted))
    below_tp = tp is None or (price is not None and price < tp)

    # trailing stop: once up ≥ trail_to_be, raise SL to at least breakeven (avg_entry) — computed
    # independently of the action so even a HOLD tightens risk on a strong winner.
    updated_tp, updated_sl = tp, sl
    if avg and gain >= cfg.get("review_trail_to_be_pct", 0.08):
        if updated_sl is None or updated_sl < avg:
            updated_sl = avg

    if sl_hit:
        action, reason, urgency, delta = "exit", "stop-loss touched", "high", -100.0
    elif days_held >= window:
        action, reason, urgency, delta = "exit", f"timeout (held {days_held}≥{window}d)", "medium", -100.0
    elif thesis_intact is False:
        action, reason, urgency, delta = "exit", "thesis broken", "high", -100.0
    elif technical_break and chips_reversal:
        action, reason, urgency, delta = "exit", "technical break + chips reversal", "high", -100.0
    elif tp_hit:
        action, reason, urgency, delta = "trim", "take-profit touched — bank partial", "medium", -50.0
    elif regime == "risk_off" and gain >= cfg.get("review_trim_profit_pct", 0.10):
        action, reason, urgency, delta = "trim", f"risk_off — de-risk winner (+{gain:.0%})", "medium", -33.0
    elif hard_flags == 1:
        flag = ("technical_break" if technical_break else
                "chips_reversal" if chips_reversal else "theme_exhausted")
        action, reason, urgency, delta = "trim", f"one warning flag ({flag})", "medium", -33.0
    elif (thesis_intact and below_tp and conviction is not None
          and conviction >= cfg.get("review_add_conviction", 0.65)
          and regime in ("risk_on", "bull_trend")):
        action, reason, urgency, delta = "add", "strong thesis + supportive regime", "low", 25.0
    else:
        action, reason, urgency, delta = "hold", "no trigger", "low", 0.0

    return {
        "symbol": pos.get("symbol"), "action": action, "reason": reason, "urgency": urgency,
        "suggested_delta_pct": delta, "gain_pct": round(gain, 4), "days_held": days_held,
        "updated_tp": updated_tp, "updated_sl": updated_sl,
    }


def review_book(positions: list[dict], ctx_lookup: dict, cfg: dict) -> list[dict]:
    """Review every lot (order-stable); ``ctx_lookup`` maps symbol → its flags/price (missing → {})."""
    return [review_position(p, ctx_lookup.get(p.get("symbol")) or {}, cfg) for p in positions]
