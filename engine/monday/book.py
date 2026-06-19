"""The 2.0 managed book (A3) — what we hold, at what size, and every lifecycle action.

1.0's ``paper_positions`` is a fixed-qty=1 auto sim that ``finalize`` replaces wholesale. 2.0 manages a
**real book** the User trades: one lot per (book, symbol) with real ``qty``, a weighted cost basis, and a
daily hold/add/trim/exit lifecycle recorded append-only (``position_actions``, the substrate for
position-management calibration, A9). Per decision 3 the engine records **fills** decision-agnostically —
whether morgan proposes and the User confirms, or the User reports a manual trade — but the **swarm never
places an order** (invariant 11; the User is the air-gap). No broker integration, ever.

Two layers, kept separate so the math is unit-testable without a database:
  * **pure** (``weighted_entry`` / ``apply_fill`` / ``exposure``) — same input → same output;
  * **store-integrating** (``record_fill`` / ``book_exposure`` / ``set_targets``) over A1's tables.
"""

from __future__ import annotations

from collections import defaultdict

from . import store


# --------------------------------------------------------------------------
# Pure cost-basis / exposure math (unit-tested; no I/O)
# --------------------------------------------------------------------------

def weighted_entry(prev_qty: float, prev_avg: float, add_qty: float, add_price: float) -> float:
    """Re-weighted average entry after adding ``add_qty`` @ ``add_price`` to an existing lot:
    ``(q0*a0 + q1*p)/(q0+q1)``. A fill into a flat lot is just the fill price."""
    total = prev_qty + add_qty
    if total <= 0:
        return add_price
    return (prev_qty * prev_avg + add_qty * add_price) / total


def apply_fill(pos: dict, side: str, qty: float, price: float) -> dict:
    """Apply one ``buy``/``sell`` fill to a lot's running state ``{qty, avg_entry}`` (MVP long-only).
    buy → open/add (avg re-weighted, no realized); sell → trim/exit (avg held, ``realized=(price-avg)*sold``).
    A sell **clamps** to the held qty (never goes negative). Returns
    ``{new_qty, new_avg, realized, action, filled_qty}`` with ``action ∈ {open, add, trim, exit}``."""
    cur_qty = float(pos.get("qty") or 0.0)
    cur_avg = float(pos.get("avg_entry") or 0.0)
    qty = abs(float(qty))
    price = float(price)
    if side == "buy":
        new_qty = cur_qty + qty
        return {"new_qty": new_qty, "new_avg": weighted_entry(cur_qty, cur_avg, qty, price),
                "realized": 0.0, "action": "add" if cur_qty > 0 else "open", "filled_qty": qty}
    if side == "sell":
        sold = min(qty, cur_qty)                       # clamp — never sell more than held
        new_qty = cur_qty - sold
        return {"new_qty": new_qty, "new_avg": cur_avg if new_qty > 0 else 0.0,
                "realized": (price - cur_avg) * sold,
                "action": "exit" if new_qty <= 0 else "trim", "filled_qty": sold}
    raise ValueError(f"unknown side: {side!r} (expected buy|sell)")


def exposure(positions: list[dict], price_lookup: dict, cash: float,
             sector_lookup: dict | None = None) -> dict:
    """Book exposure from open lots + a price map + cash (pure, MVP long-only). A symbol with no live
    price falls back to its ``avg_entry`` (cost). Returns ``{n, gross, net, cash, total, by_sector,
    weights}`` — ``weights`` is each name's market value as % of ``total`` (NAV = invested + cash)."""
    sector_lookup = sector_lookup or {}
    gross = net = 0.0
    by_sector: dict[str, float] = defaultdict(float)
    market_value: dict[str, float] = {}
    for p in positions:
        sym = p["symbol"]
        qty = float(p.get("qty") or 0.0)
        price = float(price_lookup.get(sym) or p.get("avg_entry") or 0.0)
        value = qty * price
        signed = value if p.get("direction", "long") == "long" else -value
        gross += abs(value)
        net += signed
        by_sector[sector_lookup.get(sym, "unknown")] += value
        market_value[sym] = value
    total = net + cash                                  # long-only: invested MV + cash ≈ NAV
    weights = {s: (round(v / total * 100, 2) if total else 0.0) for s, v in market_value.items()}
    return {"n": len(positions), "gross": round(gross, 2), "net": round(net, 2),
            "cash": round(cash, 2), "total": round(total, 2),
            "by_sector": {k: round(v, 2) for k, v in sorted(by_sector.items())},
            "weights": weights}


# --------------------------------------------------------------------------
# Store-integrating lifecycle ops (over A1's book_positions / position_actions)
# --------------------------------------------------------------------------

def _position_id(book: str, symbol: str) -> str:
    """One open lot per (book, symbol) — adds re-weight a single row (no per-tranche fragmentation;
    per-tranche lots are a possible future extension)."""
    return f"{book}:{symbol}"


def record_fill(book: str, symbol: str, side: str, qty: float, price: float, at: str, *,
                source: str = "morgan", rec_id: str | None = None, name: str | None = None,
                reason: str | None = None, regime: str | None = None,
                take_profit: float | None = None, stop_loss: float | None = None,
                fill_key: str | None = None) -> dict:
    """The decision-agnostic fill writer (decision 3): resolve the lot, apply the fill, upsert
    ``book_positions`` (closing it when qty hits 0), append the derived ``position_action``, and keep a
    running cash balance. **Idempotent** when ``fill_key`` is given — re-POSTing the same key is a no-op
    (protects against a double-confirm). Records a fill; **never places an order** (invariant 11).
    Returns ``{idempotent, position, action?, realized?}``."""
    from .config import settings
    book = book or settings.book_mode
    side = side.lower()
    position_id = _position_id(book, symbol)

    if fill_key:                                        # idempotency guard (double-confirm protection)
        marker = f"book_fill:{fill_key}"
        if store.kv_get(marker):
            return {"idempotent": True, "position": store.get_book_position(position_id),
                    "fill_key": fill_key}

    pos = store.get_book_position(position_id) or {"qty": 0.0, "avg_entry": 0.0, "direction": "long"}
    cur_qty = float(pos.get("qty") or 0.0)
    if side == "sell" and cur_qty <= 0:
        raise ValueError(f"no open lot to sell for {symbol} in book {book!r}")

    res = apply_fill(pos, side, qty, price)
    if side == "sell" and abs(float(qty)) > cur_qty:    # clamped — note it honestly in the action
        clamp = f"clamped sell {abs(float(qty)):g}->{res['filled_qty']:g} (held {cur_qty:g})"
        reason = f"{reason}; {clamp}" if reason else clamp

    is_open = res["action"] == "open"
    new_qty = res["new_qty"]
    saved = store.upsert_book_position({
        "position_id": position_id, "book": book, "symbol": symbol,
        "name": name or pos.get("name"), "direction": pos.get("direction", "long"),
        "qty": new_qty, "avg_entry": res["new_avg"],
        "opened_at": at if is_open else (pos.get("opened_at") or at),
        "status": "closed" if new_qty <= 0 else "open",
        "source": source if is_open else (pos.get("source") or source),
        "rec_id": rec_id if rec_id is not None else pos.get("rec_id"),
        "sizing_pct": pos.get("sizing_pct"),
        "take_profit": take_profit if take_profit is not None else pos.get("take_profit"),
        "stop_loss": stop_loss if stop_loss is not None else pos.get("stop_loss"),
    })
    action = store.add_position_action({
        "position_id": position_id, "symbol": symbol, "action_date": at, "action": res["action"],
        "prev_qty": cur_qty, "new_qty": new_qty,
        "delta_qty": res["filled_qty"] if side == "buy" else -res["filled_qty"],
        "reason": reason, "decided_by": source, "regime": regime,
    })

    # running cash ledger per book (decremented on buys, credited on sells) — honest exposure/sizing input
    cash_key = f"book_cash:{book}"
    cash = float(store.kv_get(cash_key) or settings.book_starting_cash)
    cash += (-res["filled_qty"] * float(price)) if side == "buy" else (res["filled_qty"] * float(price))
    store.kv_set(cash_key, repr(cash))

    if fill_key:
        store.kv_set(f"book_fill:{fill_key}", at or "1")
    return {"idempotent": False, "position": saved, "action": action,
            "realized": round(res["realized"], 4)}


def list_book(book: str = "paper", status: str | None = "open") -> list[dict]:
    """Open (or all, ``status=None``) lots for ``book``."""
    return store.list_book_positions(book=book, status=status)


def set_targets(position_id: str, take_profit: float | None = None,
                stop_loss: float | None = None) -> dict | None:
    """Update a lot's TP/SL (morgan's review output, A5). Returns the updated lot, or None if absent."""
    pos = store.get_book_position(position_id)
    if not pos:
        return None
    return store.upsert_book_position({
        **pos,
        "take_profit": take_profit if take_profit is not None else pos.get("take_profit"),
        "stop_loss": stop_loss if stop_loss is not None else pos.get("stop_loss"),
    })


def book_cash(book: str) -> float:
    from .config import settings
    return float(store.kv_get(f"book_cash:{book}") or settings.book_starting_cash)


def _sector_lookup() -> dict:
    """{symbol: sector} via FinMind (cached 7d); ``{}`` when unavailable (mirrors portfolio.risk_view)."""
    import pathlib

    from .config import settings
    from .ingest import finmind
    try:
        return finmind.fetch_stock_info(settings.finmind_token,
                                        str(pathlib.Path(settings.data_dir) / "cache"))
    except Exception:                                   # noqa: BLE001 — sectors are advisory, never fatal
        return {}


def _latest_prices() -> dict:
    """{symbol: close} from the latest PIT price snapshot (empty before any pipeline run)."""
    from . import snapshot
    from .config import settings
    as_of = store.kv_get("last_as_of")
    if not as_of:
        return {}
    return {r["symbol"]: r.get("close") for r in snapshot.read_snapshot(settings.data_dir, as_of)}


def book_exposure(book: str) -> dict:
    """Current exposure/cash/by-sector for ``book`` — assembles latest PIT prices + sectors + the cash
    ledger and runs the pure ``exposure``. data-engineer/risk-monitor read this (A4/GATE 2)."""
    positions = store.list_book_positions(book=book, status="open")
    return exposure(positions, _latest_prices(), book_cash(book), _sector_lookup())
