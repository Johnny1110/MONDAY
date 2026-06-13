"""/api/admin — operator-only maintenance. NOT advertised to agents in /manual (invariant 4)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import store

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/reset")
def reset() -> dict:
    """Wipe ALL transactional state (recs/positions/ledger/…). Irreversible; schema preserved.
    Operator tool for a clean slate — agents are not told this exists."""
    return {"wiped": store.reset()}
