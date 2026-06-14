"""Universe ranking (§4.1) — pure stdlib, runs anywhere."""

import unittest

from monday.ingest import universe


class TestRankUniverse(unittest.TestCase):
    def test_ranks_by_dollar_volume(self):
        bars = [
            {"symbol": "A", "name": "aa", "close": 10, "volume": 100},   # 1,000
            {"symbol": "B", "name": "bb", "close": 50, "volume": 100},   # 5,000
            {"symbol": "C", "name": "cc", "close": 1, "volume": 100},    # 100
        ]
        self.assertEqual([s for s, _ in universe.rank_universe(bars, 2)], ["B", "A"])

    def test_top_n_clamps_and_name_fallback(self):
        out = universe.rank_universe([{"symbol": "X", "close": 5, "volume": 5}], 10)
        self.assertEqual(out, [("X", "X")])   # name falls back to symbol; top_n > len is fine

    def test_empty(self):
        self.assertEqual(universe.rank_universe([], 5), [])


if __name__ == "__main__":
    unittest.main()
