"""/api/news — news / 重訊 / 法說 feed (whitepaper §4.1 event source). P1 stub in P0."""

from __future__ import annotations

from fastapi import APIRouter

from .. import pagination

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
def list_news(symbol: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    return {**pagination.paginate([], page, page_size),
            "note": "P1 source (news RSS / 公開資訊觀測站重訊 / 法說會). Not wired in P0."}
