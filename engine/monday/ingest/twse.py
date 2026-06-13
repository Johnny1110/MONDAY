"""TWSE adapters — listed-board daily prices (whitepaper §4.1 core source).

Two endpoints behind pure parsers:
  * **STOCK_DAY_ALL** (OpenAPI) — every listed instrument's latest trading day in one call; the
    daily cross-section driver + universe definition going forward. Keeps only 4-digit common
    stocks (skips ETFs/warrants/ETNs whose codes aren't 4 plain digits).
  * **STOCK_DAY** — one stock's month of daily bars (ROC dates, comma numerics); backfills the
    cold-start history one month per call.
Returns RAW (un-adjusted) prices — split/dividend back-adjustment is ``clean.adjust_splits``'s
job (§4.1). Parsers are pure (tested with real fixtures); fetchers add cache + rate-limit.
"""

from __future__ import annotations

from datetime import date

from . import base
from .parse import num, roc_to_iso

OPENAPI_STOCK_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
STOCK_DAY = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"


def _bar(symbol, name, dt, o, h, lo, c, vol) -> dict | None:
    if dt is None or None in (o, h, lo, c) or min(o, h, lo, c) <= 0:
        return None
    return {"symbol": symbol, "name": name, "date": dt,
            "open": o, "high": h, "low": lo, "close": c, "volume": int(vol or 0)}


def parse_stock_day_all(payload: list | None) -> list[dict]:
    """STOCK_DAY_ALL JSON array → normalized bars (4-digit common stocks only)."""
    bars = []
    for r in payload or []:
        code = (r.get("Code") or "").strip()
        if not (len(code) == 4 and code.isdigit()):
            continue
        bar = _bar(code, (r.get("Name") or "").strip(), roc_to_iso(r.get("Date")),
                   num(r.get("OpeningPrice")), num(r.get("HighestPrice")),
                   num(r.get("LowestPrice")), num(r.get("ClosingPrice")), num(r.get("TradeVolume")))
        if bar:
            bars.append(bar)
    return bars


def parse_stock_day(payload: dict | None, symbol: str, name: str | None = None) -> list[dict]:
    """STOCK_DAY JSON ({stat, data:[[日期,成交股數,成交金額,開,高,低,收,…]]}) → bars."""
    if not payload or payload.get("stat") != "OK":
        return []
    bars = []
    for row in payload.get("data") or []:
        if len(row) < 7:
            continue
        bar = _bar(symbol, name, roc_to_iso(row[0]), num(row[3]), num(row[4]),
                   num(row[5]), num(row[6]), num(row[1]))
        if bar:
            bars.append(bar)
    return bars


def fetch_daily_all(cache_dir: str | None = None, ttl: float = 43200) -> list[dict]:
    """The latest trading day's full cross-section (universe + last bar)."""
    return parse_stock_day_all(base.fetch_json(
        OPENAPI_STOCK_DAY_ALL, cache_dir=cache_dir, ttl=ttl, rate_key="twse", min_interval=1.0))


def fetch_stock_month(symbol: str, yyyymmdd: str, name: str | None = None,
                      cache_dir: str | None = None, ttl: float = 864000) -> list[dict]:
    payload = base.fetch_json(STOCK_DAY, {"response": "json", "stockNo": symbol, "date": yyyymmdd},
                              cache_dir=cache_dir, ttl=ttl, rate_key="twse", min_interval=1.0)
    return parse_stock_day(payload, symbol, name)


def fetch_stock_history(symbol: str, months: int = 10, name: str | None = None,
                        end: date | None = None, cache_dir: str | None = None) -> list[dict]:
    """Backfill ~``months`` of daily bars via per-month STOCK_DAY calls (deduped, ascending)."""
    end = end or date.today()
    y, m = end.year, end.month
    bars: list[dict] = []
    for _ in range(months):
        bars = fetch_stock_month(symbol, f"{y:04d}{m:02d}01", name, cache_dir) + bars
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    seen, out = set(), []
    for b in sorted(bars, key=lambda x: x["date"]):
        if b["date"] not in seen:
            seen.add(b["date"])
            out.append(b)
    return out
