"""/api/features — the computed feature rows for a trading day (§4.3)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import pagination, store
from ..config import settings
from ..featurestore import build as fbuild

router = APIRouter(prefix="/api/features", tags=["features"])


@router.get("")
def list_features(as_of: str | None = None, symbol: str | None = None,
                  page: int = 1, page_size: int = 50) -> dict:
    as_of = as_of or store.kv_get("last_as_of")
    rows = fbuild.read_features(settings.data_dir, as_of) if as_of else []
    if symbol:
        rows = [r for r in rows if r["symbol"] == symbol]
    return {**pagination.paginate(rows, page, page_size), "as_of": as_of}
