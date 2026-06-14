"""/api/portfolio — the paper portfolio (open/closed positions + summary)."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter

from .. import pagination
from .. import portfolio as portfolio_mod
from .. import store
from ..config import settings

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("")
def list_portfolio(status: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    env = pagination.paginate(store.list_positions(status), page, page_size)
    env["summary"] = portfolio_mod.summary()
    return env


@router.get("/summary")
def portfolio_summary() -> dict:
    return portfolio_mod.summary()


@router.get("/equity")
def equity() -> list[dict]:
    """Daily portfolio equity proxy from the ledger: 1 + mean mtm per mark date (drives the
    dashboard equity curve). A small time series — returned whole, not paginated."""
    by_date: dict[str, list[float]] = defaultdict(list)
    for m in store.list_marks():
        if m.get("mtm_return") is not None:
            by_date[m["mark_date"]].append(m["mtm_return"])
    return [{"date": d, "equity": round(1 + sum(v) / len(v), 4),
             "mean_mtm": round(sum(v) / len(v), 4), "n": len(v)}
            for d, v in sorted(by_date.items())]


@router.get("/risk")
def risk_view() -> dict:
    """Run the §5.7 risk gate on the current OPEN book (risk-monitor's read-only patrol):
    sector concentration, name count, liquidity floor. Advisory — never blocks."""
    import pathlib

    from .. import risk
    from ..featurestore import build as fbuild
    from ..ingest import finmind
    as_of = store.kv_get("last_as_of")
    adv = {r["symbol"]: r.get("adv_20d")
           for r in (fbuild.read_features(settings.data_dir, as_of) if as_of else [])}
    try:
        sectors = finmind.fetch_stock_info(settings.finmind_token,
                                           str(pathlib.Path(settings.data_dir) / "cache"))
    except Exception:
        sectors = {}
    picks = [{"symbol": p["symbol"], "sector": sectors.get(p["symbol"], "unknown"),
              "adv_20d": adv.get(p["symbol"])} for p in store.list_positions(status="open")]
    return risk.gate(picks, max_names=settings.max_recommendations,
                     max_per_sector=settings.max_per_sector, adv_floor=settings.liquidity_adv_floor)
