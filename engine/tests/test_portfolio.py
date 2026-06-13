"""Mark-to-market math (§6.1) — pure functions, runs anywhere."""

import unittest

from monday import portfolio as p


class TestPortfolioMath(unittest.TestCase):
    def test_mtm_long_and_short(self):
        self.assertAlmostEqual(p.mtm_return(100, 110, "long"), 0.10)
        self.assertAlmostEqual(p.mtm_return(100, 90, "short"), 0.10)
        self.assertEqual(p.mtm_return(0, 90), 0.0)

    def test_hit_tp_sl_long(self):
        self.assertEqual(p.hit_tp_sl(110, 90, 112, 95, "long"), (True, False))
        self.assertEqual(p.hit_tp_sl(110, 90, 105, 88, "long"), (False, True))

    def test_hit_tp_sl_short(self):
        # short: TP when low ≤ tp, SL when high ≥ sl
        self.assertEqual(p.hit_tp_sl(90, 110, 108, 88, "short"), (True, False))

    def test_settle_error_is_realized_minus_predicted(self):
        oc = p.settle(100, 108, 0.05, "long", "tp")
        self.assertAlmostEqual(oc["realized_return"], 0.08)
        self.assertTrue(oc["hit"])
        self.assertAlmostEqual(oc["error"], 0.03)
        self.assertEqual(oc["exit_reason"], "tp")


if __name__ == "__main__":
    unittest.main()
