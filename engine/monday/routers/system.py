"""/api/system — liveness, status, the async pipeline trigger, and task/quota visibility.

The chain is long (5–300 s), so POST /run-pipeline is ASYNC (B10): it returns a ``task_id`` and runs
in a background thread; poll GET /tasks/{id}. It is single-flight (B11) — a second trigger gets 409 —
and the same lock spans CLI runs (separate process, shared Postgres). GET /quota surfaces FinMind usage
so agents back off when the free tier is spent (B3b); /status reports token readiness (B4).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .. import __version__, store, tasks
from ..config import redacted_database_url, settings

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def status() -> dict:
    """Cheap status: versions + what the last run produced + readiness (no external calls)."""
    return {
        "service": "monday-engine",
        "version": __version__,
        "last_as_of": store.kv_get("last_as_of"),
        "model": (store.latest_model() or {}).get("model_version"),
        "recommendations": len(store.list_recommendations()),
        "open_positions": len(store.list_positions(status="open")),
        "settled_outcomes": len(store.list_outcomes()),
        "finmind_token_loaded": bool(settings.finmind_token),   # B4 — presence only, never the value
        "universe_size": settings.universe_size,
        "pipeline": store.pipeline_lock_holder(),               # the currently-running pipeline, if any
        "data_dir": settings.data_dir,
        "database": redacted_database_url(),                     # host:port/db — creds redacted (token-free)
    }


@router.post("/run-pipeline")
def run_pipeline(days: int = 180, mark_forward: int = 1, source: str = "finmind",
                 model: str = "baseline", finalize: bool = True, post: bool = False,
                 notify: bool = False, universe_size: int | None = None,
                 symbols: str | None = None, as_of: str | None = None, force: bool = False):
    """Trigger the chain ASYNCHRONOUSLY (B10): returns ``{task_id, status:"running"}`` (202) at once and
    runs in the background — poll GET /api/system/tasks/{task_id}. Single-flight (B11): 409 if a
    pipeline is already running (HTTP or CLI). ``source`` 'finmind'|'twse'; ``model`` 'baseline'|'gbdt'.
    ``finalize=false`` stops after signals (the analyst overlay then POST /api/recommendations/finalize).
    ``universe_size`` / ``symbols`` (comma list e.g. "2330,2317") scope the run (B5); ``force`` overwrites
    signals even if the day is finalized (B9/B13)."""
    from ..pipeline import run                  # lazy: keeps app import light
    params = {"days": days, "mark_forward": mark_forward, "source": source, "model": model,
              "finalize": finalize, "post": post, "notify": notify, "universe_size": universe_size,
              "symbols": symbols, "as_of": as_of, "force": force}
    task = tasks.new_task("pipeline", params)
    if not store.acquire_pipeline_lock(task["task_id"], holder="http"):
        tasks.update(task["task_id"], status="failed", message="another pipeline is running")
        return JSONResponse(status_code=409,
                            content={"error": "a pipeline is already running",
                                     "holder": store.pipeline_lock_holder(),
                                     "task_id": task["task_id"]})

    def target(progress):
        return run(as_of=as_of, days=days, mark_forward=mark_forward, post=post, notify=notify,
                   source=source, model=model, finalize=finalize, universe_size=universe_size,
                   symbols=symbols, force=force, progress=progress)

    threading.Thread(target=tasks.runner, args=(task["task_id"], target),
                     kwargs={"post": post, "webhook_url": settings.evva_webhook_url},
                     daemon=True).start()
    return JSONResponse(status_code=202, content={"task_id": task["task_id"], "status": "running"})


@router.get("/tasks")
def list_tasks(limit: int = 20) -> dict:
    """Recent runs (newest first): status / stage / what each produced (B8)."""
    return {"tasks": tasks.recent(limit)}


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    """Poll one run's status / stage / result / error (B8)."""
    rec = tasks.get(task_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
    return rec


@router.get("/quota")
def quota() -> dict:
    """FinMind usage so agents stop hammering once the free tier is spent (B3b). ``today`` is the
    persisted per-UTC-day tally (server + CLI runs); ``live`` is this process's counters since the last
    drain; ``rate_limited_recently`` is the signal to back off / fall back to cache."""
    from ..ingest import base
    day = datetime.now(timezone.utc).date().isoformat()
    raw = store.kv_get(f"finmind_quota:{day}")
    today = json.loads(raw) if raw else {"calls": 0, "rate_limited": 0, "last_rate_limited_at": None}
    live = base.quota_snapshot().get("finmind", {})
    return {"date": day, "today": today, "live": live,
            "rate_limited_recently": bool(today.get("rate_limited") or live.get("rate_limited"))}
