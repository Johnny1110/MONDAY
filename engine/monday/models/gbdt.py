"""LightGBM three-head model (whitepaper §5.2) — the quant trunk's cold-start engine.

Three heads on the same tabular cross-sectional features:
  * **Ranker** (LambdaMART, ``lambdarank``) → the stock-picking score (per-date groups + quantile
    relevance grades).
  * **Regressor** → expected 1-month return (drives the take-profit price, §5.5).
  * **Classifier** → P(touch TP within the window) → the (provisional) conviction.

lightgbm is **lazily imported** (invariant 6) so the pure layers stay importable without it. A
fitted model is a pickled bundle (the three boosters + feature list); the registry tracks the
version + OOS IC, the pickle lives under data/models/ (gitignored). SHAP attribution + isotonic
recalibration are P2 refinements; for now the calibration LEDGER is the authority (§6).
"""

from __future__ import annotations

import pathlib
import pickle
from itertools import groupby

GBDT_FEATURES = ["mom_20d", "mom_60d", "mom_120d", "dist_high_60d", "rsi_14", "vol_20d"]


def _np():
    import numpy as np
    return np


def _matrix(rows: list[dict], features: list[str]):
    np = _np()
    return np.array([[r.get(f) if r.get(f) is not None else np.nan for f in features]
                     for r in rows], dtype=float)


def _base_params(overrides: dict | None) -> dict:
    p = dict(n_estimators=200, learning_rate=0.05, num_leaves=31, min_child_samples=20,
             subsample=0.8, colsample_bytree=0.8, random_state=20260613, verbosity=-1)
    if overrides:
        p.update(overrides)
    return p


def train_heads(rows: list[dict], features: list[str] = GBDT_FEATURES,
                n_rank_buckets: int = 8, params: dict | None = None) -> dict:
    """Fit the three heads. Each row carries the feature columns + ``y_ret`` + ``y_touch`` +
    ``as_of``. Rows are sorted by date so the ranker's per-date groups are contiguous."""
    import lightgbm as lgb

    from . import labels as L
    np = _np()
    rows = sorted(rows, key=lambda r: r["as_of"])
    X = _matrix(rows, features)
    y_ret = np.array([r["y_ret"] for r in rows], dtype=float)
    y_touch = np.array([int(r["y_touch"]) for r in rows], dtype=int)

    # per-date groups + LambdaMART relevance grades (cross-sectional return buckets)
    groups: list[int] = []
    rel = [0] * len(rows)
    dates = [r["as_of"] for r in rows]
    pos = 0
    for _, grp in groupby(range(len(rows)), key=lambda k: dates[k]):
        idxs = list(grp)
        groups.append(len(idxs))
        bks = L.quantile_buckets([float(y_ret[k]) for k in idxs], n_rank_buckets)
        for local, k in enumerate(idxs):
            rel[k] = bks[local]
        pos += len(idxs)

    bp = _base_params(params)
    ranker = lgb.LGBMRanker(objective="lambdarank", **bp)
    ranker.fit(X, rel, group=groups)
    regr = lgb.LGBMRegressor(**bp)
    regr.fit(X, y_ret)
    clf = lgb.LGBMClassifier(**bp)
    clf.fit(X, y_touch)
    return {"features": features, "ranker": ranker, "regr": regr, "clf": clf}


def predict(bundle: dict, feature_rows: list[dict]) -> list[dict]:
    """Score one as_of's feature rows. Returns rows (input fields preserved) best-first with
    ``score`` / ``predicted_return`` / ``predicted_prob_tp`` / ``rank`` — same shape as the
    baseline model, so it's a drop-in for the pipeline/signals."""
    np = _np()
    if not feature_rows:
        return []
    X = _matrix(feature_rows, bundle["features"])
    score = bundle["ranker"].predict(X)
    pred_ret = bundle["regr"].predict(X)
    proba_full = bundle["clf"].predict_proba(X)
    proba = proba_full[:, 1] if getattr(proba_full, "ndim", 1) == 2 and proba_full.shape[1] > 1 \
        else np.zeros(len(feature_rows))
    out = []
    for r, s, pr, p in zip(feature_rows, score, pred_ret, proba):
        out.append({**r, "score": float(s), "predicted_return": round(float(pr), 4),
                    "predicted_prob_tp": round(float(p), 4)})
    out.sort(key=lambda x: x["score"], reverse=True)
    for rank, r in enumerate(out, 1):
        r["rank"] = rank
    return out


def save(bundle: dict, path: str) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(bundle, f)


def load(path: str) -> dict:
    with open(path, "rb") as f:
        return pickle.load(f)
