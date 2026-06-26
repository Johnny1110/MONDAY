"""/api/calibration — the regression scorecard computed from the ledger (§6.1).

The heart of the lab: IC, hit rate, calibration curve, and factor/regime attribution. In P0,
"realized" prefers a settled outcome and falls back to the latest mark's mtm for still-open
ideas, so the scorecard is populated even before the first window closes. POST /run snapshots a
scorecard into ``calibration_runs`` (what the weekly review reads, §6.2).
"""

from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, HTTPException

from .. import calibration as calc
from .. import events, pagination, store, triggers
from ..config import settings

router = APIRouter(prefix="/api/calibration", tags=["calibration"])


def _today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


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
        "attribution_by_regime": calc.attribution_with_ic(rows, "regime_label"),
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
    loop wakes on the data, not on a human reading the Friday scorecard. 2.0 (A9): the stored scorecard
    also carries the macro-call + position-management dims in its ``adjustments`` JSON (no schema change)."""
    sc = _scorecard()
    macro = calc.macro_call_accuracy(store.list_macro_calls())               # A9 dim
    posmgmt = calc.position_mgmt_value(store.list_position_actions(), _position_realized_lookup())  # A9 dim
    as_of = store.kv_get("last_as_of")
    # Regime-aware calibration (task #101): record the benchmark return + regime state so
    # subsequent drift checks can distinguish regime shift from model degradation.
    bench_pct = None
    regime_state = None
    if as_of:
        from .. import macro as macro_mod
        for r in macro_mod.read_macro_snapshot(settings.data_dir, as_of):
            if r.get("symbol") == settings.macro_benchmark_symbol:
                bench_pct = r.get("chg_pct")
                break
        raw_sig = store.kv_get("signals_today")
        if raw_sig:
            regime_state = json.loads(raw_sig).get("regime")
    run_id = f"calib-{as_of or 'na'}-{len(store.list_calibration_runs()) + 1}"
    run = store.add_calibration_run({
        "run_id": run_id, "run_date": as_of, "window": window,
        "hit_rate": sc["hit_rate"], "tp_hit_rate": None,
        "avg_win": sc["avg_win"], "avg_loss": sc["avg_loss"], "ic": sc["ic"],
        "excess_vs_taiex": bench_pct, "attribution": sc["attribution_by_factor"],
        "adjustments": {"note": "P0 scorecard snapshot; ADR-linked adjustments land in P1 (§6.4).",
                        "brier": sc["brier"], "reliability_gap": sc["reliability_gap"],
                        "regime_state": regime_state, "benchmark_chg_pct": bench_pct,
                        "attribution_by_regime": sc["attribution_by_regime"],
                        "macro": macro, "position_mgmt": posmgmt},
    })
    fired = triggers.evaluate_calibration(
        store.list_calibration_runs(), ic_floor=settings.calibration_ic_floor,
        drift_weeks=settings.calibration_drift_weeks, decay_periods=settings.factor_decay_periods)
    if settings.macro_drift_enabled:                                          # A9: ships dark by default
        hist = [(r.get("adjustments") or {}).get("macro", {}).get("hit_rate")
                for r in reversed(store.list_calibration_runs())]            # oldest-first
        md = triggers.detect_macro_drift(hist, settings.macro_call_floor, settings.macro_drift_periods)
        if md:
            fired.append(md)
    if post:
        for ev in fired:
            events.post(settings.evva_webhook_url, ev)
    return {**run, "macro": macro, "position_mgmt": posmgmt,
            "triggers_fired": [e["data"]["event_type"] for e in fired]}


# --------------------------------------------------------------------------
# A9 — macro-call accuracy + position-management value-add
# --------------------------------------------------------------------------

def _benchmark_close(date: str) -> float | None:
    """The macro-call benchmark's (TAIEX) close from the PIT macro snapshot for ``date`` (None if absent)."""
    from .. import macro as macro_mod
    for r in macro_mod.read_macro_snapshot(settings.data_dir, date):
        if r.get("symbol") == settings.macro_benchmark_symbol:
            return r.get("close")
    return None


def settle_macro_calls(as_of: str) -> dict:
    """Score every matured, still-unsettled macro call against the benchmark's realized forward return
    (PIT macro snapshots only — no look-ahead, §4.2). Idempotent: a call with ``correct`` already set is
    skipped, so re-running never double-scores."""
    eps = settings.macro_call_eps_pct / 100.0
    settled = skipped = 0
    for call in store.list_macro_calls():
        if call.get("correct") is not None:
            skipped += 1
            continue
        horizon = call.get("horizon_days") or settings.holding_window_days
        try:
            mature = (_dt.date.fromisoformat(call["call_date"]) + _dt.timedelta(days=horizon)).isoformat()
        except (ValueError, TypeError, KeyError):
            skipped += 1
            continue
        if as_of < mature:                                  # not matured yet
            skipped += 1
            continue
        start = _benchmark_close(call["call_date"])
        end = _benchmark_close(mature) or _benchmark_close(as_of)   # nearest available at/after maturity
        if not start or not end:                            # benchmark not snapshotted → can't settle yet
            skipped += 1
            continue
        fwd = end / start - 1.0
        store.update_macro_call(call["call_id"], realized_index_fwd_ret=round(fwd, 4),
                                correct=calc.score_macro_call(call.get("risk_state"), fwd, eps))
        settled += 1
    return {"as_of": as_of, "settled": settled, "skipped": skipped}


def _position_realized_lookup() -> dict:
    """Build {(symbol, action_date): {realized, hold}} for trim/exit actions from PIT price snapshots:
    realized = price_at_action/entry − 1; hold (counterfactual) = price_at_window_end/entry − 1 (or the
    latest available close). Entry date = the lot's ``open`` action date. Best-effort: an action whose
    prices aren't snapshotted is skipped (so the share is over what we can actually measure)."""
    from .. import snapshot
    actions = store.list_position_actions()
    opens: dict[str, str] = {}
    for a in sorted(actions, key=lambda x: x.get("action_date") or ""):
        if a.get("action") == "open" and a.get("position_id"):
            opens.setdefault(a["position_id"], a.get("action_date"))

    price_cache: dict[str, dict] = {}

    def close_on(date: str | None, symbol: str) -> float | None:
        if not date:
            return None
        if date not in price_cache:
            price_cache[date] = {r["symbol"]: r.get("close")
                                 for r in snapshot.read_snapshot(settings.data_dir, date)}
        return price_cache[date].get(symbol)

    window = settings.holding_window_days
    last_as_of = store.kv_get("last_as_of")
    lookup: dict = {}
    for a in actions:
        if a.get("action") not in ("trim", "exit"):
            continue
        sym, adate, pid = a.get("symbol"), a.get("action_date"), a.get("position_id")
        entry_date = opens.get(pid)
        entry_px, action_px = close_on(entry_date, sym), close_on(adate, sym)
        if not entry_px or not action_px:
            continue
        try:
            win_end = (_dt.date.fromisoformat(entry_date) + _dt.timedelta(days=window)).isoformat()
        except (ValueError, TypeError):
            continue
        hold_px = close_on(win_end, sym) or close_on(last_as_of, sym)
        if not hold_px:
            continue
        lookup[(sym, adate)] = {"realized": round(action_px / entry_px - 1, 4),
                                "hold": round(hold_px / entry_px - 1, 4)}
    return lookup


@router.post("/macro/call")
def record_macro_call(payload: dict) -> dict:
    """Record today's macro call (A9) — macro-analyst (B1) writes its OWN call here (``by``-attributed) so
    its accuracy is measurable. Body: {risk_state, call_date?, horizon_days?, sectors_favored?,
    sectors_avoid?, by?, rationale?}. Upsert on call_date (one call per day)."""
    if not payload.get("risk_state"):
        raise HTTPException(status_code=422, detail="risk_state required (risk_on|neutral|risk_off)")
    call_date = payload.get("call_date") or store.kv_get("last_as_of") or _today()
    return store.add_macro_call({
        "call_id": call_date, "call_date": call_date, "risk_state": payload["risk_state"],
        "horizon_days": payload.get("horizon_days") or settings.holding_window_days,
        "sectors_favored": payload.get("sectors_favored"), "sectors_avoid": payload.get("sectors_avoid"),
        "by": payload.get("by") or "macro-analyst", "rationale": payload.get("rationale")})


@router.get("/macro")
def macro_accuracy() -> dict:
    """Macro-call accuracy over settled calls (overall + per-risk_state) + the call log."""
    calls = store.list_macro_calls()
    return {**calc.macro_call_accuracy(calls), "min_samples": settings.calibration_min_samples,
            "benchmark": settings.macro_benchmark_symbol, "calls": calls}


@router.post("/macro/settle")
def macro_settle(as_of: str | None = None) -> dict:
    """Score matured macro calls against the benchmark's realized forward return (idempotent)."""
    return settle_macro_calls(as_of or store.kv_get("last_as_of") or _today())


@router.get("/positions")
def positions_value() -> dict:
    """Position-management value-add (did trims/exits beat holding?) from the action log + PIT prices."""
    return {**calc.position_mgmt_value(store.list_position_actions(), _position_realized_lookup()),
            "min_samples": settings.calibration_min_samples,
            "note": "value_add = realized_at_action − counterfactual_hold_to_window_end (PIT closes)."}
