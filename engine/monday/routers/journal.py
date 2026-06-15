"""/api/journal — the team work log (reviewer-calibrator's review notes, shown to the User)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import pagination, store

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("")
def list_journal(author: str | None = None, since: str | None = None,
                 page: int = 1, page_size: int = 50) -> dict:
    # author=<name> for one teammate; since=YYYY-MM-DD for the weekly review's window.
    return pagination.paginate(store.list_journal(author, since), page, page_size)


@router.post("")
def add_journal(payload: dict) -> dict:
    return store.add_journal(payload.get("body", ""), payload.get("title"),
                             payload.get("date"), payload.get("author", "reviewer-calibrator"))
