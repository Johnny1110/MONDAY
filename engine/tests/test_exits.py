"""ATR-scaled TP/SL (§5.5 / Imp #2) — pure stdlib."""

import unittest

from monday import exits


class TestExits(unittest.TestCase):
    def test_fixed_fallback_reproduces_old_band(self):
        # atr None → exactly the original behaviour: TP=max(E[ret],8%), SL=-8%
        tp, sl, basis = exits.tp_sl_prices(100.0, 0.05, None, "long")
        self.assertEqual(basis, "fixed")
        self.assertEqual(tp, 108.0)      # max(0.05, 0.08) = 0.08
        self.assertEqual(sl, 92.0)
        tp2, _, _ = exits.tp_sl_prices(100.0, 0.12, None, "long")
        self.assertEqual(tp2, 112.0)     # E[ret] 12% beats the 8% floor

    def test_atr_scales_stop_high_vs_low_vol(self):
        hi_tp, hi_sl, basis = exits.tp_sl_prices(100.0, 0.05, 5.0, "long")   # ATR 5% → SL 10%
        self.assertEqual(basis, "atr")
        lo_tp, lo_sl, _ = exits.tp_sl_prices(100.0, 0.05, 1.0, "long")       # ATR 1% → SL clamped to 4%
        self.assertLess(hi_sl, lo_sl)            # higher vol → wider (lower) stop price
        self.assertEqual(lo_sl, 96.0)            # 2×1% = 2% < floor 4% → 4%
        self.assertEqual(hi_sl, 90.0)            # 2×5% = 10%
        self.assertGreater(hi_tp, lo_tp)         # higher vol → wider TP

    def test_sl_clamped_to_cap(self):
        _, sl, _ = exits.tp_sl_prices(100.0, 0.0, 20.0, "long")   # 2×20% = 40% → capped 15%
        self.assertEqual(sl, 85.0)

    def test_short_mirrors(self):
        tp, sl, _ = exits.tp_sl_prices(100.0, 0.05, 3.0, "short")
        self.assertLess(tp, 100.0)               # short TP is below entry
        self.assertGreater(sl, 100.0)            # short SL is above entry


if __name__ == "__main__":
    unittest.main()
