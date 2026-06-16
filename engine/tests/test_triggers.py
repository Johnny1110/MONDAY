"""Calibration drift / factor-decay detectors (§6.3, Opt #3) — pure stdlib, no store/PG."""

import unittest

from monday import triggers


class TestCalibrationTriggers(unittest.TestCase):
    def test_drift_fires_when_ic_below_floor_for_n(self):
        ev = triggers.detect_calibration_drift([0.1, -0.01, -0.02, -0.03], floor=0.0, weeks=3)
        self.assertIsNotNone(ev)
        self.assertEqual(ev["data"]["event_type"], "calibration_drift")
        self.assertEqual(ev["data"]["weeks"], 3)
        self.assertEqual(ev["to"], "quant-researcher")

    def test_drift_silent_when_recent_above_floor(self):
        self.assertIsNone(triggers.detect_calibration_drift([-0.1, -0.1, 0.05], floor=0.0, weeks=3))

    def test_drift_silent_on_short_or_gapped_history(self):
        self.assertIsNone(triggers.detect_calibration_drift([-0.1, -0.1], 0.0, 3))         # too short
        self.assertIsNone(triggers.detect_calibration_drift([-0.1, None, -0.1], 0.0, 3))   # gap breaks streak

    def test_factor_decay_fires_per_negative_factor(self):
        series = {"mom_20d": [-0.01, -0.02, -0.03], "chips": [0.02, 0.01, 0.03]}
        evs = triggers.detect_factor_decay(series, periods=3)
        kinds = {(e["data"]["event_type"], e["data"]["factor"]) for e in evs}
        self.assertIn(("factor_decay", "mom_20d"), kinds)
        self.assertNotIn(("factor_decay", "chips"), kinds)        # still positive → not decayed

    def test_factor_decay_silent_on_gap(self):
        self.assertEqual(triggers.detect_factor_decay({"f": [-0.1, None, -0.1]}, 3), [])

    def test_calibration_series_extracts_ic_and_factor_means(self):
        runs = [
            {"run_id": "c2", "run_date": "2026-06-08", "ic": -0.02,
             "attribution": {"mom_20d": {"mean": -0.01, "n": 5}}},
            {"run_id": "c1", "run_date": "2026-06-01", "ic": 0.1,         # out of order on purpose
             "attribution": {"mom_20d": {"mean": 0.02, "n": 5}}},
        ]
        ic_hist, factor_means = triggers.calibration_series(runs)
        self.assertEqual(ic_hist, [0.1, -0.02])                          # sorted oldest-first
        self.assertEqual(factor_means["mom_20d"], [0.02, -0.01])

    def test_evaluate_calibration_end_to_end(self):
        runs = [{"run_id": f"c{i}", "run_date": f"2026-06-0{i}", "ic": -0.05,
                 "attribution": {"mom_20d": {"mean": -0.02, "n": 5}}} for i in range(1, 4)]
        fired = triggers.evaluate_calibration(runs, ic_floor=0.0, drift_weeks=3, decay_periods=3)
        kinds = {e["data"]["event_type"] for e in fired}
        self.assertIn("calibration_drift", kinds)
        self.assertIn("factor_decay", kinds)

    def test_evaluate_calibration_quiet_on_healthy_history(self):
        runs = [{"run_id": f"c{i}", "run_date": f"2026-06-0{i}", "ic": 0.06,
                 "attribution": {"mom_20d": {"mean": 0.03, "n": 5}}} for i in range(1, 4)]
        self.assertEqual(triggers.evaluate_calibration(runs, ic_floor=0.0, drift_weeks=3, decay_periods=3), [])


if __name__ == "__main__":
    unittest.main()
