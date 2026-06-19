"""Managed book (A3) — pure cost-basis/exposure math + the store-backed fill lifecycle.

The math tests are stdlib-only (run anywhere); the lifecycle/idempotency/exposure tests need a
throwaway Postgres and auto-skip without one (mirroring test_store).
"""

import unittest
from unittest import mock

from monday import book
from tests.pgtest import fresh_store, requires_pg


class TestBookMath(unittest.TestCase):
    def test_weighted_entry(self):
        self.assertEqual(book.weighted_entry(0, 0.0, 1000, 900.0), 900.0)       # into a flat lot
        self.assertEqual(book.weighted_entry(1000, 900.0, 1000, 1100.0), 1000.0)  # 50/50 reweight

    def test_apply_fill_open_then_add(self):
        opened = book.apply_fill({"qty": 0, "avg_entry": 0}, "buy", 1000, 900.0)
        self.assertEqual((opened["action"], opened["new_qty"], opened["new_avg"]), ("open", 1000, 900.0))
        self.assertEqual(opened["realized"], 0.0)
        added = book.apply_fill({"qty": 1000, "avg_entry": 900.0}, "buy", 1000, 1100.0)
        self.assertEqual((added["action"], added["new_qty"], added["new_avg"]), ("add", 2000, 1000.0))

    def test_apply_fill_trim_then_exit(self):
        trim = book.apply_fill({"qty": 2000, "avg_entry": 1000.0}, "sell", 500, 1200.0)
        self.assertEqual((trim["action"], trim["new_qty"], trim["new_avg"]), ("trim", 1500, 1000.0))
        self.assertEqual(trim["realized"], (1200.0 - 1000.0) * 500)             # avg held, P&L on sold
        ex = book.apply_fill({"qty": 1500, "avg_entry": 1000.0}, "sell", 1500, 1300.0)
        self.assertEqual((ex["action"], ex["new_qty"], ex["new_avg"]), ("exit", 0, 0.0))

    def test_apply_fill_sell_clamps(self):
        # selling more than held clamps to the held qty (never negative) and exits
        res = book.apply_fill({"qty": 1000, "avg_entry": 1000.0}, "sell", 2000, 1300.0)
        self.assertEqual((res["action"], res["new_qty"], res["filled_qty"]), ("exit", 0, 1000))
        self.assertEqual(res["realized"], (1300.0 - 1000.0) * 1000)

    def test_apply_fill_bad_side(self):
        with self.assertRaises(ValueError):
            book.apply_fill({"qty": 0, "avg_entry": 0}, "hold", 1, 1.0)

    def test_exposure(self):
        positions = [{"symbol": "2330", "qty": 2000, "avg_entry": 900.0, "direction": "long"},
                     {"symbol": "2454", "qty": 1000, "avg_entry": 1200.0, "direction": "long"}]
        prices = {"2330": 1000.0, "2454": 1100.0}
        sectors = {"2330": "半導體", "2454": "半導體"}
        ex = book.exposure(positions, prices, cash=100_000.0, sector_lookup=sectors)
        self.assertEqual(ex["gross"], 3_100_000.0)        # 2000*1000 + 1000*1100
        self.assertEqual(ex["net"], 3_100_000.0)          # long-only
        self.assertEqual(ex["total"], 3_200_000.0)        # + cash
        self.assertEqual(ex["by_sector"]["半導體"], 3_100_000.0)
        self.assertEqual(ex["weights"]["2330"], 62.5)     # 2.0M / 3.2M
        self.assertEqual(ex["n"], 2)

    def test_exposure_missing_price_falls_back_to_cost(self):
        ex = book.exposure([{"symbol": "2330", "qty": 1000, "avg_entry": 100.0}], {}, cash=0.0)
        self.assertEqual(ex["gross"], 100_000.0)          # no live price → avg_entry


@requires_pg
class TestBookStore(unittest.TestCase):
    def setUp(self):
        fresh_store()

    def tearDown(self):
        from monday import store
        store.close()

    def test_record_fill_lifecycle(self):
        from monday import store
        from monday.config import settings
        book.record_fill("paper", "2330", "buy", 2000, 900.0, "2026-06-01", name="台積電")
        p = store.get_book_position("paper:2330")
        self.assertEqual((p["qty"], p["avg_entry"], p["status"]), (2000, 900.0, "open"))
        self.assertEqual((p["opened_at"], p["source"], p["name"]), ("2026-06-01", "morgan", "台積電"))

        book.record_fill("paper", "2330", "buy", 1000, 1200.0, "2026-06-05")        # add → reweight
        self.assertEqual(store.get_book_position("paper:2330")["avg_entry"], 1000.0)

        trim = book.record_fill("paper", "2330", "sell", 1000, 1100.0, "2026-06-10")  # trim
        self.assertEqual(store.get_book_position("paper:2330")["qty"], 2000)
        self.assertEqual(trim["realized"], 100_000.0)                                # (1100-1000)*1000

        ex = book.record_fill("paper", "2330", "sell", 2000, 1300.0, "2026-06-18")    # exit
        closed = store.get_book_position("paper:2330")
        self.assertEqual((closed["qty"], closed["status"]), (0, "closed"))
        self.assertEqual(ex["realized"], 600_000.0)                                  # (1300-1000)*2000

        acts = store.list_position_actions(position_id="paper:2330")
        self.assertEqual([a["action"] for a in acts], ["exit", "trim", "add", "open"])  # newest-first
        self.assertEqual(acts[-1]["delta_qty"], 2000)                                # open +2000
        self.assertEqual(acts[0]["delta_qty"], -2000)                               # exit -2000

        # cash ledger: starting cash + net realized (100k trim + 600k exit)
        self.assertEqual(book.book_cash("paper"), settings.book_starting_cash + 700_000.0)
        self.assertEqual(book.list_book("paper", "open"), [])                        # nothing open
        self.assertEqual(len(book.list_book("paper", None)), 1)                      # the closed lot

    def test_fill_idempotent(self):
        from monday import store
        first = book.record_fill("paper", "2330", "buy", 1000, 900.0, "2026-06-01", fill_key="k1")
        self.assertFalse(first["idempotent"])
        again = book.record_fill("paper", "2330", "buy", 1000, 900.0, "2026-06-01", fill_key="k1")
        self.assertTrue(again["idempotent"])                                        # no-op on re-confirm
        self.assertEqual(store.get_book_position("paper:2330")["qty"], 1000)        # not 2000
        self.assertEqual(len(store.list_position_actions(position_id="paper:2330")), 1)

    def test_sell_without_holding_rejected(self):
        with self.assertRaises(ValueError):
            book.record_fill("paper", "2330", "sell", 1000, 900.0, "2026-06-01")

    def test_paper_real_books_isolated(self):
        from monday import store
        book.record_fill("paper", "2330", "buy", 1000, 900.0, "2026-06-01")
        book.record_fill("real", "2330", "buy", 500, 905.0, "2026-06-01")
        self.assertEqual(store.get_book_position("paper:2330")["qty"], 1000)
        self.assertEqual(store.get_book_position("real:2330")["qty"], 500)
        self.assertEqual(len(book.list_book("paper")), 1)
        self.assertEqual(len(book.list_book("real")), 1)

    def test_book_exposure_with_store(self):
        from monday.config import settings
        book.record_fill("paper", "2330", "buy", 1000, 100.0, "2026-06-01")          # cash 1M-100k
        with mock.patch.object(book, "_sector_lookup", return_value={"2330": "半導體"}):
            ex = book.book_exposure("paper")
        self.assertEqual(ex["gross"], 100_000.0)              # no snapshot → price falls back to avg
        self.assertEqual(ex["cash"], settings.book_starting_cash - 100_000.0)
        self.assertEqual(ex["total"], settings.book_starting_cash)
        self.assertEqual(ex["by_sector"]["半導體"], 100_000.0)
        self.assertEqual(ex["weights"]["2330"], round(100_000.0 / settings.book_starting_cash * 100, 2))

    def test_set_targets(self):
        from monday import store
        book.record_fill("paper", "2330", "buy", 1000, 900.0, "2026-06-01")
        book.set_targets("paper:2330", take_profit=1000.0, stop_loss=850.0)
        p = store.get_book_position("paper:2330")
        self.assertEqual((p["take_profit"], p["stop_loss"]), (1000.0, 850.0))
        self.assertIsNone(book.set_targets("paper:9999", take_profit=1.0))           # absent lot


if __name__ == "__main__":
    unittest.main()
