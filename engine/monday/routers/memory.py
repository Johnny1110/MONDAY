"""/api/memory — the public memory boards (morgan's constitution + researcher journals, §6.5).

One long-form markdown doc per agent: read on wake (GET), overwritten at session end (PUT).
Private per-agent working memory lives in evva-native ``agents/*/memory/``, not here.
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import store

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("")
def list_memory() -> dict:
    items = store.list_memory()
    return {"items": items, "total": len(items)}


@router.get("/{agent}")
def get_memory(agent: str) -> dict:
    return store.get_memory(agent) or {"agent": agent, "content": "", "updated_at": None}


@router.put("/{agent}")
def put_memory(agent: str, payload: dict) -> dict:
    return store.set_memory(agent, payload.get("content", ""))
