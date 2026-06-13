"""Forward-looking labels for supervised training (whitepaper §5.1/§5.2) — pure stdlib.

For a cross-sectional rank over a ~1-month holding window H, each (symbol, date) sample's targets
come from FUTURE bars: the forward return (regressor target + the rank basis) and whether the
take-profit was touched within the window (classifier target). The look-ahead here is deliberate —
it's the label, computed only from the price panel; the FEATURES stay strictly point-in-time.
Pure + unit-tested.
"""

from __future__ import annotations


def forward_return(closes: list[float], i: int, horizon: int) -> float | None:
    """Close-to-close return from bar i to i+horizon. None if the window runs past the data."""
    if i < 0 or i + horizon >= len(closes) or closes[i] == 0:
        return None
    return closes[i + horizon] / closes[i] - 1.0


def touch_tp(closes: list[float], highs: list[float], i: int, horizon: int,
             tp_pct: float) -> int | None:
    """1 if the high touches close[i]·(1+tp_pct) on any of the next ``horizon`` bars, else 0
    (a path-aware TP-hit label, not just close-to-close). None if the window runs past the data."""
    if i < 0 or i + horizon >= len(highs) or closes[i] == 0:
        return None
    target = closes[i] * (1.0 + tp_pct)
    return 1 if max(highs[i + 1:i + horizon + 1]) >= target else 0


def quantile_buckets(values: list[float | None], n_buckets: int) -> list[int]:
    """Map values to cross-sectional integer relevance grades 0..n_buckets-1 (LambdaMART labels).
    Highest values get the top grade; None values get grade 0. Balanced by rank position."""
    present = [k for k, v in enumerate(values) if v is not None]
    grades = [0] * len(values)
    if not present:
        return grades
    order = sorted(present, key=lambda k: values[k])  # type: ignore[arg-type]
    m = len(order)
    for rank, k in enumerate(order):
        grades[k] = min(n_buckets - 1, rank * n_buckets // m)
    return grades
