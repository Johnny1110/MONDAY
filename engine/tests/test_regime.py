"""Regime classifier (§5.3) — pure stdlib, runs anywhere."""

import unittest
from datetime import date, timedelta

from monday import regime


def _panel(symbols, days, fn):
    """Build a bar panel with clean sequential dates: close = fn(symbol_index, day_index)."""
    base = date(2026, 1, 1)
    bars = []
    for s in range(symbols):
        for d in range(days):
            c = fn(s, d)
            bars.append({"symbol": f"s{s:02d}", "date": (base + timedelta(days=d)).isoformat(),
                         "close": c, "high": c * 1.01, "low": c * 0.99, "volume": 1000})
    return bars


class TestClassify(unittest.TestCase):
    def test_high_vol_overrides(self):
        self.assertEqual(regime.classify(0.10, 0.9, 0.05), "high_vol")

    def test_bull(self):
        self.assertEqual(regime.classify(0.08, 0.75, 0.01), "bull_trend")

    def test_risk_off(self):
        self.assertEqual(regime.classify(-0.08, 0.25, 0.01), "risk_off")

    def test_choppy(self):
        self.assertEqual(regime.classify(0.00, 0.5, 0.01), "choppy")

    def test_neutral_on_missing(self):
        self.assertEqual(regime.classify(None, None, None), "neutral")


class TestRegimeFor(unittest.TestCase):
    def setUp(self):
        self.days = 90
        self.as_of = (date(2026, 1, 1) + timedelta(days=self.days - 1)).isoformat()

    def test_uptrend_is_bull(self):
        bars = _panel(20, self.days, lambda s, d: 100 * (1.004 ** d))  # steady broad uptrend, low vol
        self.assertEqual(regime.regime_for(bars, self.as_of), "bull_trend")

    def test_downtrend_is_risk_off(self):
        bars = _panel(20, self.days, lambda s, d: 100 * (0.996 ** d))
        self.assertEqual(regime.regime_for(bars, self.as_of), "risk_off")


if __name__ == "__main__":
    unittest.main()
