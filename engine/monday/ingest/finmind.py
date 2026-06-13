"""FinMind adapter — long-history daily prices (whitepaper §4.1; best for cold-start backfill).

The ``TaiwanStockPrice`` dataset is already ISO-dated with clean numeric types and multi-year
history — directly addressing the §11 recommendation to widen the cold-start window past
CMoney's 1 year. The token is optional (it raises the free-tier rate limit) and is read
engine-side, never exposed to agents (invariant 2). Parser is pure (tested); fetcher adds cache.
"""

from __future__ import annotations

from . import base

API = "https://api.finmindtrade.com/api/v4/data"


def parse_price(payload: dict | None, name: str | None = None) -> list[dict]:
    """FinMind TaiwanStockPrice JSON ({status, data:[{date, stock_id, open, max, min, close,
    Trading_Volume}]}) → normalized bars. (max→high, min→low.)"""
    if not payload or payload.get("status") != 200:
        return []
    bars = []
    for r in payload.get("data") or []:
        try:
            o, h, lo, c = float(r["open"]), float(r["max"]), float(r["min"]), float(r["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if min(o, h, lo, c) <= 0 or not r.get("date"):
            continue
        bars.append({"symbol": str(r.get("stock_id")), "name": name, "date": r["date"],
                     "open": o, "high": h, "low": lo, "close": c,
                     "volume": int(r.get("Trading_Volume") or 0)})
    return bars


def fetch_price(symbol: str, start, end=None, token: str = "", name: str | None = None,
                cache_dir: str | None = None, ttl: float = 43200) -> list[dict]:
    """Daily bars for ``symbol`` over [start, end] (ISO dates or date objects)."""
    params = {"dataset": "TaiwanStockPrice", "data_id": symbol, "start_date": str(start)}
    if end:
        params["end_date"] = str(end)
    if token:
        params["token"] = token
    payload = base.fetch_json(API, params, cache_dir=cache_dir, ttl=ttl,
                              rate_key="finmind", min_interval=0.6)
    return parse_price(payload, name)
