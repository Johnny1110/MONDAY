"""Async pipeline endpoint + single-flight + task/quota visibility + finalize traceability
(B5/B8/B9/B10/B11/B13). Needs fastapi + httpx (TestClient); skipped on a bare interpreter."""

import json
import time
import unittest
from unittest import mock

from tests.pgtest import TEST_DSN, fresh_store, requires_pg

try:
    import fastapi  # noqa: F401
    import httpx    # noqa: F401
    HAVE = True
except Exception:
    HAVE = False


@requires_pg
@unittest.skipUnless(HAVE, "needs fastapi + httpx (TestClient)")
class TestSystemAsync(unittest.TestCase):
    def _client(self):
        from monday.config import settings
        settings.database_url = TEST_DSN
        fresh_store()                       # clean slate + release any leftover pipeline lock
        from fastapi.testclient import TestClient

        from monday import app as appmod
        return TestClient(appmod.app)        # lifespan reconnects to the same (clean) test DB

    def test_async_run_then_poll(self):
        from monday import store

        def fake_run(progress=None, **kw):
            if progress:
                progress("ingest", "")
                progress("done", "")
            return {"as_of": "2026-06-16",
                    "stages": {"signals": {"candidates": 5, "signals_version": "2026-06-16#v",
                                           "degraded_factors": []}, "regime": "neutral"}}

        with self._client() as c, mock.patch("monday.pipeline.run", fake_run):
            r = c.post("/api/system/run-pipeline?finalize=false&universe_size=30&symbols=2330,2317&post=false")
            self.assertEqual(r.status_code, 202)
            tid = r.json()["task_id"]
            t = {}
            for _ in range(200):
                t = c.get(f"/api/system/tasks/{tid}").json()
                if t["status"] in ("succeeded", "failed"):
                    break
                time.sleep(0.02)
            self.assertEqual(t["status"], "succeeded")
            self.assertEqual(t["result"]["stages"]["signals"]["candidates"], 5)
            self.assertEqual(t["params"]["universe_size"], 30)          # B5 — new params threaded
            self.assertEqual(t["params"]["symbols"], "2330,2317")
            self.assertIsNone(store.pipeline_lock_holder())             # lock released after completion

    def test_409_single_flight(self):
        from monday import store
        with self._client() as c:
            self.assertTrue(store.acquire_pipeline_lock("held", "test"))
            try:
                r = c.post("/api/system/run-pipeline")
                self.assertEqual(r.status_code, 409)
                self.assertEqual(r.json()["holder"]["task_id"], "held")
            finally:
                store.release_pipeline_lock("held")

    def test_tasks_quota_status_endpoints(self):
        with self._client() as c:
            self.assertIn("tasks", c.get("/api/system/tasks").json())
            self.assertEqual(c.get("/api/system/tasks/nope").status_code, 404)
            q = c.get("/api/system/quota").json()
            self.assertIn("rate_limited_recently", q)
            st = c.get("/api/system/status").json()
            for k in ("finmind_token_loaded", "universe_size", "pipeline"):
                self.assertIn(k, st)

    def test_signals_date_archive_route(self):
        from monday import store
        with self._client() as c:
            store.kv_set("signals:2026-06-10",
                         json.dumps({"as_of_date": "2026-06-10", "candidate_count": 2, "candidates": []}))
            self.assertEqual(c.get("/api/signals/2026-06-10").json()["candidate_count"], 2)
            self.assertTrue(c.get("/api/signals/1999-01-01").json()["note"].startswith("no archived"))
            self.assertEqual(c.get("/api/signals/today").status_code, 200)   # literal wins over {date}

    def test_finalize_stamps_version_and_locks_day(self):
        from monday import store
        from monday.ingest import finmind
        env = {"as_of_date": "2026-06-16", "model_version": "baseline-0",
               "signals_version": "2026-06-16#fv", "regime": "neutral", "candidate_count": 1,
               "candidates": [{"symbol": "2330", "name": "TSMC", "rank": 1, "score": 0.5, "close": 100.0,
                               "predicted_return": 0.05, "predicted_prob_tp": 0.6, "adv_20d": 1e6,
                               "factors": {"mom_20d": 0.1}}]}
        with self._client() as c, mock.patch.object(finmind, "fetch_stock_info", lambda *a, **k: {}):
            store.kv_set("signals_today", json.dumps(env))
            r = c.post("/api/recommendations/finalize", json={"symbols": ["2330"]})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["signals_version"], "2026-06-16#fv")
            self.assertEqual(store.kv_get("finalized:2026-06-16"), "2026-06-16#fv")
            self.assertEqual(store.get_recommendation("2026-06-16:2330")["signals_version"],
                             "2026-06-16#fv")


if __name__ == "__main__":
    unittest.main()
