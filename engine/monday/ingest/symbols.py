"""Curated fallback universe — a slice of TW large/mid caps (codes + names).

This is the real-source fallback used by ``ingest.get_source`` when the dynamic TWSE liquidity
universe (``ingest.universe.build_universe``) can't be built (e.g. TWSE unreachable). The dynamic
top-N-by-liquidity board is preferred in production; this list just guarantees the chain never
runs empty. Codes/names are real listed tickers.
"""

from __future__ import annotations

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
