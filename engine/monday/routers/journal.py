"""/api/journal — the team work log (reviewer-calibrator's review notes, shown to the User)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import pagination, store

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("")
def list_journal(author: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    return pagination.paginate(store.list_journal(author), page, page_size)


@router.post("")
def add_journal(payload: dict) -> dict:
    return store.add_journal(payload.get("body", ""), payload.get("title"),
                             payload.get("date"), payload.get("author", "reviewer-calibrator"))
