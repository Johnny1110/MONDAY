"""Purged walk-forward CV (§5.4) — pure stdlib. The key property: no train date's label window
([t, t+horizon]) reaches into its validation block (no leakage)."""

import unittest

from monday.models import cv


class TestPurgedWalkForward(unittest.TestCase):
    def setUp(self):
        # 100 sequential trading days
        self.dates = [f"d{n:03d}" for n in range(100)]

    def test_no_leakage_gap(self):
        horizon, embargo, n = 10, 3, 4
        splits = cv.purged_walk_forward(self.dates, n_splits=n, horizon=horizon, embargo=embargo)
        self.assertEqual(len(splits), n)
        idx = {d: i for i, d in enumerate(self.dates)}
        for train, val in splits:
            self.assertTrue(train and val)
            last_train = max(idx[d] for d in train)
            first_val = min(idx[d] for d in val)
            # gap must be at least horizon + embargo (no label-window overlap into val)
            self.assertGreaterEqual(first_val - last_train, horizon + embargo)
            self.assertEqual(set(train) & set(val), set())   # disjoint

    def test_walk_forward_is_ordered(self):
        splits = cv.purged_walk_forward(self.dates, n_splits=3, horizon=5, embargo=2)
        idx = {d: i for i, d in enumerate(self.dates)}
        # each fold's validation block starts later than the previous one's
        starts = [min(idx[d] for d in val) for _, val in splits]
        self.assertEqual(starts, sorted(starts))

    def test_too_few_dates(self):
        self.assertEqual(cv.purged_walk_forward(["a", "b"], n_splits=4), [])


if __name__ == "__main__":
    unittest.main()
