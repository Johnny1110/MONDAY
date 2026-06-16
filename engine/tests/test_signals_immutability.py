"""Immutable per-date signals archive + the finalized no-clobber guard + signals_version on recs
(B9/B13). Runs the real chain on the recorded fixture — needs venv deps (pyarrow)."""

import json
import os
import tempfile
import time
import unittest

try:
    import pyarrow  # noqa: F401
    import pydantic_settings  # noqa: F401
    HAVE_DEPS = True
except Exception:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "needs venv deps (pyarrow, pydantic-settings)")
class TestSignalsImmutability(unittest.TestCase):
    def _run(self, **kw):
        from monday import pipeline
        from tests.realdata import patched
        with patched():
            return pipeline.run(days=160, mark_forward=1, **kw)

    def test_archive_version_and_no_clobber(self):
        from monday import pipeline, store
        from monday.config import settings
        with tempfile.TemporaryDirectory() as tmp:
            settings.sqlite_path = ":memory:"
            settings.data_dir = os.path.join(tmp, "data")
            store.connect(settings.sqlite_path)
            try:
                s = self._run(finalize=False)
                as_of = s["as_of"]
                v1 = s["stages"]["signals"]["signals_version"]
                self.assertFalse(s["stages"]["signals"]["preserved"])
                # immutable per-date archive carries the same version as the latest
                self.assertEqual(json.loads(store.kv_get(f"signals:{as_of}"))["signals_version"], v1)

                # morgan finalizes a subset → signals_version stamped on the recs + the day is locked
                env = json.loads(store.kv_get("signals_today"))
                chosen = [{**c, **(c.get("factors") or {})} for c in env["candidates"][:3]]
                recs, _ = pipeline.compose_recommendations(chosen, as_of, env["model_version"],
                                                           "neutral", signals_version=v1)
                store.kv_set(f"finalized:{as_of}", v1)
                self.assertEqual(store.get_recommendation(recs[0]["rec_id"])["signals_version"], v1)

                # B13: a later/background prepare run must NOT clobber the finalized signals
                time.sleep(1.1)                                    # ensure a distinct version if it DID overwrite
                s2 = self._run(finalize=False)
                self.assertTrue(s2["stages"]["signals"]["preserved"])
                self.assertEqual(json.loads(store.kv_get("signals_today"))["signals_version"], v1)

                # …unless force=True
                s3 = self._run(finalize=False, force=True)
                self.assertFalse(s3["stages"]["signals"]["preserved"])
                self.assertNotEqual(json.loads(store.kv_get("signals_today"))["signals_version"], v1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
