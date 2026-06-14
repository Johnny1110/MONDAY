"""Chip / institutional-flow factors (whitepaper §4.3 籌碼) — pure stdlib, unit-tested.

Taiwan is a retail market, so chips are a major alpha source (§5.6): the institutional desks'
net flow, its persistence (streak), and margin/short-balance dynamics. Pure functions over the
per-date chip series; the FinMind ingest assembles the series, these turn it into PIT factors.
"""

from __future__ import annotations


def net_sum(nets: list[float], window: int) -> float | None:
    """Net flow summed over the last ``window`` days (None if no data)."""
    return float(sum(nets[-window:])) if nets else None


def net_streak(nets: list[float]) -> int:
    """Signed count of consecutive trailing same-direction net days: +k buying, -k selling."""
    if not nets or nets[-1] == 0:
        return 0
    sign = 1 if nets[-1] > 0 else -1
    n = 0
    for v in reversed(nets):
        if v != 0 and (v > 0) == (sign > 0):
            n += 1
        else:
            break
    return sign * n


def balance_change(bals: list[float], window: int) -> float | None:
    """Fractional change in a balance series over ``window`` days (margin/short dynamics)."""
    if len(bals) <= window or bals[-1 - window] == 0:
        return None
    return bals[-1] / bals[-1 - window] - 1.0


def chip_factors(inst: list[dict], margin: list[dict], as_of: str, window: int = 5) -> dict:
    """PIT chip factors as of ``as_of`` from the institutional + margin series (≤ as_of only)."""
    inst = sorted((r for r in inst if r["date"] <= as_of), key=lambda x: x["date"])
    margin = sorted((r for r in margin if r["date"] <= as_of), key=lambda x: x["date"])
    fnets = [r["foreign_net"] for r in inst]
    inets = [r["invtrust_net"] for r in inst]
    mbal = [r["margin_balance"] for r in margin]
    sbal = [r["short_balance"] for r in margin]
    return {
        "foreign_net_5d": net_sum(fnets, window),
        "foreign_streak": net_streak(fnets),
        "invtrust_net_5d": net_sum(inets, window),
        "invtrust_streak": net_streak(inets),
        "margin_chg_5d": balance_change(mbal, window),
        "short_chg_5d": balance_change(sbal, window),
    }
