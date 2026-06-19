"""Daily position review (A5) — the pure hold/add/trim/exit policy, one test per branch."""

import unittest

from monday import review

CFG = {"holding_window_days": 20, "review_trim_profit_pct": 0.10,
       "review_add_conviction": 0.65, "review_trail_to_be_pct": 0.08}


def _pos(**kw):
    base = {"symbol": "2330", "avg_entry": 100.0, "qty": 1000, "take_profit": 130.0,
            "stop_loss": 90.0, "days_held": 3, "holding_window": 20}
    base.update(kw)
    return base


class TestReview(unittest.TestCase):
    def test_exit_on_sl(self):
        r = review.review_position(_pos(), {"price": 89.0}, CFG)       # price ≤ SL
        self.assertEqual(r["action"], "exit")
        self.assertEqual(r["suggested_delta_pct"], -100.0)
        self.assertEqual(r["urgency"], "high")

    def test_exit_on_timeout(self):
        r = review.review_position(_pos(days_held=20), {"price": 105.0}, CFG)
        self.assertEqual(r["action"], "exit")
        self.assertIn("timeout", r["reason"])

    def test_exit_on_broken_thesis(self):
        r = review.review_position(_pos(), {"price": 105.0, "thesis_intact": False}, CFG)
        self.assertEqual(r["action"], "exit")
        self.assertEqual(r["reason"], "thesis broken")

    def test_exit_on_double_flag(self):
        r = review.review_position(_pos(), {"price": 105.0, "technical_break": True,
                                           "chips_reversal": True}, CFG)
        self.assertEqual(r["action"], "exit")

    def test_trim_on_tp(self):
        r = review.review_position(_pos(), {"price": 131.0}, CFG)       # price ≥ TP
        self.assertEqual(r["action"], "trim")
        self.assertLess(r["suggested_delta_pct"], 0)
        self.assertGreater(r["suggested_delta_pct"], -100)             # partial, not full exit

    def test_trim_on_risk_off(self):
        r = review.review_position(_pos(), {"price": 115.0, "regime_state": "risk_off"}, CFG)
        self.assertEqual(r["action"], "trim")                         # in profit ≥10%, de-risk

    def test_trim_on_single_flag(self):
        r = review.review_position(_pos(), {"price": 105.0, "theme_exhausted": True}, CFG)
        self.assertEqual(r["action"], "trim")
        self.assertIn("theme_exhausted", r["reason"])

    def test_add_on_strong_thesis(self):
        r = review.review_position(_pos(), {"price": 105.0, "conviction": 0.7,
                                           "regime_state": "bull_trend"}, CFG)
        self.assertEqual(r["action"], "add")
        self.assertGreater(r["suggested_delta_pct"], 0)

    def test_no_add_into_broken_thesis(self):
        # conservative precedence: EXIT/TRIM beat ADD even with add-worthy conviction
        r = review.review_position(_pos(), {"price": 105.0, "conviction": 0.9,
                                           "thesis_intact": False, "regime_state": "bull_trend"}, CFG)
        self.assertEqual(r["action"], "exit")

    def test_hold_default(self):
        r = review.review_position(_pos(), {"price": 105.0}, CFG)      # no flags, modest gain
        self.assertEqual(r["action"], "hold")

    def test_hold_no_price_baseline(self):
        # mechanical baseline with no price must not crash
        r = review.review_position(_pos(), {}, CFG)
        self.assertIn(r["action"], ("hold", "exit"))                  # only timeout could fire here

    def test_trailing_stop(self):
        # up ≥ trail threshold ⇒ SL raised toward breakeven even on a HOLD
        r = review.review_position(_pos(stop_loss=90.0), {"price": 110.0}, CFG)  # +10% ≥ 8%
        self.assertEqual(r["updated_sl"], 100.0)                      # raised to entry (breakeven)

    def test_review_book_order_stable(self):
        positions = [_pos(symbol="2330"), _pos(symbol="2317"), _pos(symbol="2454")]
        ctx = {"2330": {"price": 89.0},                              # exit (SL)
               "2317": {"price": 131.0},                             # trim (TP)
               "2454": {"price": 105.0, "conviction": 0.7, "regime_state": "bull_trend"}}  # add
        out = review.review_book(positions, ctx, CFG)
        self.assertEqual([r["symbol"] for r in out], ["2330", "2317", "2454"])  # order preserved
        self.assertEqual([r["action"] for r in out], ["exit", "trim", "add"])


if __name__ == "__main__":
    unittest.main()
