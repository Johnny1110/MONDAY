"""Macro plane (A2) — pure shaping + Yahoo parser degrade + PIT snapshot roundtrip.

The parser/shaping tests are stdlib-only (run anywhere) against a recorded fixture (no live network,
mirroring tw_sample.json); the snapshot roundtrip needs pyarrow and auto-skips when absent.
"""

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from monday import macro
from monday.config import settings
from monday.ingest import base
from monday.ingest import macro as macro_ingest

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "macro_sample.json"

try:
    import pyarrow  # noqa: F401
    HAVE_PYARROW = True
except Exception:
    HAVE_PYARROW = False


def _raw_from_fixture() -> dict:
    """{symbol: chart_payload} → {symbol: [{date, close}, …]} via the real parser."""
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return {sym: macro_ingest.parse_chart(pl) for sym, pl in fixture.items()}


# A recorded TWSE MI_5MINS_HIST shape (ROC dates, thousands-separated closes, one malformed row).
_TAIEX_PAYLOAD = {
    "stat": "OK",
    "fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"],
    "data": [
        ["115/06/17", "45,800.00", "46,000.00", "45,700.00", "45,900.50"],
        ["115/06/18", "45,972.26", "46,565.70", "45,972.26", "46,465.20"],
        ["bad-row"],                                                       # malformed → skipped
        ["115/06/16", "45,500.00", "45,850.00", "45,480.00", "45,750.00"],
    ],
}


class TestMacroParse(unittest.TestCase):
    def test_parse_chart_offset_and_nulls(self):
        fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        # ^GSPC bars are stamped 13:30 UTC with a -4h offset → still land on the right local date
        gspc = macro_ingest.parse_chart(fixture["^GSPC"])
        self.assertEqual([r["date"] for r in gspc],
                         ["2026-06-17", "2026-06-18", "2026-06-19"])     # ascending, latest-last
        self.assertEqual(gspc[-1]["close"], 5100.0)
        # ^VIX carries a trailing null close (incomplete bar) → skipped, not 4 rows
        self.assertEqual(len(macro_ingest.parse_chart(fixture["^VIX"])), 3)

    def test_parse_chart_malformed(self):
        for bad in (None, {}, {"chart": {"result": []}}, {"chart": {"result": [{"meta": {}}]}}):
            self.assertEqual(macro_ingest.parse_chart(bad), [])


class TestMacroShaping(unittest.TestCase):
    def setUp(self):
        self.rows = macro.build_macro_rows("2026-06-19", _raw_from_fixture(), settings.macro_symbols)
        self.by = {r["symbol"]: r for r in self.rows}

    def test_build_macro_rows(self):
        self.assertEqual(len(self.rows), 3)
        g = self.by["^GSPC"]
        self.assertEqual((g["close"], g["prev_close"]), (5100.0, 5050.0))
        self.assertAlmostEqual(g["chg_pct"], 0.99, places=2)             # (5100/5050-1)*100
        self.assertEqual(g["asset_class"], "equity_index")
        self.assertEqual(g["name"], settings.macro_symbols["^GSPC"]["name"])  # display name from config
        self.assertEqual(g["as_of"], "2026-06-19")
        self.assertEqual(self.by["^VIX"]["chg_pct"], -12.5)             # (14/16-1)*100
        self.assertEqual(self.by["^VIX"]["asset_class"], "vol")
        self.assertEqual(self.by["USDTWD=X"]["asset_class"], "fx")

    def test_build_macro_rows_pit_uses_bars_on_or_before(self):
        # asking as_of an earlier day uses that day's close as the latest (no look-ahead to 2026-06-19)
        rows = macro.build_macro_rows("2026-06-18", _raw_from_fixture(), settings.macro_symbols)
        g = {r["symbol"]: r for r in rows}["^GSPC"]
        self.assertEqual((g["close"], g["prev_close"]), (5050.0, 5000.0))

    def test_overnight_changes(self):
        ov = macro.overnight_changes(self.rows)
        self.assertEqual(ov["leaders"][0]["symbol"], "^GSPC")           # +0.99% is the top mover
        self.assertEqual(ov["laggards"][0]["symbol"], "^VIX")          # -12.5% is the worst
        self.assertIn("^VIX", ov["risk_proxies"])                      # a configured risk proxy
        self.assertIn("USDTWD=X", ov["risk_proxies"])
        self.assertNotIn("^GSPC", ov["risk_proxies"])                  # not a risk proxy
        self.assertEqual(ov["risk_proxies"]["^VIX"], -12.5)


class TestFetchIndicesDegrades(unittest.TestCase):
    def test_one_dead_ticker_omitted_rest_survive(self):
        fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))

        def fake_fetch(url, params=None, **kw):
            if "%5EGSPC" in url:                  # quote("^GSPC")
                return fixture["^GSPC"]
            if "%5ERL" in url:                    # a rate-limited ticker
                raise base.RateLimitError("HTTP 429")
            return {"chart": {"result": []}}      # "^BAD": malformed → no usable bars

        with mock.patch.object(base, "fetch_json", side_effect=fake_fetch):
            out = macro_ingest.fetch_indices(["^GSPC", "^BAD", "^RL"], cache_dir=None)
        self.assertEqual(list(out), ["^GSPC"])    # only the healthy ticker survives
        self.assertEqual(out["^GSPC"][-1]["close"], 5100.0)


@unittest.skipUnless(HAVE_PYARROW, "needs pyarrow for the parquet snapshot")
class TestMacroSnapshot(unittest.TestCase):
    def test_snapshot_roundtrip_pit_and_idempotent(self):
        raw = _raw_from_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            r19 = macro.build_macro_rows("2026-06-19", raw, settings.macro_symbols)
            r18 = macro.build_macro_rows("2026-06-18", raw, settings.macro_symbols)
            macro.write_macro_snapshot(tmp, "2026-06-18", r18)
            n = macro.write_macro_snapshot(tmp, "2026-06-19", r19)
            self.assertEqual(n, len(r18) + len(r19))                   # both days coexist (append-only)

            latest = macro.read_macro_snapshot(tmp)                    # default = latest day
            self.assertEqual({r["as_of"] for r in latest}, {"2026-06-19"})
            self.assertEqual(len(latest), 3)
            self.assertEqual({r["as_of"] for r in macro.read_macro_snapshot(tmp, "2026-06-18")},
                             {"2026-06-18"})                           # a prior PIT day is untouched
            self.assertEqual(macro.read_macro_snapshot(tmp, "2099-01-01"), [])  # absent day

            # re-writing the same as_of overwrites it (idempotent), doesn't duplicate
            n2 = macro.write_macro_snapshot(tmp, "2026-06-19", r19)
            self.assertEqual(n2, len(r18) + len(r19))


class TestTaiexFallbackParse(unittest.TestCase):
    def test_roc_to_iso(self):
        self.assertEqual(macro_ingest._roc_to_iso("115/06/18"), "2026-06-18")   # ROC year + 1911
        self.assertEqual(macro_ingest._roc_to_iso("113/06/03"), "2024-06-03")
        self.assertIsNone(macro_ingest._roc_to_iso("garbage"))
        self.assertIsNone(macro_ingest._roc_to_iso(None))

    def test_parse_taiex_hist(self):
        rows = macro_ingest.parse_taiex_hist(_TAIEX_PAYLOAD)
        self.assertEqual([r["date"] for r in rows],
                         ["2026-06-16", "2026-06-17", "2026-06-18"])    # ascending, malformed row dropped
        self.assertEqual(rows[-1]["close"], 46465.2)                    # 收盤指數, commas stripped
        self.assertEqual(rows[0]["close"], 45750.0)

    def test_parse_taiex_hist_malformed(self):
        for bad in (None, {}, {"data": None}, {"data": []}):
            self.assertEqual(macro_ingest.parse_taiex_hist(bad), [])

    def test_months_for(self):
        self.assertEqual(macro_ingest._months_for("2026-06-18"), ["20260601", "20260501"])
        self.assertEqual(macro_ingest._months_for("2026-01-05"), ["20260101", "20251201"])  # year boundary


@unittest.skipUnless(HAVE_PYARROW, "needs pyarrow for the parquet snapshot")
class TestMacroFallbackRefresh(unittest.TestCase):
    def test_twse_fills_benchmark_when_yahoo_blank(self):
        bench = settings.macro_benchmark_symbol
        taiex = [{"date": "2026-06-17", "close": 45900.5}, {"date": "2026-06-18", "close": 46465.2}]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(settings, "macro_fallback_source", "twse"), \
                mock.patch.object(macro_ingest, "fetch_indices", return_value={}), \
                mock.patch.object(macro_ingest, "fetch_taiex", return_value=taiex) as ft:
            out = macro.refresh(tmp, tmp)
            ft.assert_called_once()                                     # Yahoo blank → fallback invoked
            self.assertEqual(out["as_of"], "2026-06-18")               # snapshot anchors on the TAIEX date
            self.assertGreaterEqual(out["n"], 1)
            snap = macro.read_macro_snapshot(tmp)
            self.assertIn(bench, {r["symbol"] for r in snap})          # benchmark present despite Yahoo down

    def test_no_fallback_when_yahoo_serves_benchmark(self):
        bench = settings.macro_benchmark_symbol
        ydata = {bench: [{"date": "2026-06-17", "close": 1.0}, {"date": "2026-06-18", "close": 2.0}]}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(settings, "macro_fallback_source", "twse"), \
                mock.patch.object(macro_ingest, "fetch_indices", return_value=ydata), \
                mock.patch.object(macro_ingest, "fetch_taiex") as ft:
            macro.refresh(tmp, tmp)
            ft.assert_not_called()                                     # Yahoo served it → don't double-fetch

    def test_fallback_disabled_leaves_round_blank(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(settings, "macro_fallback_source", ""), \
                mock.patch.object(macro_ingest, "fetch_indices", return_value={}), \
                mock.patch.object(macro_ingest, "fetch_taiex") as ft:
            out = macro.refresh(tmp, tmp)
            ft.assert_not_called()                                     # disabled → no fallback
            self.assertEqual(out["n"], 0)


if __name__ == "__main__":
    unittest.main()
