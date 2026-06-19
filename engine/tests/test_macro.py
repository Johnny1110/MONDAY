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


if __name__ == "__main__":
    unittest.main()
