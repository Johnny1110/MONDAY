"""Calibration math (§6.1) — pure stdlib, runs anywhere."""

import unittest

from monday import calibration as c


class TestCalibration(unittest.TestCase):
    def test_rank_ic_perfect_and_inverse(self):
        self.assertAlmostEqual(c.rank_ic([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(c.rank_ic([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)

    def test_rank_ic_insufficient(self):
        self.assertIsNone(c.rank_ic([1], [2]))

    def test_hit_rate(self):
        self.assertEqual(c.hit_rate([0.1, -0.2, 0.3, -0.1]), 0.5)

    def test_avg_win_loss(self):
        aw, al = c.avg_win_loss([0.2, -0.1, 0.4, -0.3])
        self.assertAlmostEqual(aw, 0.3)
        self.assertAlmostEqual(al, -0.2)

    def test_calibration_curve_shape(self):
        curve = c.calibration_curve([0.05, 0.15, 0.95], [False, False, True], bins=10)
        self.assertTrue(curve)
        for b in curve:
            self.assertGreaterEqual(set(b), {"bin", "mean_pred", "observed", "n"})

    def test_attribution_list_key(self):
        """Returns split equally among contributing factors — each factor gets realized_return / n."""
        rows = [{"contributing_factors": ["mom_20d", "mom_60d"], "realized_return": 0.1},
                {"contributing_factors": ["mom_20d"], "realized_return": -0.1}]
        att = c.attribution(rows, "contributing_factors")
        # Row 1: mom_20d += 0.05, mom_60d += 0.05. Row 2: mom_20d += -0.1
        # mom_20d: [0.05, -0.1] → mean = -0.025
        # mom_60d: [0.05] → mean = 0.05
        self.assertEqual(att["mom_20d"]["n"], 2)
        self.assertAlmostEqual(att["mom_20d"]["mean"], -0.025)
        self.assertEqual(att["mom_60d"]["n"], 1)
        self.assertAlmostEqual(att["mom_60d"]["mean"], 0.05)

    def test_attribution_scalar_key_unchanged(self):
        """Scalar keys (e.g. regime_label) still get the full return — splitting only applies to lists."""
        rows = [{"regime_label": "bull_trend", "realized_return": 0.1},
                {"regime_label": "bull_trend", "realized_return": -0.05},
                {"regime_label": "choppy", "realized_return": 0.02}]
        att = c.attribution(rows, "regime_label")
        self.assertEqual(att["bull_trend"]["n"], 2)
        self.assertAlmostEqual(att["bull_trend"]["mean"], 0.025)
        self.assertEqual(att["choppy"]["n"], 1)
        self.assertAlmostEqual(att["choppy"]["mean"], 0.02)

    def test_attribution_empty_list_skipped(self):
        rows = [{"contributing_factors": [], "realized_return": 0.1}]
        att = c.attribution(rows, "contributing_factors")
        self.assertEqual(att, {})

    def test_brier_perfect_vs_overconfident(self):
        self.assertEqual(c.brier([1.0, 0.0, 1.0], [True, False, True]), 0.0)   # perfect
        # over-confident 0.9 that only half hit → (0.9-1)²/2 + (0.9-0)²/2 = 0.005 + 0.405 = 0.41
        self.assertAlmostEqual(c.brier([0.9, 0.9], [True, False]), 0.41, places=4)
        self.assertIsNone(c.brier([], []))

    def test_reliability_gap(self):
        curve = [{"bin": 7, "mean_pred": 0.7, "observed": 0.5, "n": 10},   # 0.2 off
                 {"bin": 2, "mean_pred": 0.2, "observed": 0.2, "n": 30}]   # spot on
        # count-weighted: (0.2×10 + 0×30) / 40 = 0.05
        self.assertAlmostEqual(c.reliability_gap(curve), 0.05, places=4)
        self.assertIsNone(c.reliability_gap([]))


if __name__ == "__main__":
    unittest.main()
