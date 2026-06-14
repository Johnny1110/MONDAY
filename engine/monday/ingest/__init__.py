"""Ingest adapters: pull raw external data, rate-limit, retry, cache (whitepaper §2 platform).

Credentials live in config (engine-side, invariant 1). Three sources behind a uniform registry —
``get_source(name)`` returns a callable ``fetch(days, end_date, cache_dir, token, symbols)`` that
yields bars in the normalized shape {symbol, name, date, open, high, low, close, volume}:

  * **synthetic** — deterministic, offline, no keys (P0 default; reproducible CI).
  * **finmind**   — real FinMind TaiwanStockPrice backfill (long history; cold-start workhorse).
  * **twse**      — real TWSE STOCK_DAY per-month backfill (official listed-board source).

The pipeline selects one via its ``source`` argument; everything downstream (clean → snapshot →
features → model) is source-agnostic.
"""

from __future__ import annotations

from datetime import date, timedelta

from .synthetic import DEFAULT_SYMBOLS
from .synthetic import generate as _synth_generate


def _synthetic_source(days, end_date=None, cache_dir=None, token="", symbols=None):
    return _synth_generate(end=end_date, days=days, symbols=symbols)


def _real_universe(symbols, cache_dir):
    """Resolve the symbol list for a real source: caller-given, else the top-N listed board by
    liquidity (§4.1), falling back to the curated set if TWSE is unreachable."""
    if symbols is not None:
        return symbols
    from ..config import settings
    from .universe import build_universe
    return build_universe(settings.universe_size, cache_dir=cache_dir) or DEFAULT_SYMBOLS


def _finmind_source(days, end_date=None, cache_dir=None, token="", symbols=None):
    from . import finmind
    symbols = _real_universe(symbols, cache_dir)
    end = end_date or date.today()
    start = end - timedelta(days=int(days * 1.7) + 20)   # calendar span → ~days trading rows
    bars: list[dict] = []
    for code, name in symbols:
        bars += finmind.fetch_price(code, start, end, token=token, name=name, cache_dir=cache_dir)
    return bars


def _twse_source(days, end_date=None, cache_dir=None, token="", symbols=None):
    from . import twse
    symbols = _real_universe(symbols, cache_dir)
    end = end_date or date.today()
    months = max(2, days // 18 + 2)
    bars: list[dict] = []
    for code, name in symbols:
        bars += twse.fetch_stock_history(code, months=months, name=name, end=end, cache_dir=cache_dir)
    return bars


_SOURCES = {"synthetic": _synthetic_source, "finmind": _finmind_source, "twse": _twse_source}


def get_source(name: str | None):
    """Return the fetch callable for ``name`` (default 'synthetic'). Raises on unknown source."""
    src = _SOURCES.get((name or "synthetic").lower())
    if src is None:
        raise ValueError(f"unknown ingest source: {name!r} (have {sorted(_SOURCES)})")
    return src


def source_names() -> list[str]:
    return sorted(_SOURCES)
