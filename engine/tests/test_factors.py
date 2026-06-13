"""Factor math (§4.3) — pure stdlib, runs anywhere."""

import unittest

from monday.featurestore import factors


class TestFactors(unittest.TestCase):
    def test_total_return(self):
        self.assertAlmostEqual(factors.total_return([100, 110], 1), 0.10)
        self.assertIsNone(factors.total_return([100], 1))

    def test_sma(self):
        self.assertEqual(factors.sma([1, 2, 3, 4], 2), 3.5)
        self.assertIsNone(factors.sma([1], 2))

    def test_dist_from_high(self):
        self.assertAlmostEqual(factors.dist_from_high([10, 20, 15], 3), 15 / 20 - 1)

    def test_rsi_all_gains_is_100(self):
        self.assertEqual(factors.rsi([1, 2, 3, 4, 5], 4), 100.0)

    def test_rsi_in_range(self):
        r = factors.rsi([1, 2, 1, 2, 1, 2, 1, 2], 4)
        self.assertTrue(0.0 <= r <= 100.0)

    def test_realized_vol_constant_is_zero(self):
        self.assertEqual(factors.realized_vol([5, 5, 5, 5], 3), 0.0)

    def test_atr(self):
        self.assertEqual(factors.atr([10, 11, 12], [9, 10, 11], [9.5, 10.5, 11.5], 2), 1.5)


if __name__ == "__main__":
    unittest.main()
