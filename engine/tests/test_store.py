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

    # --- 2.0 managed book / position log / macro calls / daily report (A1) ----

    def test_book_position_roundtrip(self):
        # the 2.0 managed book: qty-aware lots, distinct from the 1.0 paper_positions sim
        store.upsert_book_position({
            "position_id": "real:2330:2026-06-19", "book": "real", "symbol": "2330",
            "name": "台積電", "qty": 2000, "avg_entry": 900.0, "opened_at": "2026-06-19",
            "source": "morgan", "sizing_pct": 15.0, "take_profit": 1000.0, "stop_loss": 850.0})
        got = store.get_book_position("real:2330:2026-06-19")
        self.assertEqual(got["symbol"], "2330")
        self.assertEqual(got["qty"], 2000)
        self.assertEqual(got["book"], "real")
        self.assertEqual(got["status"], "open")             # schema default applied
        self.assertEqual(got["direction"], "long")          # schema default applied
        # upsert is idempotent on the PK (re-insert overwrites, no duplicate)
        store.upsert_book_position({
            "position_id": "real:2330:2026-06-19", "book": "real", "symbol": "2330",
            "qty": 3000, "avg_entry": 910.0, "opened_at": "2026-06-19"})
        self.assertEqual(store.get_book_position("real:2330:2026-06-19")["qty"], 3000)
        self.assertEqual(len(store.list_book_positions(book="real")), 1)
        # a paper lot is separate; book + status filters compose
        store.upsert_book_position({
            "position_id": "paper:2454:2026-06-19", "book": "paper", "symbol": "2454",
            "qty": 1000, "avg_entry": 1200.0, "opened_at": "2026-06-19"})
        self.assertEqual(len(store.list_book_positions()), 2)
        self.assertEqual(len(store.list_book_positions(book="paper")), 1)
        self.assertEqual(len(store.list_book_positions(status="open")), 2)
        store.close_book_position("real:2330:2026-06-19")
        self.assertEqual(store.get_book_position("real:2330:2026-06-19")["status"], "closed")
        self.assertEqual(len(store.list_book_positions(book="real", status="open")), 0)

    def test_position_actions_log(self):
        # append-only lifecycle log — the substrate for position-mgmt calibration (A9)
        store.add_position_action({"position_id": "real:2330:2026-06-01", "symbol": "2330",
                                   "action_date": "2026-06-01", "action": "open",
                                   "new_qty": 2000, "delta_qty": 2000, "regime": "bull_trend"})
        store.add_position_action({"position_id": "real:2330:2026-06-01", "symbol": "2330",
                                   "action_date": "2026-06-10", "action": "trim",
                                   "prev_qty": 2000, "delta_qty": -1000, "new_qty": 1000,
                                   "reason": "技術轉弱"})
        a = store.add_position_action({"position_id": "real:2330:2026-06-01", "symbol": "2330",
                                       "action_date": "2026-06-18", "action": "exit",
                                       "prev_qty": 1000, "delta_qty": -1000, "new_qty": 0})
        self.assertIsNotNone(a["action_id"])                # DB-assigned identity
        self.assertEqual(a["decided_by"], "morgan")         # default applied
        self.assertEqual(len(store.list_position_actions(position_id="real:2330:2026-06-01")), 3)
        self.assertEqual(len(store.list_position_actions(since="2026-06-05")), 2)  # date window
        self.assertEqual(store.list_position_actions()[0]["action"], "exit")       # newest-first

    def test_macro_call_roundtrip_and_update(self):
        store.add_macro_call({"call_id": "2026-06-19", "call_date": "2026-06-19",
                              "risk_state": "risk_on", "horizon_days": 20,
                              "sectors_favored": ["半導體", "AI伺服器"],
                              "sectors_avoid": ["航運"], "rationale": "費半創高"})
        got = store.get_macro_call("2026-06-19")
        self.assertEqual(got["risk_state"], "risk_on")
        self.assertEqual(got["sectors_favored"], ["半導體", "AI伺服器"])   # decoded JSON list
        self.assertEqual(got["by"], "macro-analyst")                       # default
        self.assertIsNone(got["correct"])                                  # unsettled
        store.add_macro_call({"call_id": "2026-06-12", "call_date": "2026-06-12",
                              "risk_state": "neutral"})
        self.assertEqual(len(store.list_macro_calls()), 2)
        self.assertEqual(len(store.list_macro_calls(since="2026-06-15")), 1)  # window
        # A9 settlement patches the realized result + score
        upd = store.update_macro_call("2026-06-19", realized_index_fwd_ret=0.03, correct=1)
        self.assertEqual(upd["correct"], 1)
        self.assertAlmostEqual(upd["realized_index_fwd_ret"], 0.03)
        # unknown keys are ignored (no column injection)
        store.update_macro_call("2026-06-19", bogus="x")
        self.assertEqual(store.get_macro_call("2026-06-19")["correct"], 1)

    def test_daily_report_roundtrip(self):
        store.add_daily_report({"as_of": "2026-06-19", "regime": "bull_trend",
                                "risk_state": "risk_on",
                                "data": {"sections": {"macro": "費半創高"},
                                         "disclaimer": "研究意見，下單與盈虧 User 自負"},
                                "summary_text": "今日定調：偏多"})
        got = store.get_daily_report("2026-06-19")
        self.assertEqual(got["regime"], "bull_trend")
        self.assertEqual(got["data"]["sections"]["macro"], "費半創高")      # decoded dict
        self.assertIn("disclaimer", got["data"])
        # latest-for-date: a second post that day wins on read
        store.add_daily_report({"as_of": "2026-06-19", "data": {"v": 2}})
        self.assertEqual(store.get_daily_report("2026-06-19")["data"], {"v": 2})
        self.assertEqual(len(store.list_daily_reports()), 2)

    def test_reset_includes_new_tables(self):
        store.upsert_book_position({"position_id": "p1", "symbol": "2330", "qty": 1,
                                    "avg_entry": 1.0, "opened_at": "2026-06-19"})
        store.add_position_action({"symbol": "2330", "action_date": "2026-06-19", "action": "open"})
        store.add_macro_call({"call_id": "c1", "call_date": "2026-06-19"})
        store.add_daily_report({"as_of": "2026-06-19", "data": {"x": 1}})
        counts = store.reset()
        for t in ("book_positions", "position_actions", "macro_calls", "daily_report"):
            self.assertEqual(counts[t], 1)                   # one row each, all wiped
        self.assertEqual(store.list_book_positions(), [])
        self.assertEqual(store.list_position_actions(), [])
        self.assertEqual(store.list_macro_calls(), [])
        self.assertEqual(store.list_daily_reports(), [])


if __name__ == "__main__":
    unittest.main()
