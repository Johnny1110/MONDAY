"""TPEx (上櫃) adapters — OTC-board daily prices.

One endpoint:
  * **t187ap03_L** (OpenAPI) — every OTC instrument's latest trading day in one call.
Returns ROC-dated JSON similar to TWSE STOCK_DAY_ALL. Keeps only 4-digit common stocks
(skips ETFs/warrants). Parser is pure (testable); fetcher adds cache + rate-limit.
"""

from __future__ import annotations

from . import base
from .parse import num, roc_to_iso

TPEX_DAILY_ALL = "https://www.tpex.org.tw/openapi/v1/mops2/t187ap03_L"


def _bar(symbol, name, dt, o, h, lo, c, vol) -> dict | None:
    if dt is None or None in (o, h, lo, c) or min(o, h, lo, c) <= 0:
        return None
    return {"symbol": symbol, "name": name, "date": dt,
            "open": o, "high": h, "low": lo, "close": c, "volume": int(vol or 0)}


def parse_tpex_daily_all(payload: list | None) -> list[dict]:
    """TPEx t187ap03_L JSON array → normalized bars (4-digit common stocks only).

    Field names match the TPEx OpenAPI: SecuritiesCompanyCode (or Code), CompanyName (or Name),
    TradeVolume, OpeningPrice, HighestPrice, LowestPrice, ClosingPrice. Accepts both ROC and
    ISO dates (the API may return either depending on the version)."""
    bars = []
    for r in payload or []:
        code = (r.get("SecuritiesCompanyCode") or r.get("Code") or "").strip()
        if not (len(code) == 4 and code.isdigit()):
            continue
        name = (r.get("CompanyName") or r.get("Name") or "").strip()
        dt = roc_to_iso(r.get("Date"))
        if dt is None and r.get("Date"):
            # TPEx may return ISO dates directly in some versions
            from datetime import date as dt_cls
            try:
                dt_cls.fromisoformat(str(r["Date"]))
                dt = str(r["Date"])
            except (ValueError, TypeError):
                pass
        bar = _bar(code, name, dt,
                   num(r.get("OpeningPrice")), num(r.get("HighestPrice")),
                   num(r.get("LowestPrice")), num(r.get("ClosingPrice")),
                   num(r.get("TradeVolume")))
        if bar:
            bars.append(bar)
    return bars


def fetch_daily_all(cache_dir: str | None = None, ttl: float = 43200) -> list[dict]:
    """The latest trading day's full OTC cross-section (universe discovery)."""
    return parse_tpex_daily_all(base.fetch_json(
        TPEX_DAILY_ALL, cache_dir=cache_dir, ttl=ttl, rate_key="tpex", min_interval=1.0))
