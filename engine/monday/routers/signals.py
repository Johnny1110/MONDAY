"""/api/signals — the model's daily candidate ranking (quant → LLM overlay, §5.6)."""

from __future__ import annotations

import json

from fastapi import APIRouter

from .. import store

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/today")
def signals_today() -> dict:
    """The latest candidate envelope the quant agent produces and the analysts overlay (§5.6)."""
    raw = store.kv_get("signals_today")
    if raw:
        return json.loads(raw)
    return {"as_of_date": None, "candidate_count": 0, "candidates": [],
            "note": "No pipeline run yet — POST /api/system/run-pipeline."}


@router.get("/{date}")
def signals_for_date(date: str) -> dict:
    """The IMMUTABLE signals snapshot archived for ``date`` (B9/B13) — the exact set a finalized book was
    built against, preserved even after later/background runs. (``/today`` is the mutable latest.)"""
    raw = store.kv_get(f"signals:{date}")
    if raw:
        return json.loads(raw)
    return {"as_of_date": date, "candidate_count": 0, "candidates": [],
            "note": f"no archived signals for {date}"}
