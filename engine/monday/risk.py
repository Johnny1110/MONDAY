"""Portfolio risk gate (whitepaper §5.7) — the mechanical brake (pure, unit-tested).

risk-monitor's checks on the day's book: too many names, over-concentration in one sector
("不能 20 檔都是 AI 伺服器"), and names too illiquid for a 1-month swing to exit. ADVISORY by
design — it raises objections; morgan decides (§3 honest trust model: token-free, prompt
discipline). ``picks`` = [{symbol, sector, adv_20d}]; sector "unknown" is excluded from the
concentration test (can't assess what we can't label — don't false-flag).
"""

from __future__ import annotations

from collections import Counter


def gate(picks: list[dict], *, max_names: int = 20, max_per_sector: int = 5,
         adv_floor: float = 0.0, drawdown_pct: float = 0.0, drawdown_soft_pct: float = 0.0) -> dict:
    """Evaluate the book. Returns {passed, n, by_sector, drawdown_pct, violations[]} — never raises, never
    blocks. ``drawdown_pct`` is the book's current peak-to-now drawdown (the caller computes it from the
    equity curve); when it breaches ``drawdown_soft_pct`` a graduated ``drawdown_throttle`` is raised
    (ease new exposure) — before the hard drawdown webhook fires."""
    n = len(picks)
    sectors = Counter((p.get("sector") or "unknown") for p in picks)
    violations: list[dict] = []

    if n > max_names:
        violations.append({"type": "too_many_names", "detail": f"{n} > {max_names}"})

    if drawdown_soft_pct > 0 and drawdown_pct >= drawdown_soft_pct:
        violations.append({"type": "drawdown_throttle",
                           "detail": f"book drawdown {drawdown_pct:.1f}% ≥ soft {drawdown_soft_pct:.1f}% — "
                                     "reduce new adds / size down"})

    over = {s: c for s, c in sectors.items() if s != "unknown" and c > max_per_sector}
    for s, c in sorted(over.items(), key=lambda kv: -kv[1]):
        violations.append({"type": "sector_concentration",
                           "detail": f"{s}: {c} > {max_per_sector}"})

    if adv_floor > 0:
        illiquid = sorted(p["symbol"] for p in picks
                          if p.get("adv_20d") is not None and p["adv_20d"] < adv_floor)
        if illiquid:
            violations.append({"type": "liquidity",
                               "detail": f"below adv_floor {adv_floor:.0f}: {illiquid}"})

    return {"passed": not violations, "n": n,
            "by_sector": dict(sectors.most_common()), "drawdown_pct": round(drawdown_pct, 2),
            "violations": violations}
