# PRD-001 — Engine-side cron safety-net for the daily pipeline

- **Status**: Proposed (awaiting build)
- **Date**: 2026-06-16
- **Raised by**: evva (from morgan's BUG_01 / B14), per CLAUDE.md "durable capability → PRD → evva"
- **Related**: [`docs/adr/0002-live-pipeline-defaults.md`](../adr/0002-live-pipeline-defaults.md), invariant 7

## Problem

The daily pipeline is triggered **only** by swarm-side crons (morgan's `15 21 * * 1-5`, watchdog's
`*/15`). On 2026-06-16 the `monday` swarm space was **stopped** at 21:15 → nothing ran; the day's book
only appeared after a manual 22:43 HTTP trigger. The engine — which is always-on — has **no scheduler**
(`app.py` lifespan only connects the store + checks webhook reachability). So invariant 7 ("cron
**backstops** a missed webhook") is unrealized on the platform side: there is no backstop when the swarm
is down.

## Goal

A platform-level daily safety-net that guarantees the day's pipeline runs even if the swarm never wakes,
**without double-running** when morgan already triggered it.

## Requirements

1. **Always-on, engine-side.** Runs inside the FastAPI process (started/stopped in the `lifespan`),
   independent of any swarm space being up.
2. **Idempotent / no double-run.** Before triggering, check `store.kv_get("last_as_of")` (and/or the
   single-flight `pipeline_lock`): if today's trading day is already prepared/finalized, do nothing.
   Reuse `acquire_pipeline_lock` so a concurrent morgan run wins and the backstop yields.
3. **Late enough to backstop, not race.** Fire after morgan's anchor (e.g. ~21:45 local, configurable
   `SAFETY_NET_HHMM`), so morgan's 21:15 normally gets there first and the net is a true fallback.
4. **Correct live params.** Trigger with `mark_forward=0`, `post=true` (so the leader still wakes and
   composes the book via the analyst overlay — `finalize=false`, matching morgan's SOP).
5. **Timezone-correct.** Asia/Taipei wall-clock (the engine clock is UTC; today's bug also surfaced the
   need to anchor on Taipei time).
6. **Observable.** Log each tick's decision (ran / skipped-already-done / skipped-locked); surface
   `last_safety_net_fire` in `/api/system/status`.
7. **Restart-resilient.** On engine boot after the fire time with no run for today, fire once on startup.

## Design sketch (for evva)

- A lightweight daemon thread (or `asyncio` task) started in `lifespan`; no new heavy dependency —
  a simple sleep-until-next-tick loop is enough (mirrors Sunday's cron-as-safety-net pattern). APScheduler
  only if it earns its keep.
- One config block in `config.py`: `safety_net_enabled: bool = True`, `safety_net_hhmm: str = "21:45"`,
  `safety_net_tz: str = "Asia/Taipei"`.
- The trigger reuses the existing async path (`tasks` + `acquire_pipeline_lock`) — do **not** duplicate
  run logic.

## Acceptance criteria

- With the swarm space **down**, the engine runs the day's pipeline once at the configured time and fires
  `pipeline_complete`.
- With morgan's run already done, the net **skips** (no second run, no clobbered signals).
- Unit tests: (a) skips when `last_as_of == today`; (b) yields when the lock is held; (c) honours the TZ
  boundary; (d) startup catch-up fires once.
- `/api/system/status` shows `last_safety_net_fire`.

## Out of scope

- evva-side cron reliability (B14 root cause for *today* was a stopped space — operational; this PRD makes
  the platform robust **regardless** of evva).
- Changing morgan's SOP or watchdog (they remain the primary path; this is the floor under them).
