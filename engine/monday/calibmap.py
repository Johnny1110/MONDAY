"""Probability calibration from the ledger (§6 — the ledger is the authority).

``predicted_prob_tp`` is a raw, un-calibrated P(touch-TP) — a logistic of the model score, not a real
frequency. This fits a monotone map from realized outcomes (does a 70%-confidence idea really hit ~70%?)
so ``conviction`` — the number morgan ranks the daily book on — tells the truth. PAV isotonic regression
(monotone non-decreasing, the standard reliability calibrator); pure stdlib + unit-testable. Cold-start:
too few settled outcomes → an IDENTITY map (no correction until the ledger has something to say — never
over-fit a tiny calibration set, §6.4).

A map is a list of ``(x, y)`` knots (sorted x, non-decreasing y); ``apply`` is piecewise-linear between
knots, flat outside. ``[]`` = identity.
"""

from __future__ import annotations

IDENTITY: list = []


def fit(pairs: list[tuple[float, float]], min_samples: int = 30) -> list[list[float]]:
    """Fit a monotone calibration map from ``(predicted_prob, hit∈{0,1})`` pairs via PAV isotonic
    regression. Returns ``(x, y)`` knots, or IDENTITY when there are < ``min_samples`` usable pairs."""
    clean = [(float(p), float(h)) for p, h in pairs if p is not None and h is not None]
    if len(clean) < min_samples:
        return IDENTITY
    # Aggregate by predicted prob first (exact ties → one weighted point, so each x maps to one value),
    # then Pool Adjacent Violators: a stack of blocks (x_left, value, weight); merge while monotone breaks.
    agg: dict[float, list[float]] = {}
    for x, h in clean:
        b = agg.setdefault(x, [0.0, 0.0])
        b[0] += h
        b[1] += 1
    pts = sorted((x, s / n, n) for x, (s, n) in agg.items())
    blocks: list[list[float]] = []
    for x, v, w in pts:
        xl = x
        while blocks and blocks[-1][1] > v:
            xl0, v0, w0 = blocks.pop()
            v = (v0 * w0 + v * w) / (w0 + w)
            w += w0
            xl = xl0
        blocks.append([xl, v, w])
    return [[round(xl, 4), round(v, 4)] for xl, v, _ in blocks]


def apply(cmap: list[list[float]], p: float | None) -> float | None:
    """Map a raw probability through ``cmap`` (piecewise-linear; flat outside the knot range). Identity
    when ``cmap`` is empty. Result clamped to [0, 1]."""
    if not cmap or p is None:
        return p
    p = max(0.0, min(1.0, float(p)))
    if p <= cmap[0][0]:
        return cmap[0][1]
    if p >= cmap[-1][0]:
        return cmap[-1][1]
    for (x0, y0), (x1, y1) in zip(cmap, cmap[1:]):
        if x0 <= p <= x1:
            if x1 == x0:
                return y1
            t = (p - x0) / (x1 - x0)
            return round(max(0.0, min(1.0, y0 + t * (y1 - y0))), 4)
    return cmap[-1][1]
