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

    def test_envelope_surfaces_chip_and_technical_factors(self):
        # the overlay reads these from the envelope instead of re-fetching per symbol (Opt #2 / B3b)
        preds = [{"symbol": "2330", "name": "x", "rank": 1, "score": 0.5, "close": 100.0,
                  "predicted_return": 0.05, "predicted_prob_tp": 0.6, "adv_20d": 1e6,
                  "mom_20d": 0.1, "mom_60d": 0.08, "mom_120d": 0.02, "rsi_14": 60,
                  "dist_high_60d": -0.02, "atr_14": 3.2, "vol_20d": 0.25,
                  "foreign_streak": 4, "invtrust_streak": 2, "margin_chg_5d": -0.03,
                  "short_chg_5d": 0.01}]
        f = signals.build_envelope("2026-06-16", "baseline-0", "neutral", preds, 50)["candidates"][0]["factors"]
        for k in ("foreign_streak", "invtrust_streak", "margin_chg_5d", "short_chg_5d", "atr_14", "vol_20d"):
            self.assertIn(k, f)
        self.assertEqual(f["foreign_streak"], 4)
        self.assertEqual(f["atr_14"], 3.2)

    def test_build_envelope_defaults_backward_compatible(self):
        env = signals.build_envelope("2026-06-16", "baseline-0", "neutral", [], 50)
        self.assertIsNone(env["signals_version"])
        self.assertEqual(env["degraded_factors"], [])


class TestFocusScoped(unittest.TestCase):
    # full pool, rank-sorted (as the predictors emit)
    PREDS = [
        {"symbol": "2330", "name": "台積電", "rank": 1, "score": 0.9, "close": 900.0,
         "predicted_return": 0.05, "predicted_prob_tp": 0.70},
        {"symbol": "2317", "name": "鴻海", "rank": 2, "score": 0.5, "close": 200.0,
         "predicted_return": 0.03, "predicted_prob_tp": 0.60},
        {"symbol": "2454", "name": "聯發科", "rank": 3, "score": 0.4, "close": 1200.0,
         "predicted_return": 0.02, "predicted_prob_tp": 0.55},
        {"symbol": "2603", "name": "長榮", "rank": 4, "score": -0.1, "close": 150.0,
         "predicted_return": -0.01, "predicted_prob_tp": 0.45},
    ]
    SECTORS = {"2330": "半導體", "2317": "電子", "2454": "半導體", "2603": "航運"}

    def test_envelope_backcompat(self):
        # no focus args ⇒ the exact 1.0 envelope (no sector/focus keys leak in)
        env = signals.build_envelope("2026-06-19", "baseline-0", "bull_trend", self.PREDS, 50)
        self.assertEqual(env["candidate_count"], 4)
        self.assertNotIn("focus_sectors", env)
        self.assertNotIn("sector", env["candidates"][0])
        self.assertNotIn("held", env["candidates"][0])

    def test_focus_filter(self):
        env = signals.build_envelope("2026-06-19", "baseline-0", "bull_trend", self.PREDS, 50,
                                     focus_sectors=["半導體"], sector_lookup=self.SECTORS)
        syms = [c["symbol"] for c in env["candidates"]]
        self.assertEqual(syms, ["2330", "2454"])              # only 半導體, in rank order
        self.assertTrue(all(c["in_focus"] and not c["held"] for c in env["candidates"]))
        self.assertEqual(env["focus_sectors"], ["半導體"])
        self.assertEqual(env["all_ranked"], 4)
        self.assertEqual(env["unknown_sector_count"], 0)

    def test_holdings_always_included(self):
        # 2603 (航運) is outside focus but held → must appear, scored, held=True/in_focus=False
        env = signals.build_envelope("2026-06-19", "baseline-0", "bull_trend", self.PREDS, 50,
                                     focus_sectors=["半導體"], holdings=["2603"],
                                     sector_lookup=self.SECTORS)
        held = {c["symbol"]: c for c in env["candidates"]}["2603"]
        self.assertTrue(held["held"])
        self.assertFalse(held["in_focus"])
        self.assertEqual(held["score"], -0.1)                 # its real model score, not dropped
        self.assertEqual(held["rank"], 4)

    def test_full_ranking_preserved(self):
        # scoping ≠ re-ranking: scoped candidates keep their full-pool rank/score
        env = signals.build_envelope("2026-06-19", "baseline-0", "bull_trend", self.PREDS, 50,
                                     focus_sectors=["半導體"], sector_lookup=self.SECTORS)
        for c in env["candidates"]:
            src = {p["symbol"]: p for p in self.PREDS}[c["symbol"]]
            self.assertEqual((c["rank"], c["score"]), (src["rank"], round(src["score"], 4)))

    def test_holdings_unscored_reported(self):
        env = signals.build_envelope("2026-06-19", "baseline-0", "bull_trend", self.PREDS, 50,
                                     focus_sectors=["半導體"], holdings=["9999"],
                                     sector_lookup=self.SECTORS)
        self.assertEqual(env["holdings_unscored"], ["9999"])  # absent from preds → reported, not dropped
        self.assertNotIn("9999", [c["symbol"] for c in env["candidates"]])


if __name__ == "__main__":
    unittest.main()
