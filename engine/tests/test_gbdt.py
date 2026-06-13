"""GBDT three-head model (§5.2). Needs lightgbm + numpy; skipped otherwise so the pure suite
still runs on a bare interpreter."""

import os
import tempfile
import unittest

try:
    import lightgbm  # noqa: F401
    import numpy  # noqa: F401
    HAVE = True
except Exception:
    HAVE = False


def _rows():
    # 8 dates × 20 symbols, with y_ret carrying a momentum signal the model can rank on
    rows = []
    for d in range(8):
        for s in range(20):
            m = (s - 10) / 10.0
            rows.append({"as_of": f"d{d:02d}", "symbol": f"s{s:02d}",
                         "mom_20d": m, "mom_60d": m * 0.5, "mom_120d": m * 0.3,
                         "dist_high_60d": -abs(m) * 0.1, "rsi_14": 50 + m * 20, "vol_20d": 0.02,
                         "y_ret": 0.05 * m + 0.001 * s, "y_touch": 1 if m > 0 else 0})
    return rows


@unittest.skipUnless(HAVE, "needs lightgbm + numpy")
class TestGBDT(unittest.TestCase):
    def test_train_and_predict_shape(self):
        from monday.models import gbdt
        bundle = gbdt.train_heads(_rows())
        self.assertEqual(set(bundle), {"features", "ranker", "regr", "clf"})
        cross = [r for r in _rows() if r["as_of"] == "d00"]
        preds = gbdt.predict(bundle, cross)
        self.assertEqual(len(preds), len(cross))
        self.assertEqual([p["rank"] for p in preds], list(range(1, len(preds) + 1)))  # 1..N
        for p in preds:
            for k in ("score", "predicted_return", "predicted_prob_tp"):
                self.assertIn(k, p)

    def test_save_load_roundtrip(self):
        from monday.models import gbdt
        bundle = gbdt.train_heads(_rows())
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.pkl")
            gbdt.save(bundle, path)
            self.assertEqual(gbdt.load(path)["features"], gbdt.GBDT_FEATURES)


if __name__ == "__main__":
    unittest.main()
