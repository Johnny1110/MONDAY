"""Full-chain smoke (the P0 exit gate). Needs venv deps (pyarrow, pydantic-settings); skipped
if absent so the pure-logic suite still runs on a bare interpreter."""

import os
import tempfile
import unittest

try:
    import pyarrow  # noqa: F401
    import pydantic_settings  # noqa: F401
    HAVE_DEPS = True
except Exception:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "needs venv deps (pyarrow, pydantic-settings)")
class TestPipelineSmoke(unittest.TestCase):
    def test_full_chain_end_to_end(self):
        from monday import pipeline, store
        from monday.config import settings
        with tempfile.TemporaryDirectory() as tmp:
            settings.sqlite_path = ":memory:"
            settings.data_dir = os.path.join(tmp, "data")
            store.connect(settings.sqlite_path)
            try:
                s = pipeline.run(days=160, mark_forward=1)
                written = s["stages"]["recommendations"]["written"]
                self.assertGreater(written, 0)
                self.assertGreater(s["stages"]["snapshot"]["rows_on_disk"], 0)
                self.assertGreater(s["stages"]["features"]["rows"], 0)
                self.assertGreater(s["stages"]["mark_to_market"]["day0"]["marked"], 0)
                # every written idea is either still open or settled — nothing lost
                self.assertEqual(s["portfolio"]["open"] + s["portfolio"]["closed"], written)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
