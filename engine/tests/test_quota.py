"""FinMind quota counters in the ingest layer (B3b) — mock urlopen, no network."""

import io
import json
import tempfile
import unittest
import urllib.error
from unittest import mock

from monday.ingest import base


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class TestQuota(unittest.TestCase):
    def setUp(self):
        base._quota.clear()

    def test_network_call_counts_cache_hit_does_not(self):
        payload = {"data": [{"x": 1}]}

        def fake_urlopen(req, timeout=None):
            return _Resp(json.dumps(payload).encode())

        with tempfile.TemporaryDirectory() as cd:
            with mock.patch("urllib.request.urlopen", fake_urlopen):
                base.fetch_json("http://x/api", {"a": 1}, cache_dir=cd, rate_key="finmind",
                                min_interval=0)
            self.assertEqual(base.quota_snapshot()["finmind"]["calls"], 1)
            # second identical call is served from cache → no extra network count
            with mock.patch("urllib.request.urlopen", fake_urlopen):
                base.fetch_json("http://x/api", {"a": 1}, cache_dir=cd, rate_key="finmind",
                                min_interval=0)
            self.assertEqual(base.quota_snapshot()["finmind"]["calls"], 1)

    def test_rate_limit_counted_and_raises(self):
        def boom(req, timeout=None):
            raise urllib.error.HTTPError("http://x", 402, "Payment Required", {}, None)

        with mock.patch("urllib.request.urlopen", boom):
            with self.assertRaises(base.RateLimitError):
                base.fetch_json("http://x/api", rate_key="finmind", min_interval=0, retries=2)
        snap = base.quota_snapshot()["finmind"]
        self.assertGreaterEqual(snap["calls"], 1)
        self.assertEqual(snap["rate_limited"], 1)
        self.assertIsNotNone(snap["last_rate_limited_at"])

    def test_reset_drains(self):
        base._quota_bump("finmind")
        self.assertEqual(base.reset_quota_counters()["finmind"]["calls"], 1)
        self.assertEqual(base.quota_snapshot(), {})


if __name__ == "__main__":
    unittest.main()
