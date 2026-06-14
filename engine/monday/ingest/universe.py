"""Universe definition (whitepaper §4.1) — the analysable pool, by liquidity.

The full listed board is ~1,000+ names, and cross-sectional ranking needs breadth (a 30-name
universe has no statistical power — §5.1). So the universe is the TOP-N by dollar volume — the
hard liquidity gate at the universe level (§4.1: a 1-month swing must get in and out) — taken from
TWSE's all-stocks latest cross-section (one keyless call). ``rank_universe`` is pure + tested;
``build_universe`` fetches then ranks.
"""

from __future__ import annotations


def rank_universe(bars: list[dict], top_n: int) -> list[tuple[str, str]]:
    """Rank a one-day cross-section by dollar volume (close × volume); return the top_n (code, name)."""
    ranked = sorted(bars, key=lambda b: (b.get("close") or 0) * (b.get("volume") or 0), reverse=True)
    return [(b["symbol"], b.get("name") or b["symbol"]) for b in ranked[:top_n]]


def build_universe(top_n: int, cache_dir: str | None = None) -> list[tuple[str, str]]:
    """Top-N listed names by liquidity from TWSE STOCK_DAY_ALL (one keyless call, cached)."""
    from . import twse
    return rank_universe(twse.fetch_daily_all(cache_dir=cache_dir), top_n)
