"""Signals envelope: signals_version + degraded_factors (B6/B9/B13) — pure stdlib, no deps."""

import unittest

from monday import signals


class TestSignals(unittest.TestCase):
    def test_degraded_factors_all_null(self):
        rows = [{"mom_20d": 0.1, "mom_60d": None, "mom_120d": None} for _ in range(10)]
        d = signals.degraded_factors(rows, ["mom_20d", "mom_60d", "mom_120d"])
        self.assertEqual(set(d), {"mom_60d", "mom_120d"})

    def test_degraded_factors_threshold(self):
        below = [{"f": 1.0}] * 6 + [{"f": None}] * 4         # 40% null < 0.5 → not degraded
        self.assertEqual(signals.degraded_factors(below, ["f"]), [])
        at_or_above = [{"f": 1.0}] * 4 + [{"f": None}] * 6   # 60% null ≥ 0.5 → degraded
        self.assertEqual(signals.degraded_factors(at_or_above, ["f"]), ["f"])

    def test_degraded_factors_empty(self):
        self.assertEqual(signals.degraded_factors([], ["f"]), [])

    def test_build_envelope_carries_version_and_degraded(self):
        preds = [{"symbol": "2330", "name": "x", "rank": 1, "score": 0.5, "close": 100.0,
                  "predicted_return": 0.05, "predicted_prob_tp": 0.6, "adv_20d": 1e6,
                  "mom_20d": 0.1, "mom_60d": None, "mom_120d": None, "rsi_14": 60,
                  "dist_high_60d": -0.02}]
        env = signals.build_envelope("2026-06-16", "baseline-0", "neutral", preds, 50,
                                     signals_version="2026-06-16#v", degraded=["mom_120d"])
        self.assertEqual(env["signals_version"], "2026-06-16#v")
        self.assertEqual(env["degraded_factors"], ["mom_120d"])
        self.assertEqual(env["candidate_count"], 1)
        self.assertIsNone(env["candidates"][0]["factors"]["mom_60d"])

    def test_build_envelope_defaults_backward_compatible(self):
        env = signals.build_envelope("2026-06-16", "baseline-0", "neutral", [], 50)
        self.assertIsNone(env["signals_version"])
        self.assertEqual(env["degraded_factors"], [])


if __name__ == "__main__":
    unittest.main()
