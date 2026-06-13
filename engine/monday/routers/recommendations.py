"""/api/recommendations — the ≤20 daily ideas (whitepaper appendix C contract).

GET /today serves the envelope; GET / lists the persisted recs (paginated). POST writes one
finalised idea and opens its paper position — in P0 the pipeline does this, but the endpoint is
the contract morgan will use to commit the day's book (§5.7).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from .. import pagination, portfolio, store

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
