"""Conviction calibration map — PAV isotonic (§6 / Imp #1). Pure stdlib."""

import random
import unittest

from monday import calibmap


class TestCalibMap(unittest.TestCase):
    def test_identity_on_thin_data(self):
        m = calibmap.fit([(0.7, 1.0), (0.3, 0.0)], min_samples=30)
        self.assertEqual(m, calibmap.IDENTITY)
        self.assertEqual(calibmap.apply(m, 0.7), 0.7)       # identity passthrough
        self.assertIsNone(calibmap.apply(m, None))

    def test_fit_corrects_overconfidence(self):
        # over-confident model: 0.9 predicted but only ~50% hit; 0.2 predicted ~0% hit
        pairs = [(0.9, 1.0)] * 40 + [(0.9, 0.0)] * 40 + [(0.2, 0.0)] * 40
        m = calibmap.fit(pairs, min_samples=10)
        self.assertNotEqual(m, calibmap.IDENTITY)
        self.assertLess(calibmap.apply(m, 0.9), 0.8)        # pulled down toward observed ~0.5
        self.assertLessEqual(calibmap.apply(m, 0.2), 0.2)
        self.assertLessEqual(calibmap.apply(m, 0.2), calibmap.apply(m, 0.9))   # monotone

    def test_apply_flat_outside_and_interpolates(self):
        m = [[0.2, 0.1], [0.8, 0.6]]
        self.assertEqual(calibmap.apply(m, 0.0), 0.1)       # below first knot → flat
        self.assertEqual(calibmap.apply(m, 1.0), 0.6)       # above last knot → flat
        self.assertTrue(0.1 < calibmap.apply(m, 0.5) < 0.6)  # interpolated

    def test_fit_is_monotone_non_decreasing(self):
        random.seed(1)
        pairs = [(round(random.random(), 2), float(random.random() < 0.5)) for _ in range(300)]
        ys = [y for _, y in calibmap.fit(pairs, min_samples=10)]
        self.assertEqual(ys, sorted(ys))                    # PAV guarantees non-decreasing


if __name__ == "__main__":
    unittest.main()
