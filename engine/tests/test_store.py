"""PostgreSQL store (invariant 5) — runs against a throwaway DB (skips when none reachable)."""

import unittest

from monday import store
from tests.pgtest import fresh_store, requires_pg


@requires_pg
class TestStore(unittest.TestCase):
    def setUp(self):
        fresh_store()

    def tearDown(self):
        store.close()

    def test_recommendation_roundtrip_json_cols(self):
        store.add_recommendation({
            "rec_id": "d:2330", "as_of_date": "2026-06-11", "symbol": "2330",
            "direction": "long", "entry_ref_price": 100.0, "predicted_return": 0.05,
            "predicted_prob_tp": 0.6, "conviction": 0.6, "model_version": "baseline-0",
            "contributing_factors": ["mom_20d", "mom_60d"]})
        got = store.get_recommendation("d:2330")
        self.assertEqual(got["symbol"], "2330")
        self.assertEqual(got["contributing_factors"], ["mom_20d", "mom_60d"])  # decoded JSON

    def test_position_mark_close(self):
        store.open_position("r1", "2330", "long", 100.0, "2026-06-11")
        self.assertEqual(len(store.list_positions("open")), 1)
        store.add_mark({"rec_id": "r1", "mark_date": "2026-06-12",
                        "close_price": 105.0, "mtm_return": 0.05})
        self.assertEqual(len(store.marks_for("r1")), 1)
        store.close_position("r1")
        self.assertEqual(len(store.list_positions("open")), 0)

    def test_reopen_voids_prior_outcome(self):
        # re-running a day must stay idempotent: a rec can't be both open and settled
        store.open_position("r1", "2330", "long", 100.0, "2026-06-11")
        store.add_outcome({"rec_id": "r1", "exit_date": "2026-06-12", "realized_return": 0.05,
                           "hit": True, "exit_reason": "tp"})
        self.assertIsNotNone(store.get_outcome("r1"))
        store.open_position("r1", "2330", "long", 100.0, "2026-06-11")  # re-open
        self.assertIsNone(store.get_outcome("r1"))                       # prior settlement voided

    def test_kv_and_reset(self):
        store.kv_set("k", "v")
        self.assertEqual(store.kv_get("k"), "v")
        store.reset()
        self.assertIsNone(store.kv_get("k"))

    def test_model_registry_json_cols(self):
        store.register_model("m1", factor_set=["a", "b"], regime_weights={"bull": 1})
        m = store.get_model("m1")
        self.assertEqual(m["factor_set"], ["a", "b"])
        self.assertEqual(m["regime_weights"], {"bull": 1})

    def test_journal_author_and_since_filters(self):
        # the team work log: each member journals per shift; the weekly review reads a window
        store.add_journal("old note", author="quant", date="2026-06-01")
        store.add_journal(" chip note", author="a-chips", date="2026-06-12")
        store.add_journal("quant note", author="quant", date="2026-06-12")
        self.assertEqual(len(store.list_journal()), 3)
        self.assertEqual(len(store.list_journal(author="quant")), 2)          # by teammate
        self.assertEqual(len(store.list_journal(since="2026-06-08")), 2)      # this week only
        both = store.list_journal(author="quant", since="2026-06-08")         # composable
        self.assertEqual([j["body"] for j in both], ["quant note"])


if __name__ == "__main__":
    unittest.main()
