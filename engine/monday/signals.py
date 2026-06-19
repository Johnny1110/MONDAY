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


def _candidate(c: dict) -> dict:
    """One candidate row carried in the envelope (the overlay reads factors straight from here)."""
    return {
        "symbol": c["symbol"],
        "name": c.get("name"),
        "rank": c["rank"],
        "score": round(c["score"], 4),
        "close": c["close"],
        "predicted_return": c["predicted_return"],
        "predicted_prob_tp": c["predicted_prob_tp"],                # raw P(touch-TP)
        "conviction": c.get("conviction", c.get("predicted_prob_tp")),  # ledger-calibrated (Imp #1)
        "adv_20d": c.get("adv_20d"),              # carried for the §5.7 liquidity gate at finalize
        "factors": {k: c.get(k) for k in _ENVELOPE_KEYS},   # momentum + technical + chips (read by the overlay)
    }


def build_envelope(as_of: str, model_version: str, regime: str,
                   predictions: list[dict], pool: int, *,
                   signals_version: str | None = None, degraded: list[str] | None = None,
                   focus_sectors: list[str] | None = None, holdings: list[str] | None = None,
                   sector_lookup: dict | None = None) -> dict:
    """The candidate envelope served at GET /api/signals/today. ``signals_version`` stamps the immutable
    snapshot this build is (B9/B13 — what morgan finalises against); ``degraded`` lists thin-history
    factors (B6).

    2.0 (A6): when ``focus_sectors``/``holdings`` are given, the FULL ranking is preserved (cross-sectional
    validity, §flow STEP A1) but the **output** is scoped — the top ``pool`` focus-sector names become fresh
    candidates and **every held name is always included** (even outside focus, so morgan's hold/trim/exit
    has the model's view). Each candidate is tagged ``sector``/``in_focus``/``held``. With both None the
    output is the **exact 1.0 envelope** (backward compatible)."""
    env = {
        "as_of_date": as_of,
        "model_version": model_version,
        "signals_version": signals_version,
        "regime": regime,
        "degraded_factors": degraded or [],
    }
    if focus_sectors is None and holdings is None:           # 1.0 path — unchanged
        cands = [_candidate(c) for c in predictions[:pool]]
        env["candidate_count"] = len(cands)
        env["candidates"] = cands
        return env

    # 2.0 focus-scoped path
    sector_lookup = sector_lookup or {}
    focus = set(focus_sectors or [])
    holdings = list(holdings or [])
    held_set = set(holdings)
    by_symbol = {p["symbol"]: p for p in predictions}

    chosen, seen = [], set()
    for c in predictions:                                    # predictions already rank-sorted (full pool)
        sym = c["symbol"]
        sec = sector_lookup.get(sym, "unknown")
        if focus and sec in focus and sym not in seen:       # top-`pool` focus-sector names → candidates
            chosen.append({**_candidate(c), "sector": sec, "in_focus": True, "held": sym in held_set})
            seen.add(sym)
            if len(chosen) >= pool:
                break

    holdings_unscored = []                                   # ALWAYS include held names (even outside focus)
    for sym in holdings:
        if sym in seen:
            continue
        c = by_symbol.get(sym)
        if c is None:                                        # delisted/illiquid: no prediction — report it
            holdings_unscored.append(sym)
            continue
        sec = sector_lookup.get(sym, "unknown")
        chosen.append({**_candidate(c), "sector": sec, "in_focus": sec in focus, "held": True})
        seen.add(sym)

    env.update({
        "focus_sectors": sorted(focus),
        "all_ranked": len(predictions),                      # full-pool size the ranking was computed over
        "candidate_count": len(chosen),
        "candidates": chosen,
        "holdings_unscored": holdings_unscored,
        "unknown_sector_count": sum(1 for p in predictions
                                    if sector_lookup.get(p["symbol"], "unknown") == "unknown"),
    })
    return env
