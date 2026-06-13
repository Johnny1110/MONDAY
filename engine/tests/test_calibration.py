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
        rows = [{"contributing_factors": ["mom_20d", "mom_60d"], "realized_return": 0.1},
                {"contributing_factors": ["mom_20d"], "realized_return": -0.1}]
        att = c.attribution(rows, "contributing_factors")
        self.assertEqual(att["mom_20d"]["n"], 2)
        self.assertAlmostEqual(att["mom_20d"]["mean"], 0.0)
        self.assertAlmostEqual(att["mom_60d"]["mean"], 0.1)


if __name__ == "__main__":
    unittest.main()
