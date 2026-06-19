"""Calibration math (§6.1) — pure stdlib, runs anywhere. A9 adds macro-call + position-mgmt dims."""

import tempfile
import unittest

from monday import calibration as c
from tests.pgtest import fresh_store, requires_pg

try:
    import pyarrow  # noqa: F401
    HAVE_PYARROW = True
except Exception:
    HAVE_PYARROW = False


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


class TestJudgementCalibration(unittest.TestCase):
    """A9 — macro-call accuracy + position-management value-add (pure)."""

    def test_macro_correct_rule(self):
        self.assertEqual(c.score_macro_call("risk_on", 0.05, 0.01), 1)
        self.assertEqual(c.score_macro_call("risk_on", 0.005, 0.01), 0)   # within band → not 'up'
        self.assertEqual(c.score_macro_call("risk_off", -0.05, 0.01), 1)
        self.assertEqual(c.score_macro_call("risk_off", 0.02, 0.01), 0)
        self.assertEqual(c.score_macro_call("neutral", 0.005, 0.01), 1)   # flat within band
        self.assertEqual(c.score_macro_call("neutral", 0.05, 0.01), 0)
        self.assertIsNone(c.score_macro_call("risk_on", None, 0.01))      # unsettled

    def test_macro_call_accuracy(self):
        calls = [{"risk_state": "risk_on", "correct": 1, "realized_index_fwd_ret": 0.04},
                 {"risk_state": "risk_on", "correct": 0, "realized_index_fwd_ret": -0.01},
                 {"risk_state": "risk_off", "correct": 1, "realized_index_fwd_ret": -0.03},
                 {"risk_state": "neutral", "correct": None}]              # unsettled → excluded
        a = c.macro_call_accuracy(calls)
        self.assertEqual(a["n"], 3)
        self.assertAlmostEqual(a["hit_rate"], 2 / 3, places=4)
        self.assertEqual(a["by_risk_state"]["risk_on"]["n"], 2)
        self.assertAlmostEqual(a["by_risk_state"]["risk_on"]["hit_rate"], 0.5)
        self.assertAlmostEqual(a["avg_fwd_when_risk_on"], (0.04 - 0.01) / 2)

    def test_position_mgmt_value(self):
        actions = [{"action": "exit", "symbol": "A", "action_date": "d1"},   # well-timed
                   {"action": "exit", "symbol": "B", "action_date": "d2"},   # premature
                   {"action": "hold", "symbol": "C", "action_date": "d3"}]   # ignored
        lookup = {("A", "d1"): {"realized": 0.05, "hold": -0.03},   # avoided a drop → +0.08
                  ("B", "d2"): {"realized": 0.05, "hold": 0.15}}    # missed a run-up → -0.10
        v = c.position_mgmt_value(actions, lookup)
        self.assertEqual((v["n"], v["n_exit"]), (2, 2))
        self.assertAlmostEqual(v["exit_value_add_mean"], (0.08 - 0.10) / 2)
        self.assertAlmostEqual(v["pct_actions_value_positive"], 0.5)

    def test_macro_drift_detect(self):
        from monday import triggers
        self.assertIsNone(triggers.detect_macro_drift([0.6, 0.4, 0.4], 0.5, 3))  # not all below floor
        ev = triggers.detect_macro_drift([0.4, 0.3, 0.45], 0.5, 3)
        self.assertEqual(ev["data"]["event_type"], "macro_drift")
        self.assertIsNone(triggers.detect_macro_drift([0.4, None, 0.3], 0.5, 3))  # gap breaks the streak


@requires_pg
@unittest.skipUnless(HAVE_PYARROW, "needs pyarrow for the macro snapshot")
class TestMacroSettlement(unittest.TestCase):
    """A9 settlement + scorecard folding (store + macro snapshots)."""

    def setUp(self):
        from monday.config import settings
        self.tmp = tempfile.mkdtemp()
        settings.data_dir = self.tmp
        fresh_store()

    def tearDown(self):
        from monday import store
        store.close()

    def _twii(self, date, close):
        from monday import macro
        macro.write_macro_snapshot(self.tmp, date, [{"symbol": "^TWII", "close": close,
                                                     "asset_class": "equity_index"}])

    def test_settle_macro_calls_and_idempotent(self):
        from monday import store
        from monday.routers import calibration as cal
        self._twii("2026-05-01", 20000.0)
        self._twii("2026-05-21", 21000.0)                       # +5% over the 20d horizon
        store.add_macro_call({"call_id": "2026-05-01", "call_date": "2026-05-01",
                              "risk_state": "risk_on", "horizon_days": 20})
        r = cal.settle_macro_calls("2026-05-21")
        self.assertEqual(r["settled"], 1)
        got = store.get_macro_call("2026-05-01")
        self.assertEqual(got["correct"], 1)                     # risk_on + +5% → correct
        self.assertAlmostEqual(got["realized_index_fwd_ret"], 0.05, places=3)
        self.assertEqual(cal.settle_macro_calls("2026-05-21")["settled"], 0)   # idempotent

    def test_settle_skips_unmatured(self):
        from monday import store
        from monday.routers import calibration as cal
        self._twii("2026-05-01", 20000.0)
        store.add_macro_call({"call_id": "2026-05-01", "call_date": "2026-05-01",
                              "risk_state": "risk_on", "horizon_days": 20})
        self.assertEqual(cal.settle_macro_calls("2026-05-10")["settled"], 0)   # not matured yet
        self.assertIsNone(store.get_macro_call("2026-05-01")["correct"])

    def test_scorecard_carries_new_dims(self):
        from monday import store
        from monday.routers import calibration as cal
        self._twii("2026-05-01", 20000.0)
        self._twii("2026-05-21", 19000.0)                       # -5% → risk_off correct
        store.add_macro_call({"call_id": "2026-05-01", "call_date": "2026-05-01",
                              "risk_state": "risk_off", "horizon_days": 20})
        cal.settle_macro_calls("2026-05-21")
        run = cal.save_run(post=False)
        self.assertIn("macro", run)                             # response carries the dims
        self.assertIn("position_mgmt", run)
        self.assertIn("macro", run["adjustments"])              # and they're stored in the scorecard JSON
        self.assertEqual(run["adjustments"]["macro"]["n"], 1)
        for k in ("hit_rate", "ic", "avg_win", "avg_loss"):     # stock-pick fields intact
            self.assertIn(k, run)


if __name__ == "__main__":
    unittest.main()
