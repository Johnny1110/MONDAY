"""/api/chips — institutional-flow / margin chip factors per symbol (§4.3/§5.6).

a-chips's primary data: the three desks' net-flow + persistence and margin/short dynamics. Live
FinMind (cached); token-free to the agent (keys stay engine-side, invariant 2)."""

from __future__ import annotations

import pathlib
from datetime import date, timedelta

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import store
from ..config import settings
from ..featurestore import chips as chips_mod
from ..ingest import finmind
from ..ingest.base import RateLimitError

router = APIRouter(prefix="/api/chips", tags=["chips"])


@router.get("")
def chips(symbol: str, as_of: str | None = None, days: int = 40):
    """Chip factors for ``symbol`` as of ``as_of`` (default the latest pipeline day), plus the
    recent raw flows for the analyst to eyeball."""
    as_of = as_of or store.kv_get("last_as_of") or date.today().isoformat()
    start = date.fromisoformat(as_of) - timedelta(days=int(days * 1.7) + 10)
    cache_dir = str(pathlib.Path(settings.data_dir) / "cache")
    tok = settings.finmind_token
    try:
        inst = finmind.fetch_institutional(symbol, start, as_of, token=tok, cache_dir=cache_dir)
        margin = finmind.fetch_margin(symbol, start, as_of, token=tok, cache_dir=cache_dir)
    except RateLimitError:
        return JSONResponse(
            status_code=503,
            content={"error": "upstream quota exhausted",
                     "detail": "FinMind daily limit reached, retry after reset"})
    return {
        "symbol": symbol, "as_of": as_of,
        "factors": chips_mod.chip_factors(inst, margin, as_of),
        "recent_institutional": inst[-5:],
        "recent_margin": margin[-5:],
    }
