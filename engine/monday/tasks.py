"""Async task registry + the guarded pipeline runner (B7/B8/B10/B11).

A pipeline run is long (5–300 s) and must be single-flight, so the HTTP endpoint can't run it inline
(the client would time out — B10 — and concurrent retries would race the sqlite writer — B11). This
module records each run as a KV-backed task (status / stage / message / result / error) the swarm polls
via ``GET /api/system/tasks/{id}`` (B8), and ``runner`` drives one run end to end: it streams stage
progress into the task, heartbeats the cross-process lock, fires the completion/failure webhook, and
ALWAYS releases the lock + flushes the FinMind quota tally. The HTTP router runs ``runner`` in a daemon
thread; the CLI runs it inline — both share the one single-flight lock in ``store.py``. The async
endpoint is also the sanctioned way to launch long work without a background shell (B7).

Storage is the generic kv (invariant 5) — no new agent-facing schema: each task is ``task:{id}`` and a
bounded newest-first ``task_index``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from . import store

log = logging.getLogger("monday.tasks")

_INDEX_KEY = "task_index"
_INDEX_CAP = 50            # keep the last N task bodies; older ones are tombstoned (kv has no delete)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(task_id: str) -> str:
    return f"task:{task_id}"


def new_task(kind: str, params: dict | None = None) -> dict:
    """Create a task record (status=running, stage=queued) and index it. Returns the record."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    task_id = f"{kind}-{stamp}-{uuid.uuid4().hex[:6]}"
    rec = {"task_id": task_id, "kind": kind, "status": "running", "stage": "queued",
           "message": "", "params": params or {}, "started_at": _now(), "updated_at": _now(),
           "finished_at": None, "result": None, "error": None}
    store.kv_set(_key(task_id), json.dumps(rec, ensure_ascii=False))
    _index_push(task_id)
    return rec


def _index_push(task_id: str) -> None:
    raw = store.kv_get(_INDEX_KEY)
    ids = json.loads(raw) if raw else []
    ids.insert(0, task_id)
    keep, evicted = ids[:_INDEX_CAP], ids[_INDEX_CAP:]
    store.kv_set(_INDEX_KEY, json.dumps(keep))
    for tid in evicted:                       # tombstone evicted bodies so kv doesn't grow unbounded
        store.kv_set(_key(tid), "")


def update(task_id: str, **fields) -> dict | None:
    """Merge ``fields`` (status/stage/message/result/error/finished_at) into the task record."""
    rec = get(task_id)
    if rec is None:
        return None
    rec.update(fields)
    rec["updated_at"] = _now()
    store.kv_set(_key(task_id), json.dumps(rec, ensure_ascii=False))
    return rec


def get(task_id: str) -> dict | None:
    raw = store.kv_get(_key(task_id))
    return json.loads(raw) if raw else None       # "" tombstone (evicted) → None


def recent(limit: int = 20) -> list[dict]:
    raw = store.kv_get(_INDEX_KEY)
    ids = json.loads(raw) if raw else []
    out = [get(tid) for tid in ids[:limit]]
    return [r for r in out if r is not None]


def runner(task_id: str, target, *, post: bool = False, webhook_url: str = "") -> dict:
    """Drive one run to completion under task ``task_id`` (whose lock the CALLER already holds). Streams
    progress into the task + heartbeats the lock; records result/error; fires the swarm webhook when
    ``post``; ALWAYS releases the lock + flushes the FinMind quota tally. Never raises. Returns the final
    record. ``target`` is a thunk accepting a ``progress(stage, message)`` keyword callback."""
    def _progress(stage: str, message: str = "") -> None:
        update(task_id, stage=stage, message=message)
        store.heartbeat_pipeline_lock(task_id)

    try:
        result = target(progress=_progress)
        rec = update(task_id, status="succeeded", stage="done", result=result, finished_at=_now())
        if post:
            _fire_complete(webhook_url, result)
        return rec or {}
    except Exception as e:                         # noqa: BLE001 — a run failure must not crash the worker
        log.exception("pipeline task %s failed", task_id)
        stage = (get(task_id) or {}).get("stage", "?")
        rec = update(task_id, status="failed", message=str(e), error=repr(e), finished_at=_now())
        if post:
            from . import events
            events.post(webhook_url, events.pipeline_failed_event(stage=stage, detail=str(e)))
        return rec or {}
    finally:
        store.release_pipeline_lock(task_id)
        _flush_quota()


def _fire_complete(webhook_url: str, result) -> None:
    """Fire `pipeline_complete` so downstream agents wake when the run finishes, not on a fixed cron
    (B12). No-op for non-run results (e.g. reconcile has no signals stage)."""
    if not isinstance(result, dict):
        return
    sig = result.get("stages", {}).get("signals")
    if not sig:
        return
    from . import events
    events.post(webhook_url, events.pipeline_complete_event(
        as_of=result.get("as_of"),
        candidate_count=sig.get("candidates", 0),
        signals_version=sig.get("signals_version"),
        regime=result.get("stages", {}).get("regime"),
        degraded_factors=sig.get("degraded_factors") or []))


def _flush_quota() -> None:
    """Add this process's FinMind network usage since the last flush into a per-UTC-day KV tally, so
    GET /api/system/quota reflects BOTH the server and the CLI processes (B3b). Never raises."""
    try:
        from .ingest import base
        delta = base.reset_quota_counters().get("finmind", {})
        if not (delta.get("calls") or delta.get("rate_limited")):
            return
        day = datetime.now(timezone.utc).date().isoformat()
        key = f"finmind_quota:{day}"
        raw = store.kv_get(key)
        tally = json.loads(raw) if raw else {"calls": 0, "rate_limited": 0, "last_rate_limited_at": None}
        tally["calls"] += int(delta.get("calls", 0))
        tally["rate_limited"] += int(delta.get("rate_limited", 0))
        if delta.get("last_rate_limited_at"):
            tally["last_rate_limited_at"] = delta["last_rate_limited_at"]
        store.kv_set(key, json.dumps(tally))
    except Exception as e:                         # noqa: BLE001
        log.warning("quota flush failed: %s", e)
