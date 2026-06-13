"""/api/prices — daily OHLCV bars from the PIT snapshot (§4.1/§4.2)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import pagination, snapshot, store
from ..config import settings

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("")
def list_prices(symbol: str, as_of: str | None = None,
                page: int = 1, page_size: int = 100) -> dict:
    """Price history for ``symbol`` as visible on ``as_of`` (defaults to the latest PIT day)."""
    as_of = as_of or store.kv_get("last_as_of")
    bars = [b for b in snapshot.read_snapshot(settings.data_dir, as_of) if b["symbol"] == symbol]
    bars.sort(key=lambda x: x["date"])
    return {**pagination.paginate(bars, page, page_size), "symbol": symbol, "as_of": as_of}
