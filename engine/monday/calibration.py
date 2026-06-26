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


def brier(probs: list[float], hits: list[bool]) -> float | None:
    """Brier score = mean (p − hit)² over usable pairs — a single trackable calibration KPI (0 = perfect,
    lower = better). None if there are no pairs."""
    pairs = [(float(p), 1.0 if h else 0.0) for p, h in zip(probs, hits)
             if p is not None and h is not None]
    if not pairs:
        return None
    return round(sum((p - h) ** 2 for p, h in pairs) / len(pairs), 4)


def reliability_gap(curve: list[dict]) -> float | None:
    """Count-weighted mean |observed − mean_pred| across the calibration-curve bins (0 = perfectly
    calibrated). ``curve`` is the output of ``calibration_curve``. None if empty."""
    tot = sum(b["n"] for b in curve)
    if not tot:
        return None
    return round(sum(abs(b["observed"] - b["mean_pred"]) * b["n"] for b in curve) / tot, 4)


def score_macro_call(risk_state: str | None, fwd_ret: float | None, eps: float) -> int | None:
    """Did a macro call match the realized forward benchmark return? (A9, §倉位管理 校準擴充)
    ``risk_on`` correct when fwd > +eps; ``risk_off`` when fwd < −eps; ``neutral`` when |fwd| ≤ eps.
    Returns 1/0, or None when ``fwd_ret`` is unknown or the state is unrecognised. ``eps`` is a fraction."""
    if fwd_ret is None:
        return None
    rs = (risk_state or "").lower()
    if rs == "risk_on":
        return 1 if fwd_ret > eps else 0
    if rs == "risk_off":
        return 1 if fwd_ret < -eps else 0
    if rs == "neutral":
        return 1 if abs(fwd_ret) <= eps else 0
    return None


def macro_call_accuracy(calls: list[dict]) -> dict:
    """Macro-call accuracy over the SETTLED subset (each {risk_state, correct, realized_index_fwd_ret}).
    Returns {n, hit_rate, by_risk_state:{state:{n,hit_rate}}, avg_fwd_when_risk_on, avg_fwd_when_risk_off}."""
    settled = [c for c in calls if c.get("correct") is not None]
    n = len(settled)
    by_state = {}
    for state in ("risk_on", "neutral", "risk_off"):
        grp = [c for c in settled if (c.get("risk_state") or "").lower() == state]
        if grp:
            by_state[state] = {"n": len(grp),
                               "hit_rate": round(sum(c["correct"] for c in grp) / len(grp), 4)}

    def _avg_fwd(state):
        xs = [c["realized_index_fwd_ret"] for c in settled
              if (c.get("risk_state") or "").lower() == state
              and c.get("realized_index_fwd_ret") is not None]
        return round(sum(xs) / len(xs), 4) if xs else None

    return {
        "n": n,
        "hit_rate": round(sum(c["correct"] for c in settled) / n, 4) if n else None,
        "by_risk_state": by_state,
        "avg_fwd_when_risk_on": _avg_fwd("risk_on"),
        "avg_fwd_when_risk_off": _avg_fwd("risk_off"),
    }


def position_mgmt_value(actions: list[dict], realized_lookup: dict) -> dict:
    """Did trims/exits add value vs holding? For each trim/exit action, value_add = realized_at_action −
    counterfactual_hold_return. ``realized_lookup`` maps (symbol, action_date) → {realized, hold}.
    Positive ⇒ the discipline helped. Returns {n, n_trim, n_exit, trim_value_add_mean,
    exit_value_add_mean, value_add_mean, pct_actions_value_positive}. Honest: reports negatives too."""
    trims, exits = [], []
    for a in actions:
        act = a.get("action")
        if act not in ("trim", "exit"):
            continue
        rl = realized_lookup.get((a.get("symbol"), a.get("action_date")))
        if not rl or rl.get("realized") is None or rl.get("hold") is None:
            continue
        (exits if act == "exit" else trims).append(rl["realized"] - rl["hold"])
    allv = trims + exits

    def _mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    return {
        "n": len(allv), "n_trim": len(trims), "n_exit": len(exits),
        "trim_value_add_mean": _mean(trims), "exit_value_add_mean": _mean(exits),
        "value_add_mean": _mean(allv),
        "pct_actions_value_positive": (round(sum(1 for v in allv if v > 0) / len(allv), 4)
                                       if allv else None),
    }


def attribution(rows: list[dict], key: str) -> dict:
    """Mean realized return grouped by ``key``.

    When ``key`` is a scalar (e.g. regime_label), the full return is assigned to that single group.
    When ``key`` is a list (e.g. contributing_factors), the return is split EQUALLY among the list
    members — so each factor only gets its fair share, and the factor-level means are genuinely
    differentiated rather than flat copies of the overall mean (§6.4)."""
    agg: dict = {}
    for r in rows:
        rr = r.get("realized_return")
        if rr is None:
            continue
        g = r.get(key)
        if isinstance(g, list):
            if not g:
                continue
            split = rr / len(g)
            for gg in g:
                if gg is None:
                    continue
                agg.setdefault(str(gg), []).append(split)
        else:
            if g is None:
                continue
            agg.setdefault(str(g), []).append(rr)
    return {str(k): {"mean": round(sum(v) / len(v), 4), "n": len(v)} for k, v in agg.items()}


def attribution_with_ic(rows: list[dict], key: str) -> dict:
    """Per-group mean realized return, n, AND rank IC (predicted vs realized within each group).
    Drives regime-aware calibration: a regime shift depresses IC across regimes, but model
    degradation hits specific regimes — the per-regime IC tells them apart (task #101).
    Same split semantics as ``attribution``."""
    aggr: dict[str, list[float]] = {}                # realized returns per group
    aggp: dict[str, list[float]] = {}                # predicted returns per group (for IC)
    for r in rows:
        rr = r.get("realized_return")
        pr = r.get("predicted_return")
        if rr is None:
            continue
        g = r.get(key)
        if isinstance(g, list):
            if not g:
                continue
            for gg in g:
                if gg is None:
                    continue
                aggr.setdefault(str(gg), []).append(rr / len(g))
                if pr is not None:
                    aggp.setdefault(str(gg), []).append(pr / len(g))
        else:
            if g is None:
                continue
            aggr.setdefault(str(g), []).append(rr)
            if pr is not None:
                aggp.setdefault(str(g), []).append(pr)
    out = {}
    for k in aggr:
        entry: dict = {"mean": round(sum(aggr[k]) / len(aggr[k]), 4), "n": len(aggr[k])}
        if k in aggp and len(aggp[k]) >= 2:
            entry["ic"] = rank_ic(aggp[k], aggr[k])
        out[k] = entry
    return out


def regime_ic(rows: list[dict]) -> dict:
    """Per-regime IC — shortcut for ``attribution_with_ic(rows, 'regime_label')``."""
    return attribution_with_ic(rows, "regime_label")
