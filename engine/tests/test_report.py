"""Daily report v2 (A7) — pure validate/render/telegram + the store-backed scaffold & POST round-trip."""

import json
import tempfile
import unittest
from unittest import mock

from monday import report, telegram
from tests.pgtest import fresh_store, requires_pg

try:
    import pyarrow  # noqa: F401
    HAVE_PYARROW = True
except Exception:
    HAVE_PYARROW = False


def _valid_report():
    return {
        "as_of": "2026-06-19", "regime": "bull_trend", "risk_state": "risk_on",
        "sections": {
            "macro": {"risk_state": "risk_on", "overnight": [{"symbol": "^SOX", "name": "費半",
                      "chg_pct": 1.8}], "read": "費半創高，外資偏多。"},
            "market_narrative": {"regime": "bull_trend", "hot_sectors": ["半導體"],
                                 "new_narratives": ["矽光子"], "stance": "進攻", "read": "盤勢偏多。"},
            "holdings_review": [{"symbol": "2330", "name": "台積電", "qty": 2000, "avg_entry": 1080,
                                 "price": 1120, "mtm_pct": 3.7, "action": "hold", "reason": "趨勢完整",
                                 "updated_tp": 1180, "updated_sl": 1060}],
            "new_ideas": [{"symbol": "3661", "name": "世芯", "direction": "long", "entry_ref": 3200,
                           "take_profit": 3520, "stop_loss": 3000, "suggested_pct": 6.0,
                           "suggested_qty": 1000, "conviction": 0.71, "rationale": "ASIC 動能"}],
            "exposure": {"gross_pct": 72, "net_pct": 72, "cash_pct": 28, "by_sector": {"半導體": 40},
                         "target_exposure_pct": 75},
            "risk_notes": {"events": ["台積電法說 6/20"], "landmines": [], "invalidation": "費半跌破均線"},
        },
        "disclaimer": report.DISCLAIMER,
    }


class TestReportPure(unittest.TestCase):
    def test_validate_report_valid(self):
        self.assertEqual(report.validate_report(_valid_report()), [])

    def test_validate_report_missing(self):
        r = _valid_report()
        del r["sections"]["exposure"]
        del r["disclaimer"]
        errs = report.validate_report(r)
        self.assertIn("missing section: exposure", errs)
        self.assertIn("missing disclaimer", errs)

    def test_validate_report_bad_types(self):
        r = _valid_report()
        r["sections"]["new_ideas"] = {"not": "a list"}
        self.assertIn("new_ideas must be a list", report.validate_report(r))

    def test_render_text_has_all_sections_and_disclaimer(self):
        txt = report.render_text(_valid_report())
        for header in ("宏觀定調", "台股盤勢與新敘事", "持倉檢視", "今日新標的", "倉位與曝險", "風險提醒"):
            self.assertIn(header, txt)
        self.assertIn(report.DISCLAIMER, txt)
        self.assertIn("3661", txt)                       # new idea rendered
        self.assertIn("2330", txt)                       # holding rendered

    def test_render_text_no_new_ideas_note(self):
        r = _valid_report()
        r["sections"]["new_ideas"] = []
        self.assertIn("今日不發新標的", report.render_text(r))

    def test_telegram_format_daily(self):
        msg = telegram.format_daily_report(_valid_report())
        self.assertIn(report.DISCLAIMER, msg)            # disclaimer always present (invariant 11)
        self.assertIn("3661", msg)
        self.assertFalse(telegram.enabled("", ""))       # unconfigured → no-op send


@requires_pg
@unittest.skipUnless(HAVE_PYARROW, "needs pyarrow for macro/price snapshots")
class TestReportScaffold(unittest.TestCase):
    def setUp(self):
        from monday.config import settings
        self.tmp = tempfile.mkdtemp()
        settings.data_dir = self.tmp
        fresh_store()

    def tearDown(self):
        from monday import store
        store.close()

    def test_build_scaffold(self):
        from monday import book, macro, snapshot, store
        store.kv_set("last_as_of", "2026-06-19")
        macro.write_macro_snapshot(self.tmp, "2026-06-19",
                                   [{"symbol": "^SOX", "name": "費半", "chg_pct": 1.8,
                                     "asset_class": "equity_index"}])
        snapshot.write_snapshot(self.tmp, "2026-06-19",
                                [{"symbol": "2330", "date": "2026-06-19", "close": 1120.0,
                                  "high": 1125.0, "low": 1100.0}])
        book.record_fill("paper", "2330", "buy", 2000, 1080.0, "2026-06-10", name="台積電")
        store.kv_set("signals_today", json.dumps({
            "as_of_date": "2026-06-19", "regime": "bull_trend", "focus_sectors": ["半導體"],
            "candidates": [{"symbol": "3661", "name": "世芯", "rank": 1, "score": 0.8, "close": 3200.0,
                            "predicted_return": 0.06, "predicted_prob_tp": 0.7, "conviction": 0.71,
                            "factors": {"atr_14": 80.0}}]}))
        with mock.patch.object(book, "_sector_lookup", return_value={"2330": "半導體"}):
            sc = report.build_scaffold("2026-06-19")
        self.assertEqual(report.validate_report(sc), [])              # scaffold is contract-valid
        self.assertEqual(sc["sections"]["macro"]["overnight"][0]["symbol"], "^SOX")
        h = sc["sections"]["holdings_review"][0]
        self.assertEqual(h["symbol"], "2330")
        self.assertAlmostEqual(h["mtm_pct"], round((1120 / 1080 - 1) * 100, 2))   # MTM computed
        n = sc["sections"]["new_ideas"][0]
        self.assertEqual(n["symbol"], "3661")
        self.assertIsNotNone(n["take_profit"])                       # exits computed
        self.assertIn("suggested_pct", n)                            # sizing computed
        self.assertIn("net_pct", sc["sections"]["exposure"])

    def test_post_daily_persists_and_renders(self):
        from monday import store
        from monday.routers import reports as rep_router
        saved = rep_router.post_daily(_valid_report())
        self.assertTrue(saved["summary_text"])                       # rendered
        got = rep_router.get_daily("2026-06-19")
        self.assertEqual(got["data"]["sections"]["new_ideas"][0]["symbol"], "3661")
        self.assertIn("disclaimer", got["data"])                     # disclaimer persisted (invariant 11)
        # malformed report → 422
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            rep_router.post_daily({"as_of": "2026-06-19"})           # no sections/disclaimer


if __name__ == "__main__":
    unittest.main()
