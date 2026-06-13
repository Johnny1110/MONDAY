"""Models: the prediction engine's quant trunk (whitepaper §5).

``baseline`` is the P0 **empty** model — a transparent, untrained cross-sectional momentum ranker.
``gbdt`` (P1) is the real LightGBM three-head ensemble (Ranker/Regressor/Classifier, §5.2), with
``train`` orchestrating the point-in-time training set, purged walk-forward CV (``cv``), and
forward ``labels``. lightgbm is lazily imported (invariant 6); regime-aware weighting (§5.3) is
P2. Training artifacts live in the model registry (store) + a pickle under data/models, never in
an agent conversation (§2).
"""

from .baseline import FACTOR_SET, MODEL_VERSION, infer  # noqa: F401
