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


@router.post("/reload-config")
def reload_config() -> dict:
    """Re-read .env into settings WITHOUT a restart (B4 — the engine can boot before the deploy writes
    the FinMind token, and pydantic reads env only at construction). Operator-only; returns the names of
    changed fields (never secret values, invariant 2)."""
    from .. import config
    changed = config.reload()
    return {"reloaded": changed, "finmind_token_loaded": bool(config.settings.finmind_token)}
