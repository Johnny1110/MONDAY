"""/api/system — liveness, status, the async pipeline trigger, and task/quota visibility.

The chain is long (5–300 s), so POST /run-pipeline is ASYNC (B10): it returns a ``task_id`` and runs
in a background thread; poll GET /tasks/{id}. It is single-flight (B11) — a second trigger gets 409 —
and the same lock spans CLI runs (separate process, shared Postgres). GET /quota surfaces FinMind usage
so agents back off when the free tier is spent (B3b); /status reports token readiness (B4).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .. import __version__, events, store, tasks
from ..config import redacted_database_url, settings

router = APIRouter(prefix="/api/system", tags=["system"])
log = logging.getLogger("monday.routers.system")


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
        "last_round_requested": json.loads(store.kv_get("last_round_requested") or "null"),  # A8
        "data_dir": settings.data_dir,
        "database": redacted_database_url(),                     # host:port/db — creds redacted (token-free)
    }


@router.post("/run-round")
def run_round(as_of: str | None = None, force: bool = False):
    """Wake morgan to run today's manual round (A8, §workflow 啟動時機) — morgan then orchestrates the
    whole DAG (B3). **Idempotent**: one wake per trading day unless ``force=true``. Does NOT run the
    pipeline or touch the single-flight lock (morgan task_assigns data-engineer for that). 200s even when
    the swarm is unreachable (the webhook is fire-and-forget, invariant 8) so the dashboard button always
    gets feedback. ``day`` anchors on ``last_as_of`` (the trading day the data is for), not wall-clock."""
    day = as_of or store.kv_get("last_as_of") or datetime.now(timezone.utc).date().isoformat()
    already = store.kv_get(f"round_requested:{day}")
    if already and not force:
        return JSONResponse(status_code=409,
                            content={"status": "already_requested", "as_of": day, "at": already})
    ts = datetime.now(timezone.utc).isoformat()
    store.kv_set(f"round_requested:{day}", ts)
    store.kv_set("last_round_requested", json.dumps({"as_of": day, "at": ts}))
    events.post(settings.evva_webhook_url, events.round_requested_event(day, "user"))
    log.info("run-round: woke morgan for %s (force=%s)", day, force)
    return {"status": "requested", "as_of": day, "at": ts}


@router.post("/run-pipeline")
def run_pipeline(days: int = 180, mark_forward: int = 0, source: str = "finmind",
                 model: str = "baseline", finalize: bool = True, post: bool = True,
                 notify: bool = False, universe_size: int | None = None,
                 symbols: str | None = None, as_of: str | None = None, force: bool = False):
    """Trigger the chain ASYNCHRONOUSLY (B10): returns ``{task_id, status:"running"}`` (202) at once and
    runs in the background — poll GET /api/system/tasks/{task_id}. Single-flight (B11): 409 if a
    pipeline is already running (HTTP or CLI). ``source`` 'finmind'|'twse'; ``model`` 'baseline'|'gbdt'.
    ``finalize=false`` stops after signals (the analyst overlay then POST /api/recommendations/finalize).
    ``mark_forward=0`` (LIVE default, B1) anchors as_of at the LATEST available close; use ≥1 only for
    backtests with held-out future bars to mark against. ``post=true`` (default, B15) fires the
    ``pipeline_complete`` webhook so the swarm leader wakes on completion — pass post=false only for
    tests / ad-hoc local runs. ``universe_size`` / ``symbols`` (comma list e.g. "2330,2317") scope the
    run (B5); ``force`` overwrites signals even if the day is finalized (B9/B13)."""
    if not post:                                # B15: a quiet run won't auto-wake the swarm leader
        log.warning("run-pipeline post=false — pipeline_complete webhook suppressed; the swarm leader "
                    "won't be notified (intended only for tests / ad-hoc local runs)")
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
