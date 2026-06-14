"""Market-regime classifier (whitepaper §5.3) — pure stdlib.

The model's edge is regime-dependent (§9 risk #6), so each day is labelled by the market's state,
read off an equal-weight index built from the analysable universe: trend (index return over a
window), breadth (share of names in positive momentum), and realized volatility. P2 ships the
rule-based classifier the whitepaper explicitly permits ("HMM 或簡單規則 + 分類器"); the per-style
ensemble that WEIGHTS by this label is the next increment. Thresholds are start values —
calibratable like everything (§6). Stamped on every recommendation so reviewer-calibrator's
per-regime attribution (§6.4) becomes meaningful instead of a single "neutral" bucket.
"""

from __future__ import annotations

import math

from .featurestore import factors

LABELS = ("bull_trend", "choppy", "risk_off", "high_vol", "neutral")


def market_index(bars: list[dict]) -> dict[str, float]:
    """Equal-weight index as {date: level}: the mean across symbols of close/first_close, so every
    name contributes its return path rather than its price scale."""
    by_sym: dict[str, list[tuple[str, float]]] = {}
    for b in sorted(bars, key=lambda x: x["date"]):
        by_sym.setdefault(b["symbol"], []).append((b["date"], b["close"]))
    per_date: dict[str, list[float]] = {}
    for series in by_sym.values():
        base = series[0][1] or 1.0
        for d, c in series:
            per_date.setdefault(d, []).append(c / base)
    return {d: sum(v) / len(v) for d, v in sorted(per_date.items())}


def _trend(levels: dict[str, float], window: int) -> float | None:
    ds = sorted(levels)
    if len(ds) <= window or levels[ds[-1 - window]] == 0:
        return None
    return levels[ds[-1]] / levels[ds[-1 - window]] - 1.0


def _vol(levels: dict[str, float], window: int) -> float | None:
    ds = sorted(levels)
    if len(ds) <= window:
        return None
    rets = [levels[ds[i]] / levels[ds[i - 1]] - 1.0 for i in range(len(ds) - window, len(ds))]
    m = sum(rets) / len(rets)
    return math.sqrt(sum((r - m) ** 2 for r in rets) / len(rets))


def breadth(bars: list[dict], as_of: str, window: int = 20) -> float | None:
    """Share of symbols with positive ``window``-day momentum as of ``as_of``."""
    by_sym: dict[str, list[float]] = {}
    for b in sorted(bars, key=lambda x: x["date"]):
        if b["date"] <= as_of:
            by_sym.setdefault(b["symbol"], []).append(b["close"])
    pos = tot = 0
    for closes in by_sym.values():
        m = factors.total_return(closes, window)
        if m is not None:
            tot += 1
            pos += 1 if m > 0 else 0
    return pos / tot if tot else None


def classify(trend: float | None, brd: float | None, vol: float | None, *,
             vol_hi: float = 0.03, trend_up: float = 0.03, trend_dn: float = -0.03,
             breadth_hi: float = 0.6, breadth_lo: float = 0.4) -> str:
    """Map (trend, breadth, vol) → regime label. High volatility overrides; then a trending-and-
    broad market is bull/risk_off, otherwise choppy. ``neutral`` when there's too little history."""
    if vol is not None and vol > vol_hi:
        return "high_vol"
    if trend is None or brd is None:
        return "neutral"
    if trend <= trend_dn and brd < breadth_lo:
        return "risk_off"
    if trend >= trend_up and brd > breadth_hi:
        return "bull_trend"
    return "choppy"


def regime_for(bars: list[dict], as_of: str, trend_window: int = 60,
               vol_window: int = 20) -> str:
    """Classify the regime as of ``as_of`` from the price panel (bars at or before ``as_of``)."""
    visible = [b for b in bars if b["date"] <= as_of]
    levels = market_index(visible)
    return classify(_trend(levels, trend_window), breadth(bars, as_of), _vol(levels, vol_window))
