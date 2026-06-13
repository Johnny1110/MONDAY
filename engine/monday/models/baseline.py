"""The P0 baseline ("empty") model — pure stdlib, untrained, fully transparent.

Frames the problem as a CROSS-SECTIONAL RANK (§5.1): score every name by the equal-weighted
z-score of its momentum factors, sort, and derive a bounded expected return and a (provisional)
take-profit probability. There is NO training and NO learned weight here — that is the point of
"empty model" in P0; it exists only to give the rest of the chain a real ranking to carry. The
``predicted_prob_tp`` is deliberately a raw logistic (un-calibrated) so the calibration ledger
has something to correct in P1.
"""

from __future__ import annotations

import math

MODEL_VERSION = "baseline-0"
FACTOR_SET = ["mom_20d", "mom_60d", "mom_120d", "dist_high_60d", "rsi_14"]
_SCORE_COLS = ["mom_20d", "mom_60d", "mom_120d"]


def _zstats(values: list[float | None]) -> tuple[float, float] | None:
    xs = [v for v in values if v is not None]
    if not xs:
        return None
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs)) or 1.0
    return m, sd


def score_rows(rows: list[dict]) -> list[dict]:
    """Attach a cross-sectional ``score`` = mean z-score over the momentum columns."""
    stats = {c: _zstats([r.get(c) for r in rows]) for c in _SCORE_COLS}
    out = []
    for r in rows:
        s, n = 0.0, 0
        for c in _SCORE_COLS:
            v, st = r.get(c), stats[c]
            if v is not None and st is not None:
                m, sd = st
                s += (v - m) / sd
                n += 1
        out.append({**r, "score": s / n if n else 0.0})
    return out


def infer(rows: list[dict]) -> list[dict]:
    """Rank rows best-first and attach predicted_return / predicted_prob_tp / rank."""
    scored = sorted(score_rows(rows), key=lambda x: x["score"], reverse=True)
    out = []
    for rank, r in enumerate(scored, 1):
        out.append({
            **r,
            "rank": rank,
            "predicted_return": round(0.04 * math.tanh(r["score"]), 4),  # bounded 1m E[ret]
            "predicted_prob_tp": round(1.0 / (1.0 + math.exp(-r["score"])), 4),  # raw logistic
        })
    return out
