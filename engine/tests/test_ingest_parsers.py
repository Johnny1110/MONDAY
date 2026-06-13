"""Ingest parsers (§4.1) — pure stdlib, runs anywhere. Fixtures mirror the real API shapes
(TWSE STOCK_DAY_ALL/STOCK_DAY, FinMind TaiwanStockPrice) captured live on 2026-06-12."""

import unittest

from monday.ingest import finmind, twse
from monday.ingest.parse import num, roc_to_iso


class TestParseHelpers(unittest.TestCase):
    def test_roc_to_iso(self):
        self.assertEqual(roc_to_iso("1150612"), "2026-06-12")     # OpenAPI compact form
        self.assertEqual(roc_to_iso("115/06/01"), "2026-06-01")   # STOCK_DAY slashed form
        self.assertIsNone(roc_to_iso("--"))
        self.assertIsNone(roc_to_iso(""))

    def test_num(self):
        self.assertEqual(num("2,355.00"), 2355.0)
        self.assertEqual(num("+60.00"), 60.0)
        self.assertEqual(num(" 0.00"), 0.0)
        self.assertIsNone(num("--"))
        self.assertIsNone(num(""))
        self.assertEqual(num(26306885), 26306885.0)


class TestTWSE(unittest.TestCase):
    STOCK_DAY_ALL = [
        {"Date": "1150612", "Code": "2330", "Name": "台積電", "TradeVolume": "26306885",
         "TradeValue": "60666936905", "OpeningPrice": "2325.00", "HighestPrice": "2325.00",
         "LowestPrice": "2290.00", "ClosingPrice": "2310.00", "Change": "60.00",
         "Transaction": "77219"},
        {"Date": "1150612", "Code": "00400A", "Name": "主動國泰動能高息",  # ETF → skipped
         "TradeVolume": "31081438", "OpeningPrice": "14.63", "HighestPrice": "14.63",
         "LowestPrice": "14.18", "ClosingPrice": "14.24", "Change": "0.38", "Transaction": "5675"},
        {"Date": "1150612", "Code": "9999", "Name": "未成交", "TradeVolume": "0",
         "OpeningPrice": "--", "HighestPrice": "--", "LowestPrice": "--",
         "ClosingPrice": "--", "Change": "0.00", "Transaction": "0"},  # no trades → skipped
    ]

    def test_parse_stock_day_all(self):
        bars = twse.parse_stock_day_all(self.STOCK_DAY_ALL)
        self.assertEqual(len(bars), 1)                       # only the 4-digit, traded stock
        b = bars[0]
        self.assertEqual((b["symbol"], b["date"], b["close"]), ("2330", "2026-06-12", 2310.0))
        self.assertEqual((b["high"], b["low"], b["volume"]), (2325.0, 2290.0, 26306885))

    def test_parse_stock_day_month(self):
        payload = {"stat": "OK", "data": [
            ["115/06/01", "60,942,792", "144,105,259,583", "2,355.00", "2,415.00",
             "2,350.00", "2,355.00", " 0.00", "136,367", ""],
            ["115/06/12", "26,306,885", "60,666,936,905", "2,325.00", "2,325.00",
             "2,290.00", "2,310.00", "+60.00", "77,219", ""],
        ]}
        bars = twse.parse_stock_day(payload, "2330", "台積電")
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["date"], "2026-06-01")
        self.assertEqual(bars[1]["close"], 2310.0)
        self.assertEqual(bars[1]["volume"], 26306885)        # commas stripped

    def test_parse_stock_day_not_ok(self):
        self.assertEqual(twse.parse_stock_day({"stat": "很抱歉，沒有符合條件的資料!"}, "2330"), [])


class TestFinMind(unittest.TestCase):
    def test_parse_price(self):
        payload = {"status": 200, "msg": "success", "data": [
            {"date": "2026-06-11", "stock_id": "2330", "Trading_Volume": 20000000,
             "open": 2300.0, "max": 2330.0, "min": 2295.0, "close": 2325.0},
            {"date": "2026-06-12", "stock_id": "2330", "Trading_Volume": 26306885,
             "open": 2325.0, "max": 2325.0, "min": 2290.0, "close": 2310.0},
        ]}
        bars = finmind.parse_price(payload, name="台積電")
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[1]["high"], 2325.0)            # max → high
        self.assertEqual(bars[1]["low"], 2290.0)             # min → low
        self.assertEqual(bars[0]["name"], "台積電")

    def test_parse_price_bad_status(self):
        self.assertEqual(finmind.parse_price({"status": 402, "msg": "limit"}), [])


if __name__ == "__main__":
    unittest.main()
