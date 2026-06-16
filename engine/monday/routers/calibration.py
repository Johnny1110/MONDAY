"""/api/calibration — the regression scorecard computed from the ledger (§6.1).

The heart of the lab: IC, hit rate, calibration curve, and factor/regime attribution. In P0,
"realized" prefers a settled outcome and falls back to the latest mark's mtm for still-open
ideas, so the scorecard is populated even before the first window closes. POST /run snapshots a
scorecard into ``calibration_runs`` (what the weekly review reads, §6.2).
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import calibration as calc
from .. import events, pagination, store, triggers
from ..config import settings

router = APIRouter(prefix="/api/calibration", tags=["calibration"])


def _scorecard_rows() -> list[dict]:
    rows = []
    for rec in store.list_recommendations():
        oc = store.get_outcome(rec["rec_id"])
        if oc and oc.get("realized_return") is not None:
            realized, hit = oc["realized_return"], bool(oc.get("hit"))
        else:
            marks = store.marks_for(rec["rec_id"])
            realized = marks[-1].get("mtm_return") if marks else None
            hit = (realized or 0) > 0 if realized is not None else None
        rows.append({
            "predicted_return": rec.get("predicted_return"),
            "predicted_prob_tp": rec.get("predicted_prob_tp"),
            "realized_return": realized, "hit": hit,
            "regime_label": rec.get("regime_label"),
            "contributing_factors": rec.get("contributing_factors"),
        })
    return rows


def _scorecard() -> dict:
    rows = [r for r in _scorecard_rows() if r["realized_return"] is not None]
    realized = [r["realized_return"] for r in rows]
    probs, hits = [r["predicted_prob_tp"] for r in rows], [r["hit"] for r in rows]
    avg_win, avg_loss = calc.avg_win_loss(realized)
    curve = calc.calibration_curve(probs, hits)
    return {
        "n": len(rows),
        "ic": calc.rank_ic([r["predicted_return"] for r in rows], realized),
        "hit_rate": calc.hit_rate(realized),
        "avg_win": avg_win, "avg_loss": avg_loss,
        "calibration_curve": curve,
        "brier": calc.brier(probs, hits),                    # single calibration KPI (lower = better)
        "reliability_gap": calc.reliability_gap(curve),       # mean |observed − predicted| across bins
        "attribution_by_regime": calc.attribution(rows, "regime_label"),
        "attribution_by_factor": calc.attribution(rows, "contributing_factors"),
        "note": "P0: realized = settled outcome if present, else latest mark mtm (open ideas).",
    }


@router.get("")
def scorecard() -> dict:
    return _scorecard()


@router.get("/runs")
def runs(page: int = 1, page_size: int = 50) -> dict:
    return pagination.paginate(store.list_calibration_runs(), page, page_size)


@router.post("/run")
def save_run(window: str = "adhoc", post: bool = True) -> dict:
    """Snapshot the current scorecard into calibration_runs (the weekly review's input), then check the
    run history for calibration drift / factor decay and (if ``post``) webhook quant-researcher — the §6
    loop wakes on the data, not on a human reading the Friday scorecard."""
    sc = _scorecard()
    as_of = store.kv_get("last_as_of")
    run_id = f"calib-{as_of or 'na'}-{len(store.list_calibration_runs()) + 1}"
    run = store.add_calibration_run({
        "run_id": run_id, "run_date": as_of, "window": window,
        "hit_rate": sc["hit_rate"], "tp_hit_rate": None,
        "avg_win": sc["avg_win"], "avg_loss": sc["avg_loss"], "ic": sc["ic"],
        "excess_vs_taiex": None, "attribution": sc["attribution_by_factor"],
        "adjustments": {"note": "P0 scorecard snapshot; ADR-linked adjustments land in P1 (§6.4).",
                        "brier": sc["brier"], "reliability_gap": sc["reliability_gap"]},
    })
    fired = triggers.evaluate_calibration(
        store.list_calibration_runs(), ic_floor=settings.calibration_ic_floor,
        drift_weeks=settings.calibration_drift_weeks, decay_periods=settings.factor_decay_periods)
    if post:
        for ev in fired:
            events.post(settings.evva_webhook_url, ev)
    return {**run, "triggers_fired": [e["data"]["event_type"] for e in fired]}
