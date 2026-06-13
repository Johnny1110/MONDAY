"""/api/universe — the analysable pool after the hard liquidity gate (§4.1)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import pagination, store
from ..config import settings
from ..featurestore import build as fbuild

router = APIRouter(prefix="/api/universe", tags=["universe"])


@router.get("")
def list_universe(as_of: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    as_of = as_of or store.kv_get("last_as_of")
    rows = fbuild.read_features(settings.data_dir, as_of) if as_of else []
    items = sorted(
        ({"symbol": r["symbol"], "name": r.get("name"), "close": r.get("close"),
          "adv_20d": r.get("adv_20d")} for r in rows),
        key=lambda x: x["symbol"])
    return {**pagination.paginate(items, page, page_size), "as_of": as_of}
