"""Event-driven trigger detection (whitepaper §6.3 — webhook, not polling, invariant 7).

Pure detection here; the actual fire-and-forget POST is done by the caller via ``events.post``
(so this stays testable and the engine keeps serving even when the swarm is down). ``portfolio_drawdown``
fires off the equity curve; ``calibration_drift`` / ``factor_decay`` fire off the calibration-run history
(``evaluate_calibration``) so the §6 self-calibration loop wakes quant-researcher automatically instead of
waiting for a human to read the Friday scorecard.
"""

from __future__ import annotations

from . import events


def max_drawdown(equity: list[float]) -> float:
    """Peak-to-trough drawdown of an equity curve, as a positive percentage."""
    peak = None
    mdd = 0.0
    for e in equity:
        if peak is None or e > peak:
            peak = e
        if peak:
            mdd = min(mdd, (e - peak) / peak)
    return round(abs(mdd) * 100, 2)


def evaluate(equity_curve: list[float], drawdown_threshold: float) -> list[dict]:
    """Return the swarm event payloads that the current state warrants (built, not yet posted)."""
    out: list[dict] = []
    if equity_curve:
        dd = max_drawdown(equity_curve)
        if dd > drawdown_threshold:
            out.append(events.portfolio_drawdown_event(dd, drawdown_threshold))
    return out


# --------------------------------------------------------------------------
# Calibration detectors (§6.3) — read the calibration_runs history
# --------------------------------------------------------------------------

def calibration_series(runs: list[dict]) -> tuple[list[float | None], dict[str, list[float | None]], list[float | None]]:
    """From calibration_runs (any order) → (ic_history oldest-first, {factor: contribution means
    oldest-first}, benchmark_returns oldest-first). Each run's ``attribution`` is {factor: {mean, n}}
    (the factor's mean realized return) or absent → None for that run (a gap breaks a decay streak —
    conservative). ``benchmark_returns`` are the TAIEX chg_pct at each run (None where absent)."""
    runs = sorted(runs, key=lambda r: (r.get("run_date") or "", str(r.get("run_id") or "")))
    ic_history = [r.get("ic") for r in runs]
    benchmark_returns = [
        (r.get("adjustments") or {}).get("benchmark_chg_pct") for r in runs
    ]
    per_run, all_factors = [], set()
    for r in runs:
        attr = r.get("attribution") or {}
        means = {f: v.get("mean") for f, v in attr.items() if isinstance(v, dict)}
        per_run.append(means)
        all_factors |= set(means)
    factor_means = {f: [pr.get(f) for pr in per_run] for f in all_factors}
    return ic_history, factor_means, benchmark_returns


def detect_calibration_drift(ic_history: list[float | None], floor: float, weeks: int) -> dict | None:
    """Fire when the last ``weeks`` rank-ICs are all present and < ``floor`` (predictions stopped tracking
    realized ranking — force a retrain / data+regime check)."""
    recent = ic_history[-weeks:]
    if len(recent) < weeks or any(ic is None for ic in recent):
        return None
    return events.calibration_drift_event(round(recent[-1], 3), weeks) if all(ic < floor for ic in recent) else None


def detect_factor_decay(factor_means: dict[str, list[float | None]], periods: int) -> list[dict]:
    """Fire per factor whose mean contribution is present and < 0 for the last ``periods`` runs. (The
    number carried is the factor's mean realized contribution — the available decay proxy; quant-researcher
    does the rigorous per-factor IC on wake.)"""
    out = []
    for factor, series in sorted(factor_means.items()):
        recent = series[-periods:]
        if len(recent) < periods or any(m is None for m in recent):
            continue
        if all(m < 0 for m in recent):
            out.append(events.factor_decay_event(factor, round(recent[-1], 3), periods))
    return out


def detect_macro_drift(hit_history: list[float | None], floor: float, periods: int) -> dict | None:
    """Fire when the last ``periods`` macro-call hit-rates are all present and < ``floor`` (the top-down
    framework has stopped adding value — recalibrate 定調). Mirrors ``detect_calibration_drift`` (A9)."""
    recent = hit_history[-periods:]
    if len(recent) < periods or any(h is None for h in recent):
        return None
    return events.macro_drift_event(round(recent[-1], 3), periods) if all(h < floor for h in recent) else None


def evaluate_calibration(runs: list[dict], *, ic_floor: float, drift_weeks: int,
                         decay_periods: int) -> list[dict]:
    """The calibration trigger payloads the run history warrants (built, not yet posted).
    Regime-aware (task #101): when IC drops but the drop correlates with benchmark return
    (|corr| > 0.7), the drift is suppressed — a regime_shift event fires instead."""
    ic_history, factor_means, benchmark_returns = calibration_series(runs)
    out: list[dict] = []
    drift = detect_calibration_drift(ic_history, ic_floor, drift_weeks)
    if drift:
        # Regime-aware gate: if IC moves with the market, it's regime shift, not model decay
        recent_ic = [ic for ic in ic_history[-drift_weeks:] if ic is not None]
        recent_bm = [b for b in benchmark_returns[-drift_weeks:] if b is not None]
        if len(recent_ic) >= 2 and len(recent_bm) >= 2 and len(recent_ic) == len(recent_bm):
            from .calibration import _pearson
            corr = _pearson(recent_ic, recent_bm)
            if corr is not None and abs(corr) > 0.7:
                out.append(events.regime_shift_event(round(recent_ic[-1], 3), corr))
            else:
                out.append(drift)
        else:
            out.append(drift)
    out.extend(detect_factor_decay(factor_means, decay_periods))
    return out
