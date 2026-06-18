"""/api/recommendations — the ≤20 daily ideas (whitepaper appendix C contract).

GET /today serves the envelope; GET / lists the persisted recs (paginated). POST writes one
finalised idea and opens its paper position — in P0 the pipeline does this, but the endpoint is
the contract morgan will use to commit the day's book (§5.7).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from .. import pagination, portfolio, store
from ..config import settings

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("/today")
def recommendations_today() -> dict:
    raw = store.kv_get("recommendations_today")
    if raw:
        return json.loads(raw)
    return {"as_of_date": None, "recommendations": [],
            "note": "No pipeline run yet — POST /api/system/run-pipeline."}


@router.get("")
def list_recommendations(as_of: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    return pagination.paginate(store.list_recommendations(as_of), page, page_size)


@router.post("")
def add_recommendation(rec: dict) -> dict:
    """Persist one idea (recorded at birth, §6.1) and open its paper position."""
    for required in ("rec_id", "symbol", "as_of_date"):
        if required not in rec:
            raise HTTPException(status_code=422, detail=f"missing field: {required}")
    saved = store.add_recommendation(rec)
    if saved.get("entry_ref_price"):
        portfolio.open_from_recommendation(saved)
    return saved


@router.post("/finalize")
def finalize(payload: dict) -> dict:
    """morgan composes the day's book (§5.7): pick ≤max symbols from today's candidates (after the
    analyst overlay) and commit them. Body: {symbols: ["2330", ...]}. Builds each rec from the
    stored signals, opens its paper position, and returns the appendix-C envelope."""
    symbols = payload.get("symbols") or []
    raw = store.kv_get("signals_today")
    if not raw:
        raise HTTPException(status_code=409,
                            detail="no signals today — run the prepare pipeline first (finalize=false)")
    env = json.loads(raw)
    by_sym = {c["symbol"]: c for c in env.get("candidates", [])}
    chosen = [{**by_sym[s], **(by_sym[s].get("factors") or {})}  # flatten factors for the rec builder
              for s in symbols if s in by_sym][: settings.max_recommendations]
    if not chosen:
        raise HTTPException(status_code=422,
                            detail="none of the requested symbols are in today's candidates")
    # Close all open positions first — finalize replaces the book, not appends to it.
    # This keeps total_open ≤ max_recommendations and prevents duplicate symbol exposure
    # from prior-day entries coexisting with the new composition.
    for pos in store.list_positions(status="open"):
        store.close_position(pos["rec_id"])

    import pathlib

    from .. import risk
    from ..ingest import finmind
    from ..pipeline import compose_recommendations    # lazy: keeps app import light
    sig_version = env.get("signals_version")          # B9/B13 — tie the book to the exact snapshot
    _, envelope = compose_recommendations(chosen, env["as_of_date"], env["model_version"],
                                          env.get("regime", "neutral"), signals_version=sig_version)
    # mark the day finalized so a later/background prepare run won't clobber these signals (B13)
    store.kv_set(f"finalized:{env['as_of_date']}", sig_version or env["as_of_date"])
    # §5.7 risk gate — advisory: attach violations for morgan/risk-monitor (never blocks)
    try:
        sectors = finmind.fetch_stock_info(settings.finmind_token,
                                           str(pathlib.Path(settings.data_dir) / "cache"))
    except Exception:
        sectors = {}
    enriched = [{"symbol": p["symbol"], "sector": sectors.get(p["symbol"], "unknown"),
                 "adv_20d": p.get("adv_20d")} for p in chosen]
    dd = portfolio.current_drawdown_pct(store.list_marks())   # graduated throttle (Imp #3)
    envelope["risk"] = risk.gate(enriched, max_names=settings.max_recommendations,
                                 max_per_sector=settings.max_per_sector,
                                 adv_floor=settings.liquidity_adv_floor,
                                 drawdown_pct=dd, drawdown_soft_pct=settings.drawdown_soft_pct)
    envelope["signals_version"] = sig_version
    return envelope
