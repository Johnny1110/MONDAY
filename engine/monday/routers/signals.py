"""/api/signals — the model's daily candidate ranking (quant → LLM overlay, §5.6)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .. import signals as signals_mod
from .. import store
from ..config import settings

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/today")
def signals_today() -> dict:
    """The latest candidate envelope the quant agent produces and the analysts overlay (§5.6)."""
    raw = store.kv_get("signals_today")
    if raw:
        return json.loads(raw)
    return {"as_of_date": None, "candidate_count": 0, "candidates": [],
            "note": "No pipeline run yet — POST /api/system/run-pipeline."}


@router.post("/rescope")
def rescope(payload: dict) -> dict:
    """Scope the prepared full-pool ranking to the day's focus (A6, the 2.0 SYNC A→quant step). Body:
    ``{focus_sectors:[…], holdings?:[…], pool?, force?}``. Reads the FULL ranked predictions persisted by
    the prepare run (no re-inference — cross-sectional ranking stays full-pool), keeps only focus-sector
    names as fresh candidates and **always** scores current holdings, then republishes ``signals_today``
    + the per-date archive with a new ``signals_version``. Holdings default to the open book (A3).
    Refuses to clobber a finalized day unless ``force=true`` (B9/B13)."""
    focus = payload.get("focus_sectors") or []
    pool = int(payload.get("pool") or settings.candidate_pool)
    force = bool(payload.get("force"))
    as_of = store.kv_get("last_as_of")
    if not as_of:
        raise HTTPException(status_code=409, detail="no pipeline run yet — run prepare first")

    already_final = store.kv_get(f"finalized:{as_of}")
    if already_final and not force:
        raise HTTPException(status_code=409,
                            detail=f"{as_of} already finalized ({already_final}) — pass force=true to rescope")

    from ..pipeline import read_predictions                # lazy: keeps app import light
    preds = read_predictions(settings.data_dir, as_of)
    if not preds:
        raise HTTPException(status_code=409,
                            detail=f"no persisted predictions for {as_of} — run prepare (finalize=false) first")

    meta = json.loads(store.kv_get(f"predictions_meta:{as_of}") or "{}")
    holdings = payload.get("holdings")
    if holdings is None:                                   # default to the open managed book (A3)
        holdings = [p["symbol"]
                    for p in store.list_book_positions(book=settings.book_mode, status="open")]

    from .. import book                                    # reuse the FinMind sector lookup (cached)
    sectors = book._sector_lookup()                        # noqa: SLF001 — shared helper
    version = f"{as_of}#rescope#{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    env = signals_mod.build_envelope(
        as_of, meta.get("model_version", "unknown"), meta.get("regime", "neutral"), preds, pool,
        signals_version=version, degraded=meta.get("degraded", []),
        focus_sectors=focus, holdings=holdings, sector_lookup=sectors)
    blob = json.dumps(env, ensure_ascii=False)
    store.kv_set("signals_today", blob)                    # mutable latest
    store.kv_set(f"signals:{as_of}", blob)                 # per-date archive
    return env


@router.get("/{date}")
def signals_for_date(date: str) -> dict:
    """The IMMUTABLE signals snapshot archived for ``date`` (B9/B13) — the exact set a finalized book was
    built against, preserved even after later/background runs. (``/today`` is the mutable latest.)"""
    raw = store.kv_get(f"signals:{date}")
    if raw:
        return json.loads(raw)
    return {"as_of_date": date, "candidate_count": 0, "candidates": [],
            "note": f"no archived signals for {date}"}
