"""Train + register the cold-start GBDT (whitepaper §5.2/§5.4).

Pipeline: ingest history → assemble a POINT-IN-TIME training set (features at t from bars ≤ t;
labels from bars after t) → score honest OOS rank IC via purged walk-forward CV → fit the final
model on all data → persist + register the version with its cv_ic. The OOS IC is the headline
"is this real?" number (§5.4); cold-start results are hypotheses until the live PIT ledger
confirms them (§4.2/§9). Run: ``python -m monday.models.train --source finmind --days 400``.
"""

from __future__ import annotations

import logging
import pathlib

from .. import calibration, store
from ..config import settings
from ..featurestore import build as fbuild
from ..ingest import get_source
from . import cv, gbdt, labels

log = logging.getLogger("monday.train")


def build_training_set(bars: list[dict], horizon: int, tp_pct: float,
                       min_history: int) -> list[dict]:
    """One row per (symbol, eligible date): PIT features (from bars ≤ date) + forward labels."""
    panel: dict[str, list[dict]] = {}
    for b in sorted(bars, key=lambda x: x["date"]):
        panel.setdefault(b["symbol"], []).append(b)
    rows = []
    for sym, sb in panel.items():
        closes = [b["close"] for b in sb]
        highs = [b["high"] for b in sb]
        for i in range(min_history, len(sb) - horizon):
            y_ret = labels.forward_return(closes, i, horizon)
            y_touch = labels.touch_tp(closes, highs, i, horizon, tp_pct)
            if y_ret is None or y_touch is None:
                continue
            frow = fbuild.compute_row(sym, sb[:i + 1], sb[i]["date"])
            rows.append({**frow, "y_ret": y_ret, "y_touch": y_touch})
    return rows


def oos_rank_ic(rows: list[dict], horizon: int, embargo: int, n_splits: int) -> float | None:
    """Mean out-of-sample cross-sectional rank IC across purged walk-forward folds."""
    splits = cv.purged_walk_forward([r["as_of"] for r in rows], n_splits=n_splits,
                                    horizon=horizon, embargo=embargo)
    fold_ics = []
    for train_dates, val_dates in splits:
        tr_set, va_set = set(train_dates), set(val_dates)
        tr = [r for r in rows if r["as_of"] in tr_set]
        va = [r for r in rows if r["as_of"] in va_set]
        if len(tr) < 50 or len(va) < 10:
            continue
        preds = gbdt.predict(gbdt.train_heads(tr), va)
        by_date: dict[str, list[dict]] = {}
        for p in preds:
            by_date.setdefault(p["as_of"], []).append(p)
        day_ics = [calibration.rank_ic([x["score"] for x in ps], [x["y_ret"] for x in ps])
                   for ps in by_date.values()]
        day_ics = [ic for ic in day_ics if ic is not None]
        if day_ics:
            fold_ics.append(sum(day_ics) / len(day_ics))
    return round(sum(fold_ics) / len(fold_ics), 4) if fold_ics else None


def train(source: str = "finmind", days: int = 400, horizon: int | None = None,
          tp_pct: float = 0.08, n_splits: int = 4, embargo: int = 5,
          min_history: int = 120) -> dict:
    """Train, validate (OOS IC), persist, and register the GBDT. Requires store.connect() first."""
    horizon = horizon or settings.holding_window_days
    cache_dir = str(pathlib.Path(settings.data_dir) / "cache")
    bars = get_source(source)(days=days, cache_dir=cache_dir, token=settings.finmind_token)
    if not bars:
        raise RuntimeError(f"ingest source {source!r} returned no bars")
    rows = build_training_set(bars, horizon, tp_pct, min_history)
    if len(rows) < 200:
        raise RuntimeError(f"training set too small ({len(rows)} rows) — widen --days")
    log.info("training set: %d samples over %d dates", len(rows),
             len({r["as_of"] for r in rows}))

    ic = oos_rank_ic(rows, horizon, embargo, n_splits)
    bundle = gbdt.train_heads(rows)

    first, last = min(r["as_of"] for r in rows), max(r["as_of"] for r in rows)
    version = f"gbdt-{last}"
    path = str(pathlib.Path(settings.data_dir) / "models" / f"{version}.pkl")
    gbdt.save(bundle, path)
    store.kv_set(f"model_path:{version}", path)
    store.kv_set("gbdt_latest", version)
    store.register_model(
        version, train_window=f"{first}..{last}", cv_ic=ic, factor_set=gbdt.GBDT_FEATURES,
        notes=f"LightGBM 3-head; {len(rows)} samples; purged walk-forward CV "
              f"(n_splits={n_splits}, embargo={embargo}, horizon={horizon})")
    return {"version": version, "samples": len(rows), "dates": len({r["as_of"] for r in rows}),
            "oos_rank_ic": ic, "features": gbdt.GBDT_FEATURES, "path": path}


def main(argv: list[str] | None = None) -> None:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Train + register the cold-start GBDT model")
    p.add_argument("--source", default="finmind", help="finmind | twse | synthetic")
    p.add_argument("--days", type=int, default=400)
    p.add_argument("--horizon", type=int, default=None, help="holding window (default: config)")
    p.add_argument("--tp-pct", type=float, default=0.08)
    p.add_argument("--n-splits", type=int, default=4)
    p.add_argument("--embargo", type=int, default=5)
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    store.connect(settings.sqlite_path)
    try:
        result = train(source=a.source, days=a.days, horizon=a.horizon, tp_pct=a.tp_pct,
                       n_splits=a.n_splits, embargo=a.embargo)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
