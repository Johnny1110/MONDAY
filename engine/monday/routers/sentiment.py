"""/api/sentiment — PTT/Dcard / Google Trends sentiment (§4.1 alt source). P1 stub in P0."""

from __future__ import annotations

from fastapi import APIRouter

from .. import pagination

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])


@router.get("")
def list_sentiment(symbol: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    return {**pagination.paginate([], page, page_size),
            "note": "P1 source (PTT Stock / Dcard / Google Trends 熱度與情緒). Not wired in P0."}
