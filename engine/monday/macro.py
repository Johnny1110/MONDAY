"""Macro plane (A2) — shape world-index bars into a daily cross-section + PIT snapshot.

The 2.0 flow is top-down: macro-analyst reads world indices / overnight moves to set the day's
risk-on/off (whitepaper §4.3). This module turns the ingest adapter's per-symbol bars into one row
per index for a given ``as_of`` (close / prev_close / chg_pct / asset_class), a small convenience
digest for the brief + dashboard, and a **PIT snapshot** in parquet — same look-ahead discipline as
prices (invariant 9, §4.2): stamp ``as_of``, append-only, never mutate a past day.

Pure shaping (``build_macro_rows`` / ``overnight_changes``) is stdlib-only and unit-tested; only
``refresh`` reaches out (it composes the ingest adapter + the parquet snapshot).
"""

from __future__ import annotations

import logging
import pathlib

from . import parquetio

log = logging.getLogger("monday.macro")

# Indices whose move is read as a risk barometer for TW (semis beta, fear, rates, FX pressure).
_RISK_PROXIES = ("^SOX", "^VIX", "^TNX", "USDTWD=X", "^KS11")


def build_macro_rows(as_of: str, raw: dict[str, list[dict]], meta: dict) -> list[dict]:
    """``{symbol: [{date, close}, …]}`` → one row per symbol for ``as_of``:
    ``{as_of, symbol, name, asset_class, close, prev_close, chg_pct, date}``. Uses the last two bars
    **on or before** ``as_of`` (so a symbol that didn't trade that day falls back to its latest prior
    bar — PIT-honest, no look-ahead). ``chg_pct = (close/prev_close - 1) * 100``."""
    rows = []
    for sym, series in raw.items():
        bars = [b for b in series if b["date"] <= as_of] if as_of else list(series)
        if not bars:
            continue
        close = bars[-1]["close"]
        prev_close = bars[-2]["close"] if len(bars) >= 2 else None
        chg_pct = round((close / prev_close - 1) * 100, 3) if prev_close else None
        m = meta.get(sym) or {}
        rows.append({
            "as_of": as_of, "symbol": sym, "name": m.get("name", sym),
            "asset_class": m.get("asset_class", "equity_index"),
            "close": close, "prev_close": prev_close, "chg_pct": chg_pct,
            "date": bars[-1]["date"],            # the actual last-close date (may precede as_of)
        })
    rows.sort(key=lambda r: r["symbol"])
    return rows


def overnight_changes(rows: list[dict]) -> dict:
    """A small digest for the morning brief / dashboard: biggest movers + the risk-proxy moves.
    ``{leaders:[…], laggards:[…], risk_proxies:{symbol: chg_pct}}`` (leaders best-first, laggards
    worst-first); rows without a ``chg_pct`` are excluded from the ranking."""
    scored = [r for r in rows if r.get("chg_pct") is not None]
    ranked = sorted(scored, key=lambda r: r["chg_pct"], reverse=True)
    proxies = {r["symbol"]: r["chg_pct"] for r in rows
               if r["symbol"] in _RISK_PROXIES and r.get("chg_pct") is not None}
    return {"leaders": ranked[:3], "laggards": ranked[::-1][:3], "risk_proxies": proxies}


# --- PIT snapshot (parquet; mirrors snapshot.py for prices) -------------------------

def macro_snapshot_path(data_dir: str) -> str:
    return str(pathlib.Path(data_dir) / "snapshots" / "macro.parquet")


def write_macro_snapshot(data_dir: str, as_of: str, rows: list[dict]) -> int:
    """Archive the day's macro rows, each stamped ``as_of`` (append-only, idempotent per ``as_of`` —
    re-running a day overwrites it, a prior day is never mutated). Returns total rows on disk."""
    stamped = [{**r, "as_of": as_of} for r in rows]
    return parquetio.upsert(macro_snapshot_path(data_dir), stamped, keys=["as_of"])


def read_macro_snapshot(data_dir: str, as_of: str | None = None) -> list[dict]:
    """The macro snapshot for ``as_of`` (default: the latest archived day). ``[]`` if none yet."""
    all_rows = parquetio.read_rows(macro_snapshot_path(data_dir))
    if not all_rows:
        return []
    if as_of is None:
        as_of = max(r.get("as_of") for r in all_rows)
    return sorted((r for r in all_rows if r.get("as_of") == as_of), key=lambda r: r["symbol"])


def _latest_common_date(raw: dict[str, list[dict]]) -> str | None:
    """The latest date present across ALL fetched symbols (so every index has a bar that day);
    falls back to the latest date seen anywhere when holidays/TZs prevent a perfect intersection."""
    date_sets = [set(b["date"] for b in series) for series in raw.values() if series]
    if not date_sets:
        return None
    common = set.intersection(*date_sets) if len(date_sets) > 1 else date_sets[0]
    if common:
        return max(common)
    return max(d for ds in date_sets for d in ds)


def refresh(data_dir: str, cache_dir: str, symbols=None, as_of: str | None = None,
            days: int = 7) -> dict:
    """Fetch the configured world indices → shape → PIT snapshot. ``as_of`` defaults to the latest
    common trading date across symbols. Best-effort by construction (the adapter omits dead tickers);
    returns ``{as_of, n, rows_on_disk, symbols}``. ``symbols`` defaults to ``config.macro_symbols``."""
    from .config import settings
    from .ingest import macro as macro_ingest
    meta = settings.macro_symbols
    syms = list(symbols) if symbols is not None else list(meta)
    raw = macro_ingest.fetch_indices(syms, cache_dir=cache_dir, days=days)
    # Resilience (ADR 0007): the home index / macro-call benchmark is the one symbol the round can't do
    # without. If Yahoo couldn't serve it (rate-limit / blackout), fill it from TWSE — a different source
    # family — so a Yahoo outage degrades the global brief but never starves the round of the benchmark.
    bench = settings.macro_benchmark_symbol
    if settings.macro_fallback_source == "twse" and bench in syms and bench not in raw:
        taiex = macro_ingest.fetch_taiex(as_of, cache_dir=cache_dir)
        if taiex:
            raw[bench] = taiex
            log.info("macro: %s served by TWSE fallback (%d bars; Yahoo missed it)", bench, len(taiex))
    if as_of is None:
        as_of = _latest_common_date(raw)
    rows = build_macro_rows(as_of, raw, meta) if as_of else []
    on_disk = write_macro_snapshot(data_dir, as_of, rows) if (rows and as_of) else 0
    return {"as_of": as_of, "n": len(rows), "rows_on_disk": on_disk, "symbols": len(raw)}
