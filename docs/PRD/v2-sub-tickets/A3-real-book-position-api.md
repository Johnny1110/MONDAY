# A3 — Real book & position-lifecycle API (`/api/book`)

- **Epic**: A (engine foundations) · **Owner**: evva · **Size**: M
- **Status**: Proposed
- **Depends on**: A1 (book_positions / position_actions tables + CRUD)
- **Blocks**: A4 (sizing reads the book), A5 (review reads the book), A7 (report's holdings section), A9 (position-mgmt calibration reads actions)
- **PRD ref**: PRD-002 §倉位管理, §平台改動 (真實 book / 倉位管理), §"cross-cutting contracts"; decision 3 (book ingest); whitepaper §9, invariant 11 (no real money in the swarm)
- **Files**: new `engine/monday/book.py`, new `engine/monday/routers/book.py`, `engine/monday/app.py`, `engine/monday/manual.md`, new `engine/tests/test_book.py`

## Problem

1.0's `paper_positions` is a fixed-`qty=1` auto sim and `finalize` **replaces** the whole book each day. 2.0 manages a
**real book** the User trades: lots with real `qty`, weighted cost basis, and a daily **hold/add/trim/exit** lifecycle.
Per decision 3 the engine must record **fills** (whether morgan proposes & the User confirms, or the User reports manually) —
a decision-agnostic write path — while the **swarm still never places orders** (invariant 11; the User is the air-gap).

## Goal

A `book.py` + `/api/book` that is the source of truth for "what we hold, at what size", with an append-only action log,
weighted cost-basis math, and exposure/cash accounting — all token-free, decision-agnostic on how fills arrive.

## Scope (in)

- `book.py` — pure cost-basis/exposure math + store-integrating lifecycle ops over A1's tables.
- `routers/book.py` — list holdings, record a fill, read the action log, read exposure.
- Mount + `manual.md` + tests.

## Out of scope

- **Mark-to-market / realized-P&L calibration** of the book (A9 makes marking qty-aware; A3 logs raw actions only).
- **Sizing** suggestions (A4) and **review** decisions (A5) — A3 only *applies* fills they (or morgan/User) decide.
- Broker integration / order placement — **never** (invariant 11).

## Design

### `book.py`

Pure (unit-tested, no I/O):
```python
def weighted_entry(prev_qty, prev_avg, add_qty, add_price) -> float   # (q0*a0 + q1*p)/(q0+q1)
def apply_fill(pos, side, qty, price) -> dict   # → {new_qty, new_avg, realized, action}; side ∈ buy|sell
                                                # buy→open/add (avg re-weighted); sell→trim/exit (avg held, realized=(price-avg)*sold)
def exposure(positions, price_lookup, cash) -> dict   # {gross, net, cash, total, by_sector, weights}
```

Store-integrating:
```python
def record_fill(book, symbol, side, qty, price, at, *, source="morgan", rec_id=None,
                name=None, reason=None, regime=None, take_profit=None, stop_loss=None) -> dict:
    """Resolve the lot (position_id = f"{book}:{symbol}"), apply the fill via apply_fill, upsert
    book_positions (close when qty hits 0), and append a position_action (open|add|trim|exit) with
    prev/new qty + realized. Idempotency: caller may pass an explicit fill key; re-POSTing the same key
    is a no-op (guard via a kv marker or an action dedupe id)."""
def list_book(book="paper", status="open") -> list[dict]
def set_targets(position_id, take_profit=None, stop_loss=None) -> dict
```

- One **open lot per (book, symbol)** (position_id = `"{book}:{symbol}"`), so adds re-weight a single row rather than fragmenting. (If per-tranche lots are needed later, that's a future extension; document the choice.)
- `action` is derived: `buy` on a flat symbol → `open`; `buy` on an open lot → `add`; `sell` partial → `trim`; `sell` to zero → `exit`.

### `routers/book.py` (token-free)

- `GET /api/book?book=&status=&page=&page_size=` — holdings (paginated) + `summary` (n, gross/net exposure, cash, by_sector). Defaults to `book=settings.book_mode`.
- `POST /api/book/fill` — body `{book?, symbol, side, qty, price, at?, source?, rec_id?, reason?, take_profit?, stop_loss?, fill_key?}`. **The decision-agnostic write path** (decision 3). Validates required fields (422 otherwise); returns the updated position. `at` defaults to `last_as_of`.
- `POST /api/book/targets` — body `{book?, symbol, take_profit?, stop_loss?}` → update TP/SL (morgan's review output, A5).
- `GET /api/book/actions?since=&page=&page_size=` — the position-action log (paginated; A9 + the weekly review read it).
- `GET /api/book/exposure?book=` — current exposure/cash/by-sector (uses latest prices; reuse the reconcile price path or the latest feature `close`).

### Wiring

- `app.py`: add `book` to imports + `include_router`.
- Sector labels reuse `ingest/finmind.fetch_stock_info` (as `routers/portfolio.risk_view` does); `unknown` when unavailable.
- `manual.md`: new "## Book / positions" section; state clearly **the swarm proposes fills, the User confirms — the engine never places orders** (invariant 11).

## Acceptance criteria

- `POST /api/book/fill` buy on a flat symbol opens a lot; a second buy re-weights `avg_entry` correctly; a partial sell trims (avg unchanged, realized recorded); a sell-to-zero closes the lot — each appends the right `position_action`.
- Re-POSTing a fill with the same `fill_key` is a **no-op** (idempotent — protects against double-confirm).
- `GET /api/book` returns open holdings + a correct exposure summary; `book=` filters paper vs real.
- `GET /api/book/actions?since=` returns the lifecycle log filtered by date.
- All endpoints token-free; `book.py` pure math has no DB dependency.

## Test plan (`engine/tests/test_book.py`)

- `test_weighted_entry` / `test_apply_fill_*` — open/add (re-weight), trim (realized math), exit (close).
- `test_record_fill_lifecycle` — full open→add→trim→exit over the store; assert `book_positions` + `position_actions` end state.
- `test_fill_idempotent` — same `fill_key` twice → one action, unchanged qty.
- `test_exposure` — gross/net/by_sector/weights from a price lookup + cash.

## Invariant & discipline checklist

- [ ] **Invariant 11**: the endpoint records fills; nothing here (or anywhere in the swarm) places an order. Manual + docstrings say so.
- [ ] Token-free; one router module for `/api/book` (2,4).
- [ ] Pure cost-basis/exposure math separated from store ops + unit-tested (6).
- [ ] Lists paginated (3); transactional state in PG (5).

## Risks / edge cases

- **Double-confirm**: morgan proposes, User confirms twice → idempotency via `fill_key` is mandatory, not optional.
- **Sells exceeding holdings**: clamp to held qty + flag in the action `reason` (don't go negative).
- **Paper vs real**: keep `book` a first-class filter everywhere so D1's dry-run (paper) and the live book (real) never mix.
- **Splits/dividends on held names**: out of scope for A3; note as a known limitation (the daily reconcile uses split-adjusted prices from `clean.adjust_splits`, so MTM is consistent; cost-basis adjustment is a future ticket).

## Rollout notes

`book_mode="paper"` (A1 default) during dry-run; D1 flips to `real`. The 1.0 `paper_positions`/`finalize` path stays intact in parallel until D1 — A3 adds, doesn't replace.
