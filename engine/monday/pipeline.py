"""The full production chain, end to end.

ingest → clean + universe gate → PIT snapshot → feature store → model → signals →
write recommendations + open paper positions → mark-to-market → portfolio summary + triggers.

This is the deterministic spine the swarm drives piecewise (data-engineer runs
ingest/clean/snapshot/features; quant runs inference; morgan finalises recommendations;
reviewer-calibrator marks the ledger). It runs on real free-core market data (FinMind primary,
TWSE fallback); tests inject a recorded real-data fixture. Callable as ``python -m monday.pipeline``
or via POST /api/system/run-pipeline.
"""

from __future__ import annotations

import json
import logging
import pathlib
from collections import defaultdict

from . import clean as clean_mod
from . import events, portfolio, regime as regime_mod, signals, snapshot, store, telegram, triggers
from .config import settings
from .featurestore import build as fbuild
from .ingest import get_source
from .models import baseline

log = logging.getLogger("monday.pipeline")


def _build_rec(c: dict, as_of: str, model_version: str, regime: str, window: int) -> dict:
    """A recommendation recorded AT BIRTH with every column calibration needs (§6.1). TP uses
    max(model E[ret], 8%); SL fixed −8% — both multipliers are calibratable in P1 (§5.5)."""
    entry = c["close"]
    tp_pct = max(c["predicted_return"], 0.08)
    return {
        "rec_id": f"{as_of}:{c['symbol']}",
        "as_of_date": as_of, "symbol": c["symbol"], "name": c.get("name"),
        "direction": "long",                     # MVP long-only (whitepaper §11 default)
        "entry_ref_price": entry,
        "predicted_return": c["predicted_return"],
        "predicted_prob_tp": c["predicted_prob_tp"],
        "conviction": c["predicted_prob_tp"],
        "model_version": model_version,
        "feature_snapshot_id": as_of,
        "regime_label": regime,
        "take_profit_price": round(entry * (1 + tp_pct), 2),
        "stop_loss_price": round(entry * (1 - 0.08), 2),
        "holding_window_days": window,
        "contributing_factors": [k for k in ("mom_20d", "mom_60d", "mom_120d")
                                 if c.get(k) is not None and c[k] > 0],
        "contributing_analysts": [],             # LLM overlay is the swarm's job (P1, §5.6)
        "rationale": f"Cross-sectional model rank ({model_version}).",
        "risk_notes": "Paper portfolio, not investment advice; cold-start model — treat as a hypothesis (§9).",
    }


def _rec_envelope(recs: list[dict], as_of: str, model_version: str, regime: str) -> dict:
    """The daily recommendation envelope (whitepaper appendix C)."""
    return {
        "as_of_date": as_of, "model_version": model_version, "regime": regime,
        "recommendations": [{
            "symbol": r["symbol"], "name": r["name"], "direction": r["direction"],
            "entry_ref": r["entry_ref_price"], "take_profit": r["take_profit_price"],
            "tp_pct": round((r["take_profit_price"] / r["entry_ref_price"] - 1) * 100, 1),
            "stop_loss": r["stop_loss_price"], "holding_window_days": r["holding_window_days"],
            "conviction": r["conviction"], "factors": r["contributing_factors"],
            "analysts": r["contributing_analysts"], "rationale": r["rationale"],
            "risk_notes": r["risk_notes"],
        } for r in recs],
    }


def compose_recommendations(preds: list[dict], as_of: str, model_version: str,
                            regime: str) -> tuple[list[dict], dict]:
    """Write recommendations (recorded at birth, §6.1) + open their paper positions, and persist
    the daily envelope. Used by the autonomous run AND by morgan's finalize endpoint (which passes
    the analyst-curated subset). ``preds`` rows carry flattened feature columns + close + the
    predicted_* fields. Returns (recs, envelope)."""
    recs = []
    for c in preds:
        rec = _build_rec(c, as_of, model_version, regime, settings.holding_window_days)
        store.add_recommendation(rec)
        portfolio.open_from_recommendation(rec)
        recs.append(rec)
    envelope = _rec_envelope(recs, as_of, model_version, regime)
    store.kv_set("recommendations_today", json.dumps(envelope, ensure_ascii=False))
    return recs, envelope


def _equity_curve() -> list[float]:
    """A crude daily portfolio equity proxy from the ledger: 1 + mean mtm per mark date."""
    by_date: dict[str, list[float]] = defaultdict(list)
    for m in store.list_marks():
        if m.get("mtm_return") is not None:
            by_date[m["mark_date"]].append(m["mtm_return"])
    return [1.0 + sum(v) / len(v) for _, v in sorted(by_date.items())]


def _enrich_chips(rows: list[dict], as_of: str, cache_dir: str) -> None:
    """Merge chip factors (§5.6) into feature rows in place (FinMind source only). Concurrent +
    month-anchored cache; chip_factors clips each series to <= as_of, so the through-latest fetch
    stays PIT-safe (no look-ahead)."""
    from .featurestore import chips
    from .ingest import finmind
    syms = sorted({r["symbol"] for r in rows})
    start = finmind._anchor_start(as_of, 90)        # month-anchored ≥60d lookback → stable cache key
    chips.enrich_rows(rows, finmind.fetch_chips(syms, start, None, settings.finmind_token, cache_dir))


def _infer(model: str, feat_rows: list[dict]) -> tuple[list[dict], str]:
    """Run inference with the chosen model. 'gbdt' loads the latest registered GBDT (falling back
    to baseline with a warning if none is trained); 'baseline' uses the untrained momentum ranker.
    Both return (predictions, model_version) in the same shape."""
    if model == "gbdt":
        version = store.kv_get("gbdt_latest")
        path = store.kv_get(f"model_path:{version}") if version else None
        if path and pathlib.Path(path).is_file():
            from .models import gbdt
            return gbdt.predict(gbdt.load(path), feat_rows), version
        log.warning("model=gbdt requested but none trained — falling back to baseline "
                    "(train one: python -m monday.models.train)")
    store.register_model(baseline.MODEL_VERSION, train_window="(untrained P0 baseline)",
                         factor_set=baseline.FACTOR_SET,
                         notes="P0 transparent cross-sectional momentum ranker")
    return baseline.infer(feat_rows), baseline.MODEL_VERSION


def run(as_of: str | None = None, days: int = 180, mark_forward: int = 1,
        post: bool = False, notify: bool = False, source: str = "finmind",
        model: str = "baseline", finalize: bool = True) -> dict:
    """Run the chain. ``source`` selects the ingest adapter ('finmind' | 'twse');
    ``model`` selects the predictor ('baseline' | 'gbdt'). ``finalize=True`` (autonomous) composes
    the full book + marks; ``finalize=False`` stops after signals so the swarm composes the book
    via the analyst overlay (§5.6/§5.7). ``post`` fires swarm webhooks, ``notify`` pushes Telegram
    (both no-op when unconfigured). Returns a stage-by-stage summary. Requires store.connect() first."""
    out: dict = {"stages": {}}

    # 1 — ingest (source-agnostic real free-core data: FinMind primary, TWSE fallback)
    fetch = get_source(source)
    cache_dir = str(pathlib.Path(settings.data_dir) / "cache")
    bars = fetch(days=days + mark_forward, cache_dir=cache_dir, token=settings.finmind_token)
    if not bars:
        raise RuntimeError(f"ingest source {source!r} returned no bars")
    dates = sorted({b["date"] for b in bars})
    if as_of is None:
        as_of = dates[-1 - mark_forward] if len(dates) > mark_forward else dates[-1]
    forward_dates = [d for d in dates if d > as_of][:mark_forward]
    out["as_of"] = as_of
    store.kv_set("last_as_of", as_of)            # routers default to this trading day
    out["stages"]["ingest"] = {"source": source, "bars": len(bars),
                               "symbols": len({b["symbol"] for b in bars})}
    visible = [b for b in bars if b["date"] <= as_of]

    # 2 — clean + hard universe gate
    cleaned, flagged = clean_mod.quality_gate(visible)
    cleaned = clean_mod.adjust_splits(cleaned)
    universe, dropped = clean_mod.liquidity_filter(cleaned)
    out["stages"]["clean"] = {"clean": len(cleaned), "flagged": len(flagged),
                              "universe": len(universe), "dropped_illiquid": len(dropped)}

    # regime label (§5.3) — stamped on every idea so per-regime attribution is meaningful
    regime = regime_mod.regime_for(cleaned, as_of)
    out["stages"]["regime"] = regime

    # 3 — PIT snapshot (look-ahead cure, §4.2)
    rows_on_disk = snapshot.write_snapshot(settings.data_dir, as_of, cleaned)
    out["stages"]["snapshot"] = {"as_of": as_of, "rows_on_disk": rows_on_disk}

    # 4 — feature store (+ chip factors when the source provides them, §5.6)
    feat_rows = fbuild.build_features(cleaned, as_of, universe)
    if source == "finmind":
        _enrich_chips(feat_rows, as_of, cache_dir)
    fbuild.write_features(settings.data_dir, feat_rows)
    out["stages"]["features"] = {"rows": len(feat_rows), "chips": source == "finmind"}

    # 5 — inference (baseline momentum ranker, or a trained GBDT via --model gbdt)
    preds, model_version = _infer(model, feat_rows)
    out["stages"]["inference"] = {"model": model_version, "ranked": len(preds)}

    # 6 — candidate signals (served at /api/signals/today)
    envelope = signals.build_envelope(as_of, model_version, regime,
                                      preds, settings.candidate_pool)
    store.kv_set("signals_today", json.dumps(envelope, ensure_ascii=False))
    out["stages"]["signals"] = {"candidates": envelope["candidate_count"]}

    # 7 — finalize. Autonomous mode composes the full book; the swarm flow uses finalize=False
    # (data-engineer/quant prepare signals → analysts overlay → morgan composes via
    # POST /api/recommendations/finalize), §5.6/§5.7.
    if not finalize:
        out["stages"]["recommendations"] = {
            "written": 0,
            "note": "finalize=False — signals only; compose via POST /api/recommendations/finalize"}
        return out

    n = min(settings.max_recommendations, len(preds))
    recs, rec_envelope = compose_recommendations(preds[:n], as_of, model_version, regime)
    out["stages"]["recommendations"] = {"written": len(recs)}

    # 8 — mark-to-market (open day + forward days): exercises the ledger
    bar_idx = {(b["symbol"], b["date"]): b for b in bars}

    def lookup(d: str) -> dict:
        syms = {p["symbol"] for p in store.list_positions()}
        return {s: bar_idx[(s, d)] for s in syms if (s, d) in bar_idx}

    day0 = portfolio.mark_positions(as_of, lookup(as_of), settings.holding_window_days)
    fwd = {"marked": 0, "settled": 0}
    for d in forward_dates:
        m = portfolio.mark_positions(d, lookup(d), settings.holding_window_days)
        fwd["marked"] += m["marked"]
        fwd["settled"] += m["settled"]
    out["stages"]["mark_to_market"] = {"day0": day0, "forward": fwd,
                                       "forward_dates": forward_dates}

    # 9 — portfolio summary + trigger evaluation
    psum = portfolio.summary()
    fired = triggers.evaluate(_equity_curve(), settings.drawdown_trigger_pct)
    if post:
        for ev in fired:
            events.post(settings.evva_webhook_url, ev)
    out["portfolio"] = psum
    out["triggers_fired"] = [e["data"]["event_type"] for e in fired]

    store.add_report(f"pipeline run — {as_of}",
                     f"{len(recs)} ideas written; portfolio={psum}; "
                     f"triggers={out['triggers_fired']}", kind="recommendation")
    if notify:
        telegram.send(settings.telegram_bot_token, settings.telegram_chat_id,
                      telegram.format_recommendations(rec_envelope))
    return out


def reconcile(as_of: str | None = None, source: str = "finmind", days: int = 30) -> dict:
    """Daily mark-to-market of all OPEN positions against the latest available prices
    (reviewer-calibrator's daily duty, §6.1). Standalone — writes no new recommendations.
    Requires store.connect() first."""
    cache_dir = str(pathlib.Path(settings.data_dir) / "cache")
    syms = sorted({p["symbol"] for p in store.list_positions(status="open")})
    if not syms:                                   # nothing to mark — don't pull the universe for nothing
        return {"mark_date": as_of, "marked": 0, "settled": 0, "portfolio": portfolio.summary()}
    # fetch prices ONLY for open positions (a handful), not the whole universe (quota + speed)
    fetch = get_source(source)
    bars = fetch(days=days, cache_dir=cache_dir, token=settings.finmind_token,
                 symbols=[(s, s) for s in syms])
    if not bars:
        raise RuntimeError(f"ingest source {source!r} returned no bars for open positions")
    bar_idx = {(b["symbol"], b["date"]): b for b in bars}
    mark_date = as_of or max(b["date"] for b in bars)
    lookup = {s: bar_idx[(s, mark_date)] for s in syms if (s, mark_date) in bar_idx}
    res = portfolio.mark_positions(mark_date, lookup, settings.holding_window_days)
    store.kv_set("last_reconcile", mark_date)
    return {"mark_date": mark_date, **res, "portfolio": portfolio.summary()}


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(description="Run the Monday pipeline (or reconcile the ledger)")
    p.add_argument("--as-of", default=None, help="anchor date (default: latest available day)")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--mark-forward", type=int, default=1)
    p.add_argument("--source", default="finmind", help="finmind | twse")
    p.add_argument("--model", default="baseline", help="baseline | gbdt")
    p.add_argument("--no-finalize", dest="finalize", action="store_false",
                   help="stop after signals (don't auto-compose the book)")
    p.add_argument("--reconcile", action="store_true",
                   help="mark-to-market open positions instead of running the chain")
    p.add_argument("--post", action="store_true", help="fire swarm webhooks")
    p.add_argument("--notify", action="store_true", help="push Telegram")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    store.connect(settings.sqlite_path)
    try:
        if a.reconcile:
            summary = reconcile(as_of=a.as_of, source=a.source)
        else:
            summary = run(as_of=a.as_of, days=a.days, mark_forward=a.mark_forward,
                          post=a.post, notify=a.notify, source=a.source, model=a.model,
                          finalize=a.finalize)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
