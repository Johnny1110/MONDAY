"""Calibration math — the regression engine's core (whitepaper §6.1, pure stdlib).

"No ledger, no calibration" (cardinal discipline 2). Given the ledger's predictions and
realized outcomes, these pure functions compute the metrics that drive every adjustment:
rank IC (predicted ranking vs realized ranking), hit rate, win/loss, the calibration curve
(are the 70%-confidence ideas really ~70% hits?), and factor/regime/analyst attribution.
Stdlib only — unit-testable anywhere (invariant 6); the store/router layers feed it rows.
"""

from __future__ import annotations

import math


def _ranks(xs: list[float]) -> list[float]:
    """Average ranks (1-based), ties share the mean rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return cov / math.sqrt(va * vb)


def rank_ic(predicted: list[float], realized: list[float]) -> float | None:
    """Spearman rank IC between predicted scores and realized returns. None if < 2 pairs."""
    pairs = [(p, r) for p, r in zip(predicted, realized) if p is not None and r is not None]
    if len(pairs) < 2:
        return None
    ps, rs = [p for p, _ in pairs], [r for _, r in pairs]
    ic = _pearson(_ranks(ps), _ranks(rs))
    return None if ic is None else round(ic, 4)


def hit_rate(realized: list[float]) -> float | None:
    xs = [r for r in realized if r is not None]
    return round(sum(1 for r in xs if r > 0) / len(xs), 4) if xs else None


def avg_win_loss(realized: list[float]) -> tuple[float | None, float | None]:
    wins = [r for r in realized if r is not None and r > 0]
    losses = [r for r in realized if r is not None and r <= 0]
    return (round(sum(wins) / len(wins), 4) if wins else None,
            round(sum(losses) / len(losses), 4) if losses else None)


def calibration_curve(probs: list[float], hits: list[bool], bins: int = 10) -> list[dict]:
    """Bucket predicted probabilities and compare mean predicted vs observed hit frequency."""
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, h in zip(probs, hits):
        if p is None or h is None:
            continue
        idx = min(bins - 1, max(0, int(p * bins)))
        buckets[idx].append((p, 1 if h else 0))
    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        out.append({
            "bin": i,
            "mean_pred": round(sum(p for p, _ in b) / len(b), 4),
            "observed": round(sum(h for _, h in b) / len(b), 4),
            "n": len(b),
        })
    return out


def attribution(rows: list[dict], key: str) -> dict:
    """Mean realized return grouped by ``key`` (a scalar like regime, or a list like factors/
    analysts). Tells the review SOP which factor/regime/analyst actually made money (§6.4)."""
    agg: dict = {}
    for r in rows:
        rr = r.get("realized_return")
        if rr is None:
            continue
        g = r.get(key)
        for gg in (g if isinstance(g, list) else [g]):
            if gg is None:
                continue
            agg.setdefault(gg, []).append(rr)
    return {str(k): {"mean": round(sum(v) / len(v), 4), "n": len(v)} for k, v in agg.items()}
