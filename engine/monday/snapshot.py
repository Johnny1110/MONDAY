"""Point-in-time (PIT) snapshots — the #1 look-ahead-bias cure (whitepaper §4.2).

The single most important asset Monday accrues: every post-close, archive the data visible
THAT day, stamped ``as_of``, as-is. Calibration and post-launch walk-forward read only the PIT
view rebuilt from these snapshots — never "today's latest value" retro-applied to the past.
Stored in parquet (invariant 5); re-snapshotting an ``as_of`` overwrites it (idempotent rerun),
but a prior day's snapshot is never mutated.
"""

from __future__ import annotations

import pathlib

from . import parquetio


def snapshot_path(data_dir: str) -> str:
    return str(pathlib.Path(data_dir) / "snapshots" / "prices.parquet")


def write_snapshot(data_dir: str, as_of: str, bars: list[dict]) -> int:
    """Append the day's visible bars, each stamped with ``as_of``. Returns total rows on disk."""
    rows = [{**b, "as_of": as_of} for b in bars]
    return parquetio.upsert(snapshot_path(data_dir), rows, keys=["as_of"])


def read_snapshot(data_dir: str, as_of: str | None = None) -> list[dict]:
    where = {"as_of": as_of} if as_of else None
    return parquetio.read_rows(snapshot_path(data_dir), where)
