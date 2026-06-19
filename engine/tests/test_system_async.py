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

    def test_run_round_fires_once(self):
        from monday import events, store
        with self._client() as c, mock.patch.object(events, "post") as ep:
            store.kv_set("last_as_of", "2026-06-19")
            r = c.post("/api/system/run-round")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["as_of"], "2026-06-19")
            self.assertEqual(ep.call_count, 1)                       # exactly one wake
            ev = ep.call_args[0][1]                                  # post(url, payload)
            self.assertEqual(ev["data"]["event_type"], "round_requested")
            self.assertEqual(ev["to"], "morgan")
            self.assertIsNotNone(store.kv_get("round_requested:2026-06-19"))
            # second call the same day → 409, NO second webhook
            r2 = c.post("/api/system/run-round")
            self.assertEqual(r2.status_code, 409)
            self.assertEqual(r2.json()["status"], "already_requested")
            self.assertEqual(ep.call_count, 1)
            # force overrides → re-fires
            self.assertEqual(c.post("/api/system/run-round?force=true").status_code, 200)
            self.assertEqual(ep.call_count, 2)
            self.assertIsNone(store.pipeline_lock_holder())          # never touched the pipeline lock

    def test_run_round_webhook_safe(self):
        # fire-and-forget: an unreachable swarm must NOT 500 the endpoint (invariant 8)
        from monday import store
        from monday.config import settings
        orig = settings.evva_webhook_url
        with self._client() as c:
            settings.evva_webhook_url = "http://127.0.0.1:1/dead"   # real events.post → connection refused
            try:
                store.kv_set("last_as_of", "2026-06-19")
                r = c.post("/api/system/run-round")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["status"], "requested")
            finally:
                settings.evva_webhook_url = orig

    def test_status_shows_last_round(self):
        from monday import events, store
        with self._client() as c, mock.patch.object(events, "post"):
            store.kv_set("last_as_of", "2026-06-19")
            c.post("/api/system/run-round")
            st = c.get("/api/system/status").json()
            self.assertIn("last_round_requested", st)
            self.assertEqual(st["last_round_requested"]["as_of"], "2026-06-19")

    def test_finalize_replaces_not_appends(self):
        """Each finalize is a complete new book — old open positions are closed, not accumulated."""
        from monday import store
        from monday.ingest import finmind
        env = {"as_of_date": "2026-06-17", "model_version": "baseline-0",
               "signals_version": "2026-06-17#fv", "regime": "neutral", "candidate_count": 3,
               "candidates": [
                   {"symbol": "2330", "name": "TSMC", "rank": 1, "score": 0.5, "close": 100.0,
                    "predicted_return": 0.05, "predicted_prob_tp": 0.6, "adv_20d": 1e6,
                    "factors": {"mom_20d": 0.1}},
                   {"symbol": "2317", "name": "HonHai", "rank": 2, "score": 0.4, "close": 80.0,
                    "predicted_return": 0.03, "predicted_prob_tp": 0.55, "adv_20d": 2e6,
                    "factors": {"mom_20d": 0.05}},
                   {"symbol": "2454", "name": "MTK", "rank": 3, "score": 0.35, "close": 600.0,
                    "predicted_return": 0.04, "predicted_prob_tp": 0.5, "adv_20d": 1.5e6,
                    "factors": {"mom_20d": 0.08}},
               ]}
        with self._client() as c, mock.patch.object(finmind, "fetch_stock_info", lambda *a, **k: {}):
            store.kv_set("signals_today", json.dumps(env))
            # First finalize: pick 2 symbols
            r1 = c.post("/api/recommendations/finalize", json={"symbols": ["2330", "2317"]})
            self.assertEqual(r1.status_code, 200, r1.text)
            open_pos = store.list_positions(status="open")
            self.assertEqual(len(open_pos), 2)
            open_syms = {p["symbol"] for p in open_pos}
            self.assertEqual(open_syms, {"2330", "2317"})

            # Second finalize: pick 1 different symbol — old 2 should close, only 1 open
            r2 = c.post("/api/recommendations/finalize", json={"symbols": ["2454"]})
            self.assertEqual(r2.status_code, 200, r2.text)
            open_pos = store.list_positions(status="open")
            self.assertEqual(len(open_pos), 1)
            self.assertEqual(open_pos[0]["symbol"], "2454")

            # No duplicates — only one position per symbol exists at any time
            all_pos = store.list_positions()
            sym_status = {(p["symbol"], p["status"]) for p in all_pos}
            self.assertEqual(sym_status, {("2454", "open"), ("2330", "closed"), ("2317", "closed")})


if __name__ == "__main__":
    unittest.main()
