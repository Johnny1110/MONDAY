"""Full-chain smoke (the exit gate), run on a recorded real-data fixture (no network, no fake data).
Needs venv deps (pyarrow, pydantic-settings); skipped if absent so the pure-logic suite still runs on
a bare interpreter."""

import os
import tempfile
import unittest

from tests.realdata import patched

try:
    import pyarrow  # noqa: F401
    import pydantic_settings  # noqa: F401
    HAVE_DEPS = True
except Exception:
    HAVE_DEPS = False


class TestNoSyntheticSource(unittest.TestCase):
    """Production runs on real data only — the synthetic/fake source must be gone."""

    def test_synthetic_source_removed(self):
        from monday.ingest import get_source, source_names
        self.assertEqual(source_names(), ["finmind", "twse"])
        with self.assertRaises(ValueError):
            get_source("synthetic")


@unittest.skipUnless(HAVE_DEPS, "needs venv deps (pyarrow, pydantic-settings)")
class TestPipelineSmoke(unittest.TestCase):
    def test_full_chain_end_to_end(self):
        from monday import pipeline, store
        from monday.config import settings
        with tempfile.TemporaryDirectory() as tmp:
            settings.sqlite_path = ":memory:"
            settings.data_dir = os.path.join(tmp, "data")
            store.connect(settings.sqlite_path)
            try:
                with patched():
                    s = pipeline.run(days=160, mark_forward=1)
                written = s["stages"]["recommendations"]["written"]
                self.assertGreater(written, 0)
                self.assertGreater(s["stages"]["snapshot"]["rows_on_disk"], 0)
                self.assertGreater(s["stages"]["features"]["rows"], 0)
                self.assertGreater(s["stages"]["mark_to_market"]["day0"]["marked"], 0)
                # every written idea is either still open or settled — nothing lost
                self.assertEqual(s["portfolio"]["open"] + s["portfolio"]["closed"], written)
            finally:
                store.close()

    def test_signals_only_then_compose_then_reconcile(self):
        # the swarm flow: prepare signals (no recs) → morgan composes a subset → reconcile marks them
        import json
        from monday import pipeline, store
        from monday.config import settings
        with tempfile.TemporaryDirectory() as tmp:
            settings.sqlite_path = ":memory:"
            settings.data_dir = os.path.join(tmp, "data")
            store.connect(settings.sqlite_path)
            try:
                with patched():
                    s = pipeline.run(days=160, mark_forward=1, finalize=False)
                self.assertEqual(s["stages"]["recommendations"]["written"], 0)
                self.assertGreater(s["stages"]["signals"]["candidates"], 0)
                self.assertEqual(len(store.list_positions(status="open")), 0)  # nothing auto-opened

                env = json.loads(store.kv_get("signals_today"))
                chosen = [{**c, **(c.get("factors") or {})} for c in env["candidates"][:3]]
                recs, _ = pipeline.compose_recommendations(
                    chosen, env["as_of_date"], env["model_version"], "neutral")
                self.assertEqual(len(recs), 3)
                self.assertEqual(len(store.list_positions(status="open")), 3)

                with patched():
                    r = pipeline.reconcile(days=160)
                self.assertEqual(r["marked"], 3)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
