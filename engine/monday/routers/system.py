"""/api/system — liveness, status, and the manual full-chain trigger (P0 exit gate)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__, store
from ..config import settings

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def status() -> dict:
    """Cheap status: versions + what the last pipeline run produced (no external calls)."""
    return {
        "service": "monday-engine",
        "version": __version__,
        "last_as_of": store.kv_get("last_as_of"),
        "model": (store.latest_model() or {}).get("model_version"),
        "recommendations": len(store.list_recommendations()),
        "open_positions": len(store.list_positions(status="open")),
        "settled_outcomes": len(store.list_outcomes()),
        "data_dir": settings.data_dir,
        "sqlite_path": settings.sqlite_path,
    }


@router.post("/run-pipeline")
def run_pipeline(days: int = 180, mark_forward: int = 1, source: str = "synthetic",
                 model: str = "baseline", finalize: bool = True,
                 post: bool = False, notify: bool = False) -> dict:
    """Trigger the chain (ingest → … → signals [→ recommend → mark]). ``source`` selects the ingest
    adapter ('synthetic' | 'finmind' | 'twse'); ``model`` the predictor ('baseline' | 'gbdt').
    ``finalize=false`` stops after signals so the swarm composes the book (the analysts overlay,
    then POST /api/recommendations/finalize)."""
    from ..pipeline import run                 # lazy: keeps app import light
    return run(days=days, mark_forward=mark_forward, source=source, model=model,
               finalize=finalize, post=post, notify=notify)
