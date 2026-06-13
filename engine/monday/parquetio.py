"""Parquet I/O for the large, read-only analysis tables (invariant 5).

PIT snapshots, price history and the feature store live in parquet (columnar, analysis-
friendly), NOT sqlite — sqlite is reserved for transactional state (recs/ledger/…). pyarrow
is a heavy dep, so it is **lazily imported** here (invariant 6); nothing at module top level
pulls it in, keeping the pure-logic layers importable in any environment.

P0 keeps the storage model deliberately simple: one parquet file per logical table, and
``append`` does read-modify-rewrite (the datasets are small in the scaffold). The append-only
*semantics* (never mutate a prior ``as_of`` row) are what matter for PIT correctness; swapping
the physical layout for a partitioned dataset later is an internal change behind this seam.
"""

from __future__ import annotations

import pathlib
from typing import Any


def _pa():
    import pyarrow as pa            # lazy (invariant 6)
    import pyarrow.parquet as pq
    return pa, pq


def exists(path: str) -> bool:
    return pathlib.Path(path).is_file()


def write_table(path: str, rows: list[dict], append: bool = False) -> int:
    """Write ``rows`` to a parquet file. ``append=True`` preserves existing rows
    (read-modify-rewrite). Returns the total row count now on disk. No-op on empty input."""
    pa, pq = _pa()
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if append and p.is_file():
        rows = read_rows(path) + rows
    if not rows:
        return 0
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, str(p))
    return len(rows)


def read_rows(path: str, where: dict | None = None) -> list[dict]:
    """Read a parquet file back to a list of dicts, optionally filtered by exact-match
    ``where`` (e.g. ``{"as_of": "2026-06-13"}``). Returns [] when the file is absent."""
    if not exists(path):
        return []
    _, pq = _pa()
    rows = pq.read_table(str(path)).to_pylist()
    if where:
        rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
    return rows


def upsert(path: str, rows: list[dict], keys: list[str]) -> int:
    """Replace any existing rows whose ``keys`` tuple matches an incoming row, then write the
    union. Makes re-running a day idempotent (re-snapshotting an ``as_of`` overwrites it rather
    than duplicating). Returns the total row count now on disk."""
    existing = read_rows(path)
    if existing and rows:
        incoming = {tuple(r.get(k) for k in keys) for r in rows}
        existing = [e for e in existing if tuple(e.get(k) for k in keys) not in incoming]
    return write_table(path, existing + rows)
