"""Offline real-data fixture for the full-chain test + smoke.

``tests/fixtures/tw_sample.json`` holds **recorded real FinMind bars** (15 liquid TW names, ~1y),
committed so the chain runs deterministically with **no network and no synthetic/fake data**.
``patched()`` feeds these bars into the pipeline and no-ops chip enrichment (which fires a network
call and is covered separately by test_chips.py).
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from contextlib import contextmanager
from unittest import mock

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "tw_sample.json"


def load_bars() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@contextmanager
def patched():
    """Feed the recorded real-data fixture into pipeline.run/reconcile (offline, deterministic)."""
    from monday import pipeline
    bars = load_bars()
    with mock.patch.object(pipeline, "get_source", lambda name=None: (lambda *a, **k: list(bars))), \
         mock.patch.object(pipeline, "_enrich_chips", lambda *a, **k: None):
        yield


def run_smoke() -> dict:
    """Run one full chain on the fixture in a throwaway store; assert it produced a book + marks.
    The offline exit gate invoked by scripts/smoke.sh."""
    from monday import pipeline, store
    from monday.config import settings
    with tempfile.TemporaryDirectory() as tmp:
        settings.sqlite_path = ":memory:"
        settings.data_dir = os.path.join(tmp, "data")
        store.connect(settings.sqlite_path)
        try:
            with patched():
                s = pipeline.run(days=160, mark_forward=1)
            w = s["stages"]["recommendations"]["written"]
            m = s["stages"]["mark_to_market"]["day0"]["marked"]
            assert w > 0 and m > 0, s
            print("OK  as_of=%s  universe=%s  recommendations=%s  ledger_marks=%s  portfolio=%s" % (
                s["as_of"], s["stages"]["clean"]["universe"], w, m, s["portfolio"]))
            return s
        finally:
            store.close()
