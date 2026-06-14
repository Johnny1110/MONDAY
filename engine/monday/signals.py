"""Cross-sectional candidate signals — the model's hand-off to the LLM overlay (§5.6).

The model ranks the whole analysable pool; ``build_envelope`` takes the top ``pool`` names as
CANDIDATES (whitepaper §5.6: ~40–60). The three analyst agents overlay/veto *within* this set —
the LLM never invents a name outside it (cardinal discipline 1). Pure: shapes data, no I/O.
"""

from __future__ import annotations

_FACTOR_KEYS = ["mom_20d", "mom_60d", "mom_120d", "rsi_14", "dist_high_60d"]


def build_envelope(as_of: str, model_version: str, regime: str,
                   predictions: list[dict], pool: int) -> dict:
    """The candidate envelope served at GET /api/signals/today."""
    cands = predictions[:pool]
    return {
        "as_of_date": as_of,
        "model_version": model_version,
        "regime": regime,
        "candidate_count": len(cands),
        "candidates": [{
            "symbol": c["symbol"],
            "name": c.get("name"),
            "rank": c["rank"],
            "score": round(c["score"], 4),
            "close": c["close"],
            "predicted_return": c["predicted_return"],
            "predicted_prob_tp": c["predicted_prob_tp"],
            "adv_20d": c.get("adv_20d"),          # carried for the §5.7 liquidity gate at finalize
            "factors": {k: c.get(k) for k in _FACTOR_KEYS},
        } for c in cands],
    }
