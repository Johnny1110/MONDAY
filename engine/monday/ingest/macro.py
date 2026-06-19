"""Macro adapter — world indices for the 2.0 top-down read (A2, whitepaper §4.3).

Free, **key-less** source: the Yahoo Finance v8 chart JSON (one GET per symbol), behind
``base.fetch_json`` so it inherits the platform's cache + per-host rate-limit + retry + quota
hygiene (invariant 6, stdlib urllib only). A single dead/blocked ticker is tolerated — it is
logged and omitted so one bad symbol never sinks the batch (the brief degrades, it doesn't crash).
The parser is pure (tested against a recorded fixture, no live network in tests).
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone

from . import base

log = logging.getLogger("monday.ingest")

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# Yahoo rejects a bare/unknown UA on some edges — present a browser-like one (no key, still token-free).
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _range_for(days: int) -> str:
    """Map a desired lookback to Yahoo's coarse ``range`` buckets — always wide enough for ≥2 bars
    (so prev_close exists across a weekend/holiday)."""
    if days <= 5:
        return "5d"
    if days <= 25:
        return "1mo"
    if days <= 80:
        return "3mo"
    return "6mo"


def parse_chart(payload: dict | None) -> list[dict]:
    """Yahoo v8 chart JSON → ``[{date, close}, …]`` ascending (latest last). Pure + tolerant: returns
    ``[]`` on any missing/malformed shape, skips null closes (the current incomplete bar). ``date`` is
    the **local trading date** (timestamp shifted by the exchange ``gmtoffset`` so an Asian midnight bar
    or a US 09:30 ET bar both land on the right civil day)."""
    try:
        result = (payload or {})["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        return []
    timestamps = result.get("timestamp") or []
    try:
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return []
    gmtoffset = (result.get("meta") or {}).get("gmtoffset") or 0
    rows = []
    for ts, c in zip(timestamps, closes):
        if ts is None or c is None:
            continue
        try:
            d = datetime.fromtimestamp(int(ts) + int(gmtoffset), tz=timezone.utc).date().isoformat()
            rows.append({"date": d, "close": float(c)})
        except (ValueError, TypeError, OverflowError, OSError):
            continue
    rows.sort(key=lambda r: r["date"])
    return rows


def fetch_indices(symbols: list[str], *, cache_dir: str | None = None, days: int = 7,
                  ttl: float = 43200) -> dict[str, list[dict]]:
    """Per symbol: GET the Yahoo chart via ``base.fetch_json`` (key-less, cached, rate-limited) and
    parse to ``[{date, close}, …]`` latest-last. Returns ``{symbol: rows}``, **omitting** any symbol
    that fails (dead ticker / malformed JSON / rate-limit) — a partial macro read is still useful and
    must never raise into the caller (invariant 8 spirit)."""
    out: dict[str, list[dict]] = {}
    rng = _range_for(days)
    for sym in symbols:
        try:
            payload = base.fetch_json(
                CHART_URL.format(symbol=urllib.parse.quote(sym)),
                {"range": rng, "interval": "1d"},
                cache_dir=cache_dir, ttl=ttl, rate_key="yahoo", min_interval=0.4,
                headers={"User-Agent": _UA})
        except base.RateLimitError as e:
            log.warning("macro: %s rate-limited — omitted (%s)", sym, e)
            continue
        except Exception as e:                      # noqa: BLE001 — one bad ticker never sinks the batch
            log.warning("macro: %s fetch failed — omitted (%s)", sym, e)
            continue
        rows = parse_chart(payload)
        if rows:
            out[sym] = rows
        else:
            log.warning("macro: %s returned no usable bars — omitted", sym)
    return out
