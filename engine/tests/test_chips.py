"""Chip factors + ingest parsers (§4.3) — pure stdlib, runs anywhere."""

import unittest

from monday.featurestore import chips
from monday.ingest import finmind


class TestChipFactors(unittest.TestCase):
    def test_net_streak(self):
        self.assertEqual(chips.net_streak([1, 2, 3]), 3)         # 3 buy days
        self.assertEqual(chips.net_streak([5, -1, -2]), -2)      # 2 sell days
        self.assertEqual(chips.net_streak([1, -1, 4]), 1)        # only the last day
        self.assertEqual(chips.net_streak([]), 0)
        self.assertEqual(chips.net_streak([0]), 0)

    def test_net_sum(self):
        self.assertEqual(chips.net_sum([1, 2, 3, 4], 2), 7)
        self.assertIsNone(chips.net_sum([], 5))

    def test_balance_change(self):
        self.assertAlmostEqual(chips.balance_change([100, 110, 120], 2), 0.20)
        self.assertIsNone(chips.balance_change([100], 2))

    def test_chip_factors_pit(self):
        inst = [{"date": "2026-06-10", "foreign_net": 100, "invtrust_net": 5, "dealer_net": 0},
                {"date": "2026-06-11", "foreign_net": 200, "invtrust_net": -3, "dealer_net": 0},
                {"date": "2026-06-12", "foreign_net": 300, "invtrust_net": 8, "dealer_net": 0}]  # future
        f = chips.chip_factors(inst, [], as_of="2026-06-11")           # excludes 06-12
        self.assertEqual(f["foreign_net_5d"], 300)                     # 100+200 only
        self.assertEqual(f["foreign_streak"], 2)

    def test_enrich_rows(self):
        rows = [{"symbol": "2330", "as_of": "2026-06-11"}, {"symbol": "X", "as_of": "2026-06-11"}]
        chips_by = {"2330": {"inst": [
            {"date": "2026-06-10", "foreign_net": 100, "invtrust_net": 0, "dealer_net": 0},
            {"date": "2026-06-11", "foreign_net": 200, "invtrust_net": 0, "dealer_net": 0}],
            "margin": []}}
        chips.enrich_rows(rows, chips_by)
        self.assertEqual(rows[0]["foreign_streak"], 2)        # 2330 enriched
        self.assertIsNone(rows[1]["foreign_streak"])          # unknown symbol → None (NaN to GBDT)


class TestChipParsers(unittest.TestCase):
    def test_parse_institutional_nets(self):
        payload = {"status": 200, "data": [
            {"date": "2026-06-09", "name": "Foreign_Investor", "buy": 15_000_000, "sell": 30_000_000},
            {"date": "2026-06-09", "name": "Investment_Trust", "buy": 2_700_000, "sell": 40_000},
            {"date": "2026-06-09", "name": "Dealer_self", "buy": 160_000, "sell": 1_191_000},
        ]}
        rows = finmind.parse_institutional(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["foreign_net"], -15_000_000)
        self.assertEqual(rows[0]["invtrust_net"], 2_660_000)

    def test_parse_margin(self):
        payload = {"status": 200, "data": [
            {"date": "2026-06-12", "MarginPurchaseTodayBalance": 27421, "ShortSaleTodayBalance": 13}]}
        rows = finmind.parse_margin(payload)
        self.assertEqual(rows[0]["margin_balance"], 27421.0)
        self.assertEqual(rows[0]["short_balance"], 13.0)


if __name__ == "__main__":
    unittest.main()
