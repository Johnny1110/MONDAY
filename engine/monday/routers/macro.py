"""/api/macro — world macro indices for the 2.0 top-down read (A2, PIT-snapshotted, token-free).

macro-analyst (B1) reads this to set the day's risk-on/off; the dashboard (C1) renders the grid;
A9 joins the snapshot to score macro calls. The fixed ~13-index list is small, so the read returns
the whole set (no pagination) — like ``/api/portfolio/equity``.
"""

from __future__ import annotations

import pathlib

from fastapi import APIRouter

from .. import macro as macro_mod
from ..config import settings

router = APIRouter(prefix="/api/macro", tags=["macro"])


def _cache_dir() -> str:
    return str(pathlib.Path(settings.data_dir) / "cache")


def _view(as_of: str | None, rows: list[dict], empty_note: str) -> dict:
    if not rows:
        return {"as_of": as_of, "indices": [], "overnight": {}, "note": empty_note}
    return {"as_of": rows[0].get("as_of"), "indices": rows,
            "overnight": macro_mod.overnight_changes(rows)}


@router.get("")
def macro_today(as_of: str | None = None) -> dict:
    """Latest (or ``as_of``) macro snapshot: ``{as_of, indices:[…], overnight:{leaders,laggards,risk_proxies}}``."""
    rows = macro_mod.read_macro_snapshot(settings.data_dir, as_of)
    return _view(as_of, rows, "no macro snapshot yet — POST /api/macro/refresh")


@router.get("/{date}")
def macro_for_date(date: str) -> dict:
    """The IMMUTABLE PIT macro snapshot archived for ``date`` (mirrors /api/signals/{date})."""
    rows = macro_mod.read_macro_snapshot(settings.data_dir, date)
    return _view(date, rows, f"no macro snapshot for {date}")


@router.post("/refresh")
def macro_refresh(as_of: str | None = None) -> dict:
    """Pull the configured indices + write the PIT snapshot now (synchronous, ~13 cached fetches).
    data-engineer calls this each morning (STEP 0b). Returns ``{as_of, n, rows_on_disk, symbols}``."""
    return macro_mod.refresh(settings.data_dir, _cache_dir(), as_of=as_of)
