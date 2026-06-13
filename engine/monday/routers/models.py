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


@router.post("/train")
def train_model(source: str = "finmind", days: int = 400) -> dict:
    """Train + register a cold-start GBDT on real free-core data (the quant-researcher's retrain
    trigger, §6.3). Returns the new version + its OOS rank IC. Synchronous — minutes on a wide
    universe; the swarm calls it from the monthly recalibration cron (§8)."""
    from ..models.train import train           # lazy: pulls lightgbm/numpy only on demand
    return train(source=source, days=days)
