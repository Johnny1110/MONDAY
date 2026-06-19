# A8 — Manual round trigger (`POST /api/system/run-round`)

- **Epic**: A (engine foundations) · **Owner**: evva · **Size**: S
- **Status**: Proposed
- **Depends on**: — (uses `events.py` + `store` kv + `tasks` patterns on `main`)
- **Blocks**: B3 (morgan wakes on it), B5 (manifest), C1 (dashboard button)
- **PRD ref**: PRD-002 §workflow 啟動時機 (User 手動喚醒), §flow morgan 編排腳本 step 0, §平台改動 (手動 round 觸發); decision 1 (盤前早晨), invariant 7/8
- **Files**: `engine/monday/routers/system.py`, `engine/monday/events.py`, `engine/monday/manual.md`, `engine/tests/test_system_async.py` (extend) or new `test_round.py`

## Problem

2.0 is **human-triggered**: the User wakes Monday once a day and gets a report. 1.0 only has cron + the
`pipeline_complete` webhook. We need a thin, idempotent **"run today's round"** entry that **wakes morgan** (who then
orchestrates the whole DAG per B3) — it must NOT itself run the pipeline (morgan task_assigns data-engineer for that),
and it must not double-fire if pressed twice.

## Goal

`POST /api/system/run-round` fires a `round_requested` swarm webhook to wake morgan, once per trading day (idempotent,
`force` to override), and surfaces the decision in `/status`.

## Scope (in)

- `events.round_requested_event(as_of, requested_by)` builder (same shape/pattern as `pipeline_complete_event`).
- `POST /api/system/run-round` endpoint — idempotency guard + webhook + observability.
- `GET /api/system/status` adds `last_round_requested`.
- manual + tests.

## Out of scope

- The orchestration itself (B3 — morgan drives data-engineer → analysts → …).
- A Telegram **inbound** trigger (1.0 Telegram is outbound-only; inbound bot is a future ticket). Primary triggers: the dashboard button (C1) and the User messaging morgan in evva web.
- Running the pipeline synchronously (that stays `run-pipeline`, single-flight).

## Design

### `events.py`

Add a builder mirroring the existing ones (`pipeline_complete_event`, `portfolio_drawdown_event`, …):
```python
def round_requested_event(as_of, requested_by="user") -> dict:
    return {"title": "round_requested", "to": "morgan",
            "body": f"User requested today's round ({as_of}). Run the manual-round SOP.",
            "data": {"event_type": "round_requested", "as_of": as_of,
                     "requested_by": requested_by, "suggested_action": "run_daily_round"}}
```
(`to: "morgan"` so the swarm routes it to the leader; `suggested_action` self-describes, like the other events.)

### `POST /api/system/run-round` (`routers/system.py`)

```python
@router.post("/run-round")
def run_round(as_of: str | None = None, force: bool = False):
    """Wake morgan to run today's manual round (it then orchestrates the DAG). Idempotent: one wake per
    trading day unless force=true. Does NOT run the pipeline (morgan task_assigns data-engineer)."""
    day = as_of or store.kv_get("last_as_of") or datetime.now(timezone.utc).date().isoformat()
    already = store.kv_get(f"round_requested:{day}")
    if already and not force:
        return JSONResponse(status_code=409, content={"status": "already_requested",
                            "as_of": day, "at": already})
    ts = _now()
    store.kv_set(f"round_requested:{day}", ts)
    store.kv_set("last_round_requested", json.dumps({"as_of": day, "at": ts}))
    events.post(settings.evva_webhook_url, events.round_requested_event(day, "user"))
    log.info("run-round: woke morgan for %s (force=%s)", day, force)
    return {"status": "requested", "as_of": day, "at": ts}
```

- `events.post` is fire-and-forget (never raises); if the swarm is down it's logged (invariant 8) — the endpoint still 200s so the dashboard button gives feedback.
- `/status`: add `"last_round_requested": json.loads(store.kv_get("last_round_requested") or "null")`.

### `manual.md`

Document under "## System": purpose, idempotency, that it wakes morgan (not the pipeline), and the `round_requested` event in the event-sources section.

## Acceptance criteria

- First `POST /run-round` of the day fires exactly one `round_requested` webhook and records `round_requested:{day}` + `last_round_requested`.
- A second call the same day returns 409 `already_requested` and fires **no** second webhook; `force=true` overrides and re-fires.
- Endpoint 200s even when the swarm webhook is unreachable (logged, not raised).
- `GET /api/system/status` shows `last_round_requested`.
- Does not touch the pipeline lock or run the chain.

## Test plan

- `test_run_round_fires_once` — monkeypatch `events.post`; first call fires + records; second 409 no-fire; `force` re-fires.
- `test_run_round_webhook_safe` — `events.post` raising/unreachable ⇒ endpoint still 200 (fire-and-forget).
- `test_status_shows_last_round` — after a round request, `/status` carries it.

## Invariant & discipline checklist

- [ ] Token-free (2); webhook fire-and-forget, never raises (7,8).
- [ ] Idempotent (no double-wake) — observable decision logged (mirrors PRD-001's safety-net discipline).
- [ ] Thin: wakes morgan only; orchestration is the swarm's job (separation of platform/swarm, §2).

## Risks / edge cases

- **Day boundary / TZ**: anchor `day` on `last_as_of` (the trading day the data is for), not wall-clock UTC, to avoid a pre-open call keying the wrong date — document this.
- **Swarm down**: webhook dropped → watchdog/cron safety net still exists (B5 keeps a backstop); the 409/observability tells the User it was already requested.

## Rollout notes

Tiny + independent — build early. C1 wires the dashboard "Run today's round" button to it; B3 defines morgan's reaction; B5 keeps watchdog as the missed-wake backstop.
