"""Training labels (§5.2) — pure stdlib, runs anywhere."""

import unittest

from monday.models import labels


class TestLabels(unittest.TestCase):
    def test_forward_return(self):
        closes = [100, 105, 110, 120]
        self.assertAlmostEqual(labels.forward_return(closes, 0, 2), 0.10)   # 100→110
        self.assertAlmostEqual(labels.forward_return(closes, 1, 2), 120 / 105 - 1)
        self.assertIsNone(labels.forward_return(closes, 2, 2))              # window past data

    def test_touch_tp(self):
        closes = [100, 100, 100, 100]
        highs = [100, 104, 109, 100]
        self.assertEqual(labels.touch_tp(closes, highs, 0, 3, 0.08), 1)     # high 109 ≥ 108
        self.assertEqual(labels.touch_tp(closes, highs, 0, 3, 0.10), 0)     # need 110, max is 109
        self.assertIsNone(labels.touch_tp(closes, highs, 2, 3, 0.08))       # window past data

    def test_quantile_buckets(self):
        g = labels.quantile_buckets([0.5, -0.2, 0.9, 0.1], 4)
        self.assertEqual(g[2], 3)                                           # highest → top grade
        self.assertEqual(g[1], 0)                                           # lowest → grade 0
        self.assertEqual(len(g), 4)

    def test_quantile_buckets_with_none(self):
        g = labels.quantile_buckets([0.5, None, 0.9], 4)
        self.assertEqual(g[1], 0)                                           # None → grade 0


if __name__ == "__main__":
    unittest.main()
