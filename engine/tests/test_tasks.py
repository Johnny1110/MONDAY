"""Async task registry + the guarded runner: status/stage streaming, lock release, quota flush
(B8/B10/B11/B3b) — :memory:, no heavy deps."""

import json
import unittest
from datetime import datetime, timezone

from monday import store, tasks
from tests.pgtest import fresh_store, requires_pg


@requires_pg
class TestTasks(unittest.TestCase):
    def setUp(self):
        fresh_store()

    def tearDown(self):
        store.close()

    def test_lifecycle_and_recent(self):
        t = tasks.new_task("pipeline", {"days": 180})
        self.assertEqual(t["status"], "running")
        tasks.update(t["task_id"], status="succeeded", stage="done", result={"ok": True})
        got = tasks.get(t["task_id"])
        self.assertEqual(got["status"], "succeeded")
        self.assertEqual(got["result"], {"ok": True})
        self.assertIn(t["task_id"], [r["task_id"] for r in tasks.recent()])

    def test_index_cap_and_tombstone(self):
        ids = [tasks.new_task("k", {})["task_id"] for _ in range(tasks._INDEX_CAP + 5)]
        self.assertLessEqual(len(tasks.recent(limit=1000)), tasks._INDEX_CAP)
        self.assertIsNone(tasks.get(ids[0]))             # oldest evicted (tombstoned)
        self.assertIsNotNone(tasks.get(ids[-1]))         # newest kept

    def test_runner_success_streams_stage_and_releases_lock(self):
        t = tasks.new_task("pipeline", {})
        self.assertTrue(store.acquire_pipeline_lock(t["task_id"], "test"))

        def target(progress):
            progress("ingest", "x")
            progress("done", "")
            return {"as_of": "2026-06-16",
                    "stages": {"signals": {"candidates": 3}, "regime": "neutral"}}

        rec = tasks.runner(t["task_id"], target, post=False)
        self.assertEqual(rec["status"], "succeeded")
        self.assertEqual(tasks.get(t["task_id"])["stage"], "done")     # progress was streamed
        self.assertIsNone(store.pipeline_lock_holder())                # lock released

    def test_runner_failure_records_error_and_releases(self):
        t = tasks.new_task("pipeline", {})
        store.acquire_pipeline_lock(t["task_id"], "test")

        def boom(progress):
            raise RuntimeError("ingest exploded")

        rec = tasks.runner(t["task_id"], boom, post=False)
        self.assertEqual(rec["status"], "failed")
        self.assertIn("ingest exploded", rec["error"])
        self.assertIsNone(store.pipeline_lock_holder())                # released even on failure

    def test_quota_flush_into_daily_tally(self):
        from monday.ingest import base
        base._quota.clear()
        base._quota_bump("finmind")
        base._quota_bump("finmind", rate_limited=True)
        t = tasks.new_task("pipeline", {})
        store.acquire_pipeline_lock(t["task_id"], "test")
        tasks.runner(t["task_id"], lambda progress: {"ok": 1}, post=False)   # finally → _flush_quota
        day = datetime.now(timezone.utc).date().isoformat()
        tally = json.loads(store.kv_get(f"finmind_quota:{day}"))
        self.assertGreaterEqual(tally["calls"], 1)
        self.assertGreaterEqual(tally["rate_limited"], 1)


if __name__ == "__main__":
    unittest.main()
