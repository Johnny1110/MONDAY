"""/api/book — the 2.0 managed book the User trades (A3, token-free).

Holdings, the decision-agnostic fill writer (decision 3), TP/SL targets, the lifecycle action log,
and exposure/cash. **The swarm proposes fills, the User confirms — the engine records them but NEVER
places an order** (invariant 11; the User is the air-gap). No broker integration, ever.
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, HTTPException

from .. import book as book_mod
from .. import pagination, sizing as sizing_mod, store
from ..config import settings

router = APIRouter(prefix="/api/book", tags=["book"])


def _today() -> str:
    return date.today().isoformat()


def _today_regime() -> str:
    """The latest run's regime/risk-state, for default sizing scale (neutral if unknown)."""
    as_of = store.kv_get("last_as_of")
    if as_of:
        meta = json.loads(store.kv_get(f"predictions_meta:{as_of}") or "{}")
        if meta.get("regime"):
            return meta["regime"]
    raw = store.kv_get("signals_today")
    if raw:
        return json.loads(raw).get("regime") or "neutral"
    return "neutral"


@router.get("")
def list_holdings(book: str | None = None, status: str | None = "open",
                  page: int = 1, page_size: int = 50) -> dict:
    """Holdings (paginated) + an exposure ``summary``. ``book`` defaults to ``settings.book_mode``;
    ``status=all`` returns open+closed."""
    book = book or settings.book_mode
    st = None if (status in (None, "", "all")) else status
    env = pagination.paginate(book_mod.list_book(book, st), page, page_size)
    env["book"] = book
    env["summary"] = book_mod.book_exposure(book)
    return env


@router.post("/fill")
def fill(payload: dict) -> dict:
    """Record one fill (decision-agnostic, decision 3). Body: ``{symbol, side, qty, price, book?, at?,
    source?, rec_id?, name?, reason?, regime?, take_profit?, stop_loss?, fill_key?}``. ``side ∈
    {buy, sell}``; ``at`` defaults to ``last_as_of``. Pass ``fill_key`` to make a confirm idempotent.
    Returns the updated lot + the logged action. **Records a fill — never places an order** (inv. 11)."""
    for req in ("symbol", "side", "qty", "price"):
        if payload.get(req) is None:
            raise HTTPException(status_code=422, detail=f"missing field: {req}")
    side = str(payload["side"]).lower()
    if side not in ("buy", "sell"):
        raise HTTPException(status_code=422, detail="side must be buy|sell")
    try:
        qty = float(payload["qty"]); price = float(payload["price"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="qty and price must be numbers")
    if qty <= 0 or price <= 0:
        raise HTTPException(status_code=422, detail="qty and price must be > 0")
    book = payload.get("book") or settings.book_mode
    at = payload.get("at") or store.kv_get("last_as_of") or _today()
    try:
        return book_mod.record_fill(
            book, str(payload["symbol"]), side, qty, price, at,
            source=payload.get("source") or "morgan", rec_id=payload.get("rec_id"),
            name=payload.get("name"), reason=payload.get("reason"), regime=payload.get("regime"),
            take_profit=payload.get("take_profit"), stop_loss=payload.get("stop_loss"),
            fill_key=payload.get("fill_key"))
    except ValueError as e:                              # e.g. selling a lot we don't hold
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/targets")
def targets(payload: dict) -> dict:
    """Set a lot's take-profit / stop-loss (morgan's review output, A5). Body:
    ``{symbol, book?, take_profit?, stop_loss?}``."""
    if not payload.get("symbol"):
        raise HTTPException(status_code=422, detail="missing field: symbol")
    book = payload.get("book") or settings.book_mode
    pos = book_mod.set_targets(book_mod._position_id(book, str(payload["symbol"])),  # noqa: SLF001
                               take_profit=payload.get("take_profit"),
                               stop_loss=payload.get("stop_loss"))
    if pos is None:
        raise HTTPException(status_code=404,
                            detail=f"no lot for {payload['symbol']} in book {book!r}")
    return pos


@router.get("/actions")
def actions(since: str | None = None, position_id: str | None = None,
            page: int = 1, page_size: int = 50) -> dict:
    """The append-only lifecycle log (paginated; A9 + the weekly review read it). ``since`` is an
    inclusive YYYY-MM-DD lower bound on ``action_date``."""
    return pagination.paginate(
        store.list_position_actions(position_id=position_id, since=since), page, page_size)


@router.get("/exposure")
def exposure_view(book: str | None = None) -> dict:
    """Current exposure/cash/by-sector for ``book`` (risk-monitor's GATE 2 input, A4/B4)."""
    return book_mod.book_exposure(book or settings.book_mode)


@router.post("/sizing")
def sizing(payload: dict) -> dict:
    """Size today's candidates against the book (A4): risk-budget × conviction × regime scale, capped.
    Body: ``{candidates:[{symbol, conviction, atr_stop_pct?|stop_loss?, price, sector?}], regime_state?,
    book_value?, book?}``. ``book_value`` defaults to the book's exposure total (else starting cash);
    ``regime_state`` to the latest run's regime. Returns ``{book, book_value, regime_state, sizing:[…]}``.
    Sizing never levers and has no knob to chase the 10% target (decision 4)."""
    cands = payload.get("candidates") or []
    if not cands:
        raise HTTPException(status_code=422, detail="candidates required")
    book = payload.get("book") or settings.book_mode
    book_value = payload.get("book_value")
    if book_value is None:
        book_value = book_mod.book_exposure(book).get("total") or settings.book_starting_cash
    regime_state = payload.get("regime_state") or _today_regime()
    norm = [{
        "symbol": c.get("symbol"), "sector": c.get("sector"), "conviction": c.get("conviction"),
        "price": c.get("price"),
        "atr_stop_pct": sizing_mod.stop_pct(c.get("atr_stop_pct"), c.get("stop_loss"),
                                            c.get("price"), settings.sl_pct_floor),
    } for c in cands]
    results = sizing_mod.size_book(
        norm, book_value=book_value, regime_state=regime_state,
        risk_budget_pct=settings.risk_budget_pct_per_trade,
        max_position_pct=settings.book_max_position_pct,
        max_total_exposure_pct=settings.max_total_exposure_pct, lot_size=settings.lot_size)
    return {"book": book, "book_value": book_value, "regime_state": regime_state, "sizing": results}
