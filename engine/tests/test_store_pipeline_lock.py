"""Cross-process pipeline single-flight lock (B11) + the signals_version migration — :memory:, no deps."""

import unittest

from monday import store


class TestPipelineLock(unittest.TestCase):
    def setUp(self):
        store.connect(":memory:")

    def tearDown(self):
        store.close()

    def test_single_flight_acquire_release(self):
        self.assertTrue(store.acquire_pipeline_lock("t1", "A"))
        self.assertFalse(store.acquire_pipeline_lock("t2", "B"))      # held → refused
        self.assertEqual(store.pipeline_lock_holder()["task_id"], "t1")
        store.release_pipeline_lock("t2")                             # not the owner → no-op
        self.assertEqual(store.pipeline_lock_holder()["task_id"], "t1")
        store.release_pipeline_lock("t1")
        self.assertIsNone(store.pipeline_lock_holder())
        self.assertTrue(store.acquire_pipeline_lock("t3", "C"))       # free again

    def test_stale_lease_reclaimed(self):
        self.assertTrue(store.acquire_pipeline_lock("t1", "A"))
        self.assertFalse(store.acquire_pipeline_lock("t2", "B", stale_seconds=1800))   # fresh holder
        self.assertTrue(store.acquire_pipeline_lock("t2", "B", stale_seconds=0))       # t1 instantly stale
        self.assertEqual(store.pipeline_lock_holder()["task_id"], "t2")

    def test_reset_keeps_lock_seed_row(self):
        store.acquire_pipeline_lock("t1", "A")
        store.release_pipeline_lock("t1")
        store.reset()                                                 # wipes kv etc., not pipeline_lock
        self.assertTrue(store.acquire_pipeline_lock("t1", "A"))       # seed row still there to UPDATE

    def test_signals_version_column_roundtrips(self):
        store.add_recommendation({"rec_id": "d:2330", "as_of_date": "2026-06-16", "symbol": "2330",
                                  "direction": "long", "entry_ref_price": 100.0,
                                  "signals_version": "2026-06-16#v"})
        self.assertEqual(store.get_recommendation("d:2330")["signals_version"], "2026-06-16#v")


if __name__ == "__main__":
    unittest.main()
