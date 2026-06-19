"""Position sizing (A4) — pure risk-budget math: monotonicity, regime scaling, caps, lot rounding."""

import unittest

from monday import sizing


def _size(conviction=0.8, atr_stop_pct=0.08, regime="bull_trend", max_pos=20.0,
          book_value=1_000_000.0, price=100.0, rb=1.0):
    return sizing.suggest_size(conviction, atr_stop_pct, risk_budget_pct=rb, regime_state=regime,
                               max_position_pct=max_pos, book_value=book_value, price=price)


class TestSizing(unittest.TestCase):
    def test_risk_budget_monotonicity(self):
        # conviction ↑ ⇒ size ↑
        lo = _size(conviction=0.4)["suggested_pct"]
        hi = _size(conviction=0.9)["suggested_pct"]
        self.assertGreater(hi, lo)
        # tighter stop ⇒ larger size (risk parity), same risk budget
        tight = _size(atr_stop_pct=0.05)["suggested_pct"]
        wide = _size(atr_stop_pct=0.10)["suggested_pct"]
        self.assertGreater(tight, wide)

    def test_regime_scaling(self):
        off = _size(regime="risk_off")["suggested_pct"]
        neu = _size(regime="neutral")["suggested_pct"]
        bull = _size(regime="bull_trend")["suggested_pct"]
        self.assertLess(off, neu)
        self.assertLess(neu, bull)
        self.assertEqual(sizing.regime_scale("unknown"), 0.8)        # default neutral

    def test_per_name_cap(self):
        # a very tight stop blows past the per-name cap → clamped, flagged
        r = _size(conviction=1.0, atr_stop_pct=0.02, max_pos=20.0)   # base 50% → cap 20
        self.assertEqual(r["suggested_pct"], 20.0)
        self.assertEqual(r["capped_by"], "max_position")

    def test_total_exposure_prorata(self):
        cands = [{"symbol": s, "conviction": 1.0, "atr_stop_pct": 0.08, "price": 100.0}
                 for s in ("a", "b", "c", "d", "e", "f", "g", "h")]   # 8 × 12.5% = 100% pre-cap
        out = sizing.size_book(cands, book_value=1_000_000.0, regime_state="bull_trend",
                               risk_budget_pct=1.0, max_position_pct=20.0,
                               max_total_exposure_pct=50.0, lot_size=1000)
        self.assertAlmostEqual(sum(r["suggested_pct"] for r in out), 50.0, places=2)  # scaled to cap
        self.assertTrue(all(r["capped_by"] == "total_exposure" for r in out))

    def test_lot_rounding(self):
        r = _size(conviction=0.8, atr_stop_pct=0.08, book_value=1_000_000.0, price=333.0)
        self.assertEqual(r["suggested_qty"] % 1000, 0)              # whole lots
        budget_value = r["suggested_pct"] / 100.0 * 1_000_000.0     # qty never exceeds the pct budget
        self.assertLessEqual(r["suggested_qty"] * 333.0, budget_value + 1e-6)

    def test_missing_atr_fallback(self):
        self.assertEqual(sizing.stop_pct(), 0.04)                   # nothing supplied → floor
        self.assertEqual(sizing.stop_pct(0.05), 0.05)              # explicit wins
        self.assertAlmostEqual(sizing.stop_pct(stop_loss=92.0, price=100.0), 0.08)  # derived from SL
        self.assertEqual(sizing.stop_pct(stop_loss=110.0, price=100.0), 0.04)       # non-positive → floor

    def test_per_sector_cap(self):
        cands = [{"symbol": "a", "sector": "半導體", "conviction": 1.0, "atr_stop_pct": 0.08, "price": 100.0},
                 {"symbol": "b", "sector": "半導體", "conviction": 1.0, "atr_stop_pct": 0.08, "price": 100.0},
                 {"symbol": "c", "sector": "航運", "conviction": 1.0, "atr_stop_pct": 0.08, "price": 100.0}]
        out = sizing.size_book(cands, book_value=1_000_000.0, regime_state="bull_trend",
                               risk_budget_pct=1.0, max_position_pct=20.0,
                               max_total_exposure_pct=100.0, max_per_sector_pct=15.0, lot_size=1000)
        semi = sum(r["suggested_pct"] for r in out if r["sector"] == "半導體")
        self.assertAlmostEqual(semi, 15.0, places=2)               # 半導體 capped to its sector limit
        self.assertEqual([r for r in out if r["symbol"] == "c"][0]["capped_by"], None)  # 航運 untouched


if __name__ == "__main__":
    unittest.main()
