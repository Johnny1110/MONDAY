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


class TestEquityCurve(unittest.TestCase):
    """The real equal-weight NAV curve (Imp #3) — pure, hand-worked scenarios."""

    def test_curve_compounds_equal_weight_daily(self):
        marks = [
            {"rec_id": "A", "mark_date": "2026-06-01", "mtm_return": 0.0},
            {"rec_id": "B", "mark_date": "2026-06-01", "mtm_return": 0.0},
            {"rec_id": "A", "mark_date": "2026-06-02", "mtm_return": 0.05},
            {"rec_id": "B", "mark_date": "2026-06-02", "mtm_return": -0.02},   # day2 mean +0.015
            {"rec_id": "A", "mark_date": "2026-06-03", "mtm_return": 0.10},
            {"rec_id": "B", "mark_date": "2026-06-03", "mtm_return": -0.06},   # day3 mean +0.005
        ]
        c = p.equity_curve(marks)
        self.assertEqual([x["date"] for x in c], ["2026-06-01", "2026-06-02", "2026-06-03"])
        self.assertAlmostEqual(c[0]["equity"], 1.0, places=4)        # entry day0 ≈ 0 → no jump
        self.assertAlmostEqual(c[1]["equity"], 1.015, places=4)
        self.assertAlmostEqual(c[2]["equity"], 1.0201, places=4)     # 1.015 × 1.005, compounded
        self.assertTrue(all(x["drawdown"] <= 0 for x in c))

    def test_drawdown_and_performance(self):
        marks = [{"rec_id": "C", "mark_date": "2026-06-01", "mtm_return": 0.0},
                 {"rec_id": "C", "mark_date": "2026-06-02", "mtm_return": -0.10}]
        c = p.equity_curve(marks)
        self.assertAlmostEqual(c[-1]["equity"], 0.9, places=4)
        self.assertAlmostEqual(c[-1]["drawdown"], -0.10, places=4)
        perf = p.performance(c)
        self.assertAlmostEqual(perf["cum_return"], -0.10, places=4)
        self.assertAlmostEqual(perf["max_drawdown"], -0.10, places=4)
        self.assertEqual(perf["days"], 2)

    def test_empty(self):
        self.assertEqual(p.equity_curve([]), [])
        self.assertEqual(p.performance([])["days"], 0)

    def test_max_drawdown_matches_triggers(self):
        from monday import triggers
        marks = [{"rec_id": "C", "mark_date": f"2026-06-0{i}", "mtm_return": m}
                 for i, m in [(1, 0.0), (2, 0.2), (3, 0.1), (4, -0.05)]]
        c = p.equity_curve(marks)
        navs = [x["equity"] for x in c]
        # performance max_drawdown is a negative fraction; triggers.max_drawdown is a positive percent
        self.assertAlmostEqual(abs(p.performance(c)["max_drawdown"]) * 100,
                               triggers.max_drawdown(navs), places=1)


if __name__ == "__main__":
    unittest.main()
