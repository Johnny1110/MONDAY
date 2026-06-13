"""/api/reports — User-facing notices (daily ideas / review summaries / alerts, invariant 8b)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import pagination, store

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
def list_reports(kind: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    return pagination.paginate(store.list_reports(kind), page, page_size)


@router.post("")
def add_report(payload: dict) -> dict:
    return store.add_report(payload.get("title", "(untitled)"), payload.get("body", ""),
                            payload.get("kind", "info"))
