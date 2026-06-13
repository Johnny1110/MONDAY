"""Pure factor math — stdlib only, unit-testable anywhere (invariant 6).

Each function takes a chronologically-ordered close (or OHLC) series and returns a float, or
``None`` when there is insufficient history. No numpy, no I/O, no config — so these are the
"same input → same output, must have a unit test" core that belongs in the platform (§2).
"""

from __future__ import annotations

import math


def total_return(closes: list[float], window: int) -> float | None:
    """Simple return over ``window`` bars (momentum). None if history is too short."""
    if len(closes) <= window or closes[-1 - window] == 0:
        return None
    return closes[-1] / closes[-1 - window] - 1.0


def sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def dist_from_high(closes: list[float], window: int) -> float | None:
    """Distance below the rolling ``window`` high (≤ 0; 0 = making new highs)."""
    if len(closes) < window:
        return None
    hi = max(closes[-window:])
    return None if hi == 0 else closes[-1] / hi - 1.0


def rsi(closes: list[float], window: int = 14) -> float | None:
    """Wilder-style RSI over the last ``window`` changes. 100 when there are no losses."""
    if len(closes) <= window:
        return None
    gains = losses = 0.0
    for i in range(len(closes) - window, len(closes)):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    rs = (gains / window) / (losses / window)
    return 100.0 - 100.0 / (1.0 + rs)


def realized_vol(closes: list[float], window: int) -> float | None:
    """Standard deviation of the last ``window`` simple returns."""
    if len(closes) <= window:
        return None
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(len(closes) - window, len(closes))]
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / len(rets)
    return math.sqrt(var)


def atr(highs: list[float], lows: list[float], closes: list[float],
        window: int = 14) -> float | None:
    """Average true range over ``window`` bars (drives the TP/SL ATR multipliers, §5.5)."""
    n = len(closes)
    if n <= window:
        return None
    trs = []
    for i in range(n - window, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs) / len(trs)
