"""Cross-sectional candidate signals — the model's hand-off to the LLM overlay (§5.6).

The model ranks the whole analysable pool; ``build_envelope`` takes the top ``pool`` names as
CANDIDATES (whitepaper §5.6: ~40–60). The three analyst agents overlay/veto *within* this set —
the LLM never invents a name outside it (cardinal discipline 1). Pure: shapes data, no I/O.
"""

from __future__ import annotations

_FACTOR_KEYS = ["mom_20d", "mom_60d", "mom_120d", "rsi_14", "dist_high_60d"]   # B6 degradation check (thin-history momentum)
# Pre-computed factors surfaced in each candidate so the analyst overlay reads them straight from the
# envelope instead of re-fetching per symbol (kills the a-chips → FinMind per-candidate fan-out / B3b).
# Chip factors come FREE from the pipeline's enrichment; technical from the feature store — both are
# already on the prediction rows (the predictors preserve feat-row columns via {**r, …}).
_CHIP_KEYS = ["foreign_streak", "invtrust_streak", "margin_chg_5d", "short_chg_5d"]
_TECH_KEYS = ["atr_14", "vol_20d"]
_ENVELOPE_KEYS = _FACTOR_KEYS + _TECH_KEYS + _CHIP_KEYS


def degraded_factors(feat_rows: list[dict], factor_keys: list[str] | None = None,
                     threshold: float = 0.5) -> list[str]:
    """Factors that are null across at least ``threshold`` of the universe — history is too thin to
    compute them, so the ranking silently collapses onto the few that survive (B6: days<120 nulls
    mom_60d/mom_120d/dist_high_60d). Pure + testable; surfaced in the envelope so the swarm sees the
    degradation instead of trusting a single-factor rank."""
    keys = factor_keys or _FACTOR_KEYS
    n = len(feat_rows)
    if not n:
        return []
    return [k for k in keys if sum(1 for r in feat_rows if r.get(k) is None) / n >= threshold]


def build_envelope(as_of: str, model_version: str, regime: str,
                   predictions: list[dict], pool: int,
                   signals_version: str | None = None, degraded: list[str] | None = None) -> dict:
    """The candidate envelope served at GET /api/signals/today. ``signals_version`` stamps the immutable
    snapshot this build is (B9/B13 — what morgan finalises against); ``degraded`` lists thin-history
    factors (B6)."""
    cands = predictions[:pool]
    return {
        "as_of_date": as_of,
        "model_version": model_version,
        "signals_version": signals_version,
        "regime": regime,
        "degraded_factors": degraded or [],
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
            "factors": {k: c.get(k) for k in _ENVELOPE_KEYS},   # momentum + technical + chips (read by the overlay)
        } for c in cands],
    }
