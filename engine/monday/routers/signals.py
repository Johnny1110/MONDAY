"""/api/signals — the model's daily candidate ranking (quant → LLM overlay, §5.6)."""

from __future__ import annotations

import json

from fastapi import APIRouter

from .. import store

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/today")
def signals_today() -> dict:
    """The candidate envelope the quant agent produces and the analysts overlay (§5.6)."""
    raw = store.kv_get("signals_today")
    if raw:
        return json.loads(raw)
    return {"as_of_date": None, "candidate_count": 0, "candidates": [],
            "note": "No pipeline run yet — POST /api/system/run-pipeline."}
