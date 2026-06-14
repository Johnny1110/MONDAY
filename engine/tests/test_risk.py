"""Portfolio risk gate (§5.7) — pure stdlib, runs anywhere."""

import unittest

from monday import risk
from monday.ingest import finmind


class TestRiskGate(unittest.TestCase):
    def test_clean_book_passes(self):
        picks = [{"symbol": "2330", "sector": "半導體業", "adv_20d": 1e9},
                 {"symbol": "2882", "sector": "金融保險", "adv_20d": 5e8}]
        r = risk.gate(picks, max_names=20, max_per_sector=5)
        self.assertTrue(r["passed"])
        self.assertEqual(r["violations"], [])

    def test_sector_concentration_flagged(self):
        picks = [{"symbol": f"s{i}", "sector": "半導體業"} for i in range(6)]
        r = risk.gate(picks, max_per_sector=5)
        self.assertFalse(r["passed"])
        self.assertEqual(r["violations"][0]["type"], "sector_concentration")
        self.assertEqual(r["by_sector"]["半導體業"], 6)

    def test_unknown_sector_not_flagged(self):
        picks = [{"symbol": f"s{i}", "sector": "unknown"} for i in range(10)]
        self.assertTrue(risk.gate(picks, max_per_sector=5)["passed"])  # can't assess → don't flag

    def test_liquidity_floor(self):
        picks = [{"symbol": "A", "sector": "x", "adv_20d": 100.0},
                 {"symbol": "B", "sector": "y", "adv_20d": 5000.0}]
        r = risk.gate(picks, adv_floor=1000.0)
        self.assertFalse(r["passed"])
        self.assertEqual(r["violations"][0]["type"], "liquidity")
        self.assertIn("A", r["violations"][0]["detail"])

    def test_too_many_names(self):
        picks = [{"symbol": f"s{i}", "sector": "unknown"} for i in range(21)]
        r = risk.gate(picks, max_names=20)
        self.assertTrue(any(v["type"] == "too_many_names" for v in r["violations"]))


class TestStockInfoParse(unittest.TestCase):
    def test_prefers_specific_sector(self):
        payload = {"status": 200, "data": [
            {"stock_id": "2330", "industry_category": "電子工業"},
            {"stock_id": "2330", "industry_category": "半導體業"},
            {"stock_id": "2882", "industry_category": "金融保險"},
        ]}
        m = finmind.parse_stock_info(payload)
        self.assertEqual(m["2330"], "半導體業")   # specific over the 電子工業 umbrella
        self.assertEqual(m["2882"], "金融保險")

    def test_bad_status(self):
        self.assertEqual(finmind.parse_stock_info({"status": 402}), {})


if __name__ == "__main__":
    unittest.main()
