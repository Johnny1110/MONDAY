"""FinMind adapter — long-history daily prices (whitepaper §4.1; best for cold-start backfill).

The ``TaiwanStockPrice`` dataset is already ISO-dated with clean numeric types and multi-year
history — directly addressing the §11 recommendation to widen the cold-start window past
CMoney's 1 year. The token is optional (it raises the free-tier rate limit) and is read
engine-side, never exposed to agents (invariant 2). Parser is pure (tested); fetcher adds cache.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from . import base

API = "https://api.finmindtrade.com/api/v4/data"


def _anchor_start(as_of, lookback_days: int) -> str:
    """Month-quantized lower bound (first of the month, ``lookback_days`` before ``as_of``). Anchoring
    to the month keeps each symbol's cache key STABLE across daily runs — the old sliding start/end
    changed the key every day, forcing a full cold re-fetch of the whole universe on every run."""
    d = (as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of))) - timedelta(days=lookback_days)
    return date(d.year, d.month, 1).isoformat()


def _bulk(items, work, label: str):
    """Run ``work(item)`` concurrently; stop + return partial on the first RateLimitError (quota).
    Cached items short-circuit inside ``work`` (no network), so a re-run after a partial pull resumes.
    Returns the list of results (one per completed item)."""
    from ..config import settings
    results, hit = [], False
    with ThreadPoolExecutor(max_workers=max(1, settings.ingest_max_workers)) as ex:
        futs = {ex.submit(work, it): it for it in items}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except base.RateLimitError:
                hit = True
                for f in futs:
                    f.cancel()
    if hit:
        base.log.warning("FinMind rate limit hit — %s partial: %d/%d (re-run to resume from cache)",
                         label, len(results), len(items))
    return results


def fetch_universe_prices(symbols, as_of, lookback_days: int, token: str = "",
                          cache_dir: str | None = None) -> list[dict]:
    """Concurrent daily-price pull for the whole universe (the daily-ingest hot path). Month-anchored
    cache (stable key) + thread pool + graceful partial on quota — replaces the serial per-symbol loop
    that took >15 min and timed out. ``symbols`` is a list of (code, name)."""
    start = _anchor_start(as_of, lookback_days)
    per_symbol = _bulk(
        symbols,
        lambda it: fetch_price(it[0], start, None, token=token, name=it[1],
                               cache_dir=cache_dir, min_interval=0.0),
        "prices")
    return [bar for bars in per_symbol for bar in bars]


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
                cache_dir: str | None = None, ttl: float = 21600, min_interval: float = 0.6) -> list[dict]:
    """Daily bars for ``symbol`` over [start, end] (ISO dates or date objects). The concurrent universe
    pull passes ``min_interval=0`` (pool size bounds throughput instead of a per-call serial wait)."""
    params = {"dataset": "TaiwanStockPrice", "data_id": symbol, "start_date": str(start)}
    if end:
        params["end_date"] = str(end)
    if token:
        params["token"] = token
    payload = base.fetch_json(API, params, cache_dir=cache_dir, ttl=ttl,
                              rate_key="finmind", min_interval=min_interval)
    return parse_price(payload, name)


def parse_stock_info(payload: dict | None) -> dict[str, str]:
    """TaiwanStockInfo JSON → {stock_id: sector}. A stock lists several industry_category rows
    (a specific sub-industry plus the broad '電子工業' umbrella); prefer the specific one — that's
    what the §5.7 sector-concentration gate cares about ('不能 20 檔都是半導體')."""
    if not payload or payload.get("status") != 200:
        return {}
    cats: dict[str, list[str]] = {}
    for r in payload.get("data") or []:
        sid, ind = r.get("stock_id"), r.get("industry_category")
        if sid and ind:
            cats.setdefault(sid, []).append(ind)
    out: dict[str, str] = {}
    for sid, inds in cats.items():
        specific = [i for i in inds if i != "電子工業"]
        out[sid] = (specific or inds)[0]
    return out


def fetch_stock_info(token: str = "", cache_dir: str | None = None,
                     ttl: float = 604800) -> dict[str, str]:
    """{stock_id: sector} for every listed stock (cached 7d — sectors rarely change)."""
    params = {"dataset": "TaiwanStockInfo"}
    if token:
        params["token"] = token
    payload = base.fetch_json(API, params, cache_dir=cache_dir, ttl=ttl,
                              rate_key="finmind", min_interval=0.6)
    return parse_stock_info(payload)


# Three institutional desks (§4.3 籌碼): foreign / investment-trust / dealer net flow.
_FOREIGN = {"Foreign_Investor", "Foreign_Dealer_Self"}
_DEALER = {"Dealer_self", "Dealer_Hedging"}


def parse_institutional(payload: dict | None) -> list[dict]:
    """TaiwanStockInstitutionalInvestorsBuySell (one row per desk per day) → per-date net flows
    {date, foreign_net, invtrust_net, dealer_net} (shares), ascending."""
    if not payload or payload.get("status") != 200:
        return []
    by_date: dict[str, dict] = {}
    for r in payload.get("data") or []:
        d, nm = r.get("date"), r.get("name")
        if not d:
            continue
        try:
            net = int(r.get("buy") or 0) - int(r.get("sell") or 0)
        except (TypeError, ValueError):
            continue
        agg = by_date.setdefault(d, {"date": d, "foreign_net": 0, "invtrust_net": 0, "dealer_net": 0})
        if nm in _FOREIGN:
            agg["foreign_net"] += net
        elif nm == "Investment_Trust":
            agg["invtrust_net"] += net
        elif nm in _DEALER:
            agg["dealer_net"] += net
    return [by_date[d] for d in sorted(by_date)]


def parse_margin(payload: dict | None) -> list[dict]:
    """TaiwanStockMarginPurchaseShortSale → per-date {date, margin_balance, short_balance}, ascending."""
    if not payload or payload.get("status") != 200:
        return []
    out = []
    for r in payload.get("data") or []:
        if not r.get("date"):
            continue
        try:
            out.append({"date": r["date"],
                        "margin_balance": float(r.get("MarginPurchaseTodayBalance") or 0),
                        "short_balance": float(r.get("ShortSaleTodayBalance") or 0)})
        except (TypeError, ValueError):
            continue
    return sorted(out, key=lambda x: x["date"])


def _chip_fetch(dataset: str, symbol: str, start, end, token, cache_dir, ttl, min_interval=0.6):
    params = {"dataset": dataset, "data_id": symbol, "start_date": str(start)}
    if end:
        params["end_date"] = str(end)
    if token:
        params["token"] = token
    return base.fetch_json(API, params, cache_dir=cache_dir, ttl=ttl,
                           rate_key="finmind", min_interval=min_interval)


def fetch_institutional(symbol: str, start, end=None, token: str = "", cache_dir: str | None = None,
                        ttl: float = 21600, min_interval: float = 0.6) -> list[dict]:
    return parse_institutional(_chip_fetch("TaiwanStockInstitutionalInvestorsBuySell",
                                           symbol, start, end, token, cache_dir, ttl, min_interval))


def fetch_margin(symbol: str, start, end=None, token: str = "", cache_dir: str | None = None,
                 ttl: float = 21600, min_interval: float = 0.6) -> list[dict]:
    return parse_margin(_chip_fetch("TaiwanStockMarginPurchaseShortSale",
                                    symbol, start, end, token, cache_dir, ttl, min_interval))


def fetch_chips(symbols, start, end=None, token: str = "",
                cache_dir: str | None = None) -> dict[str, dict]:
    """{symbol: {inst, margin}} for the universe — concurrent, month-anchored cache, graceful partial
    on quota (the enrich step tolerates missing symbols). Two calls per symbol (法人 + 融資券)."""
    def one(s):
        return s, {"inst": fetch_institutional(s, start, end, token, cache_dir, min_interval=0.0),
                   "margin": fetch_margin(s, start, end, token, cache_dir, min_interval=0.0)}
    return dict(_bulk(list(symbols), one, "chips"))


# ── TaiwanStockBalanceSheet (§4.3 基本面) ──────────────────────────────────
# Quarterly IFRS balance-sheet items. FinMind returns one row per (stock_id, date, type)
# with a float64 ``value`` and ``origin_name`` (Chinese label). The parser normalises
# to a compact [{date, stock_id, type, value}] list. Cache TTL is 7 days — quarterly
# filings don't change intra-week.

def parse_balance_sheet(payload: dict | None) -> list[dict]:
    """TaiwanStockBalanceSheet JSON → [{date, stock_id, type, value}], ascending by date."""
    if not payload or payload.get("status") != 200:
        return []
    rows = []
    for r in payload.get("data") or []:
        try:
            rows.append({"date": r["date"], "stock_id": str(r["stock_id"]),
                         "type": r["type"], "value": float(r["value"])})
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(rows, key=lambda x: x["date"])


def fetch_balance_sheet(symbol: str, start, end=None, token: str = "",
                        cache_dir: str | None = None,
                        ttl: float = 604800, min_interval: float = 0.6) -> list[dict]:
    """Quarterly balance-sheet rows for ``symbol``. Returns [{date, stock_id, type, value}]."""
    return parse_balance_sheet(
        _chip_fetch("TaiwanStockBalanceSheet", symbol, start, end, token, cache_dir, ttl,
                    min_interval))


def fetch_balance_sheets(symbols, start, end=None, token: str = "",
                         cache_dir: str | None = None) -> dict[str, list[dict]]:
    """{symbol: [balance-sheet rows]} for the universe — concurrent, month-anchored cache,
    graceful partial on quota."""
    def one(s):
        return s, fetch_balance_sheet(s, start, end, token, cache_dir, min_interval=0.0)
    return dict(_bulk(list(symbols), one, "balance_sheets"))
