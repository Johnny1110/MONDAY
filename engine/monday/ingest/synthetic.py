"""Deterministic synthetic TW-equity price source (P0 only).

A seeded random walk per symbol — enough OHLCV history for the factor library and the full
pipeline to run with zero network and zero credentials. NOT investable data; it exists so the
P0 exit gate ("trigger one full chain end to end") is reproducible in CI. Real adapters replace
this in P1, emitting the same bar shape: {symbol, name, date, open, high, low, close, volume}.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

# A small slice of TW large/mid caps (codes + names) — labels only; prices are synthetic.
DEFAULT_SYMBOLS: list[tuple[str, str]] = [
    ("2330", "台積電"), ("2317", "鴻海"), ("2454", "聯發科"), ("2308", "台達電"),
    ("2303", "聯電"), ("2412", "中華電"), ("2882", "國泰金"), ("2881", "富邦金"),
    ("2891", "中信金"), ("3711", "日月光投控"), ("2002", "中鋼"), ("1301", "台塑"),
    ("1303", "南亞"), ("2207", "和泰車"), ("2603", "長榮"), ("2609", "陽明"),
    ("3034", "聯詠"), ("3008", "大立光"), ("2379", "瑞昱"), ("2357", "華碩"),
    ("2382", "廣達"), ("2395", "研華"), ("4938", "和碩"), ("2474", "可成"),
    ("6505", "台塑化"), ("1216", "統一"), ("2105", "正新"), ("2880", "華南金"),
    ("5880", "合庫金"), ("2912", "統一超"),
]


def _weekdays(end: date, n: int) -> list[str]:
    """The ``n`` most recent weekdays ending at ``end`` (inclusive), ascending ISO dates."""
    out: list[str] = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:                     # Mon–Fri
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


def generate(end: date | None = None, symbols: list[tuple[str, str]] | None = None,
             days: int = 180, seed: int = 20260613) -> list[dict]:
    """Generate a daily OHLCV panel: ``days`` weekdays ending at ``end`` (default today),
    one row per symbol per day. Fully determined by ``seed`` (reproducible)."""
    end = end or date.today()
    symbols = symbols or DEFAULT_SYMBOLS
    dates = _weekdays(end, days)
    rng = random.Random(seed)
    bars: list[dict] = []
    for code, name in symbols:
        price = rng.uniform(20, 600)
        drift = rng.uniform(-0.0006, 0.0016)    # per-symbol trend
        vol = rng.uniform(0.012, 0.030)
        base_vol = rng.uniform(3e3, 4e5)
        for d in dates:
            prev = price
            ret = rng.gauss(drift, vol)
            price = max(1.0, prev * (1 + ret))
            high = max(prev, price) * (1 + abs(rng.gauss(0, 0.004)))
            low = min(prev, price) * (1 - abs(rng.gauss(0, 0.004)))
            volume = int(base_vol * (1 + abs(rng.gauss(0, 0.4))))
            bars.append({
                "symbol": code, "name": name, "date": d,
                "open": round(prev, 2), "high": round(high, 2),
                "low": round(low, 2), "close": round(price, 2),
                "volume": volume,
            })
    return bars
