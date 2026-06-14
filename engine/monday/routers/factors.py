"""/api/factors — the factor catalog (what each feature column means)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/factors", tags=["factors"])

CATALOG = [
    {"name": "mom_20d", "group": "momentum", "desc": "1-month total return"},
    {"name": "mom_60d", "group": "momentum", "desc": "3-month total return"},
    {"name": "mom_120d", "group": "momentum", "desc": "6-month total return"},
    {"name": "dist_high_60d", "group": "momentum", "desc": "distance below the 60d high (≤0)"},
    {"name": "rsi_14", "group": "technical", "desc": "14-day RSI"},
    {"name": "vol_20d", "group": "risk", "desc": "20-day realized volatility"},
    {"name": "atr_14", "group": "risk", "desc": "14-day ATR (drives TP/SL sizing, §5.5)"},
    {"name": "adv_20d", "group": "liquidity", "desc": "20-day avg dollar volume (universe gate)"},
    {"name": "foreign_net_5d", "group": "chips", "desc": "foreign-investor 5d net buy (shares)"},
    {"name": "foreign_streak", "group": "chips", "desc": "consecutive foreign net-buy(+)/sell(-) days"},
    {"name": "invtrust_net_5d", "group": "chips", "desc": "investment-trust 5d net buy"},
    {"name": "invtrust_streak", "group": "chips", "desc": "consecutive investment-trust net-buy/sell days"},
    {"name": "margin_chg_5d", "group": "chips", "desc": "margin (融資) balance 5d change"},
    {"name": "short_chg_5d", "group": "chips", "desc": "short-sale (融券) balance 5d change"},
]


@router.get("")
def list_factors() -> dict:
    return {"items": CATALOG, "total": len(CATALOG),
            "note": "momentum/technical + chips (籌碼, via /api/chips) groups are live; "
                    "fundamental / event / sentiment / regime factor groups land later (§4.3)."}
