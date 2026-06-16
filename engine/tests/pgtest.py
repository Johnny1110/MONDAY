"""Shared Postgres test harness.

The store is now PostgreSQL-backed, so store-backed tests need a reachable database. They run against a
**throwaway** DB from ``MONDAY_TEST_DSN`` (default a local ``monday_test``) and **auto-skip** when none
is reachable — mirroring the pyarrow-gated skips elsewhere, so the pure-logic suite still runs on a bare
box. Each store-backed test starts from ``store.reset()`` for isolation; point this at a disposable
database, never production.
"""

from __future__ import annotations

import os
import unittest

TEST_DSN = os.environ.get(
    "MONDAY_TEST_DSN", "postgresql://monday:monday@127.0.0.1:5432/monday_test")


def _pg_reachable(dsn: str) -> bool:
    try:
        import psycopg
    except Exception:
        return False
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            return True
    except Exception:
        return False


PG_AVAILABLE = _pg_reachable(TEST_DSN)
requires_pg = unittest.skipUnless(
    PG_AVAILABLE, f"needs a reachable Postgres (set MONDAY_TEST_DSN; tried {TEST_DSN})")


def fresh_store(dsn: str = TEST_DSN) -> None:
    """Connect + clean slate for a test: wipe the transactional tables AND release any pipeline lock a
    prior test left held (the lock row persists in a shared PG DB, unlike a fresh sqlite ``:memory:``)."""
    from monday import store
    store.connect(dsn)
    store.reset()
    store.acquire_pipeline_lock("_setup_", stale_seconds=0)   # steal any leftover lease …
    store.release_pipeline_lock("_setup_")                    # … then free it
