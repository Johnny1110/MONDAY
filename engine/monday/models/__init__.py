"""Models: the prediction engine's quant trunk (whitepaper §5).

P0 ships an **empty/baseline** model — a transparent, untrained cross-sectional momentum
ranker — so the chain produces a ranking without any training infrastructure. The real GBDT
three-head ensemble (Ranker/Regressor/Classifier, §5.2) and regime-aware weighting (§5.3) land
in P1+, with lightgbm lazily imported (invariant 6). Training artifacts live in the model
registry (store), never in an agent conversation (§2).
"""

from .baseline import FACTOR_SET, MODEL_VERSION, infer  # noqa: F401
