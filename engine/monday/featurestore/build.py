"""Build the daily feature rows from a price panel and persist to parquet (§4.3).

One row per symbol for a given ``as_of``, computed only from bars at or before ``as_of`` (no
look-ahead). Persistence uses ``upsert`` keyed on ``as_of`` so a rerun overwrites that day.
"""

from __future__ import annotations

import pathlib

from .. import parquetio
from . import factors


def _panel(bars: list[dict]) -> dict[str, list[dict]]:
    panel: dict[str, list[dict]] = {}
    for b in sorted(bars, key=lambda x: x["date"]):
        panel.setdefault(b["symbol"], []).append(b)
    return panel


def compute_row(symbol: str, sbars: list[dict], as_of: str) -> dict:
    closes = [b["close"] for b in sbars]
    highs = [b["high"] for b in sbars]
    lows = [b["low"] for b in sbars]
    vols = [b["volume"] for b in sbars]
    adv20 = (sum(c * v for c, v in zip(closes[-20:], vols[-20:])) / min(20, len(closes))
             if closes else None)
    return {
        "as_of": as_of, "symbol": symbol, "name": sbars[-1].get("name"),
        "close": closes[-1] if closes else None,
        "mom_20d": factors.total_return(closes, 20),
        "mom_60d": factors.total_return(closes, 60),
        "mom_120d": factors.total_return(closes, 120),
        "dist_high_60d": factors.dist_from_high(closes, 60),
        "rsi_14": factors.rsi(closes, 14),
        "vol_20d": factors.realized_vol(closes, 20),
        "atr_14": factors.atr(highs, lows, closes, 14),
        "adv_20d": adv20,
        "pe_ratio": None,                      # enriched from FinMind TaiwanStockPER (PIT-safe)
    }


def build_features(bars: list[dict], as_of: str, universe: set[str] | None = None) -> list[dict]:
    """Feature rows for ``as_of``, using only bars ≤ as_of. Restrict to ``universe`` if given."""
    visible = [b for b in bars if b["date"] <= as_of]
    panel = _panel(visible)
    rows = []
    for sym, sbars in panel.items():
        if universe is not None and sym not in universe:
            continue
        rows.append(compute_row(sym, sbars, as_of))
    return rows


def features_path(data_dir: str) -> str:
    return str(pathlib.Path(data_dir) / "features" / "features.parquet")


def write_features(data_dir: str, rows: list[dict]) -> int:
    return parquetio.upsert(features_path(data_dir), rows, keys=["as_of", "symbol"])


def read_features(data_dir: str, as_of: str) -> list[dict]:
    return parquetio.read_rows(features_path(data_dir), where={"as_of": as_of})
