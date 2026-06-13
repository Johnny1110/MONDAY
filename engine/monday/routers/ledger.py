"""/api/ledger — the calibration ledger: daily marks + settled outcomes (§6.1)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import pagination, store

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


@router.get("/marks")
def marks(rec_id: str | None = None, date: str | None = None,
          page: int = 1, page_size: int = 100) -> dict:
    rows = store.marks_for(rec_id) if rec_id else store.list_marks(date)
    return pagination.paginate(rows, page, page_size)


@router.get("/outcomes")
def outcomes(page: int = 1, page_size: int = 50) -> dict:
    return pagination.paginate(store.list_outcomes(), page, page_size)
