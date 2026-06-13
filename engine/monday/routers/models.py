"""/api/models — the model registry (versions + training metadata, §5.4)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import pagination, store

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
def list_models(page: int = 1, page_size: int = 50) -> dict:
    return pagination.paginate(store.list_models(), page, page_size)


@router.get("/{version}")
def get_model(version: str) -> dict:
    m = store.get_model(version)
    if not m:
        raise HTTPException(status_code=404, detail="model version not found")
    return m
