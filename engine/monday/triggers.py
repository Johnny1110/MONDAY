"""Event-driven trigger detection (whitepaper §6.3 — webhook, not polling, invariant 7).

Pure detection here; the actual fire-and-forget POST is done by the caller via ``events.post``
(so this stays testable and the engine keeps serving even when the swarm is down). P0 wires the
``portfolio_drawdown`` trigger end to end; ``calibration_drift`` / ``factor_decay`` builders
exist in ``events`` and get their detectors in P1 once the ledger has multi-week history.
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
