# A1 — Schema, store layer & data contracts

- **Epic**: A (engine foundations) · **Owner**: evva · **Size**: M
- **Status**: Proposed
- **Depends on**: — (foundation; first to build)
- **Blocks**: A3, A4, A5, A7, A9 (they consume these tables/contracts)
- **PRD ref**: PRD-002 §倉位管理, §平台改動, §"cross-cutting contracts"; whitepaper §6.1 / appendix B; ADR 0001 (Postgres)
- **Files**: `engine/monday/store.py`, `engine/monday/config.py`, `engine/tests/test_store.py`

## Problem

2.0 introduces three durable concepts the 1.0 store has no home for: (1) the **real managed book** (positions with
real `qty`/sizing/lifecycle, vs. the fixed-`qty=1` auto paper sim in `paper_positions`), (2) a **position-action log**
(hold/add/trim/exit decisions, for position-management calibration), and (3) **macro calls** + a **structured 6-section
daily report**. Spreading ad-hoc schema across feature tickets risks `store.py` churn and merge conflicts across sessions.
Land the schema + store API **once**, tested, so A3–A9 build against a stable surface.

## Goal

All new transactional tables, their `store.py` CRUD, the reset/JSON wiring, and config knobs — landed and unit-tested,
**without touching the behaviour of any existing table** (1.0 path stays green).

## Scope (in)

- New PG tables in `store._SCHEMA`: `book_positions`, `position_actions`, `macro_calls`, `daily_report`.
- `store._TABLES` (reset list) and `store._JSON_COLS` updated.
- CRUD functions for each table (mirroring existing function style + `_row` JSON-decode + upsert-on-conflict).
- `config.py` knobs the book/report consume.
- `engine/tests/test_store.py` cases for every new function.

## Out of scope

- Mark-to-market / P&L of the real book (A9 makes marking qty-aware).
- Any router or business logic (A3+ own that). This ticket is **storage only**.
- Touching `paper_positions` / `ledger_marks` / `outcomes` schema (the 1.0 paper sim is untouched here).

## Design

### Schema (append to `store._SCHEMA`; all `CREATE TABLE IF NOT EXISTS`, idempotent)

```sql
-- The 2.0 MANAGED BOOK: one row per held lot. Distinct from paper_positions (the 1.0 auto sim, qty=1),
-- so the autonomous pipeline keeps working until D1 cuts over. `book` separates the dry-run paper book
-- from the User's real book; `source` records who originated the lot; `rec_id` links to a model rec when one exists.
CREATE TABLE IF NOT EXISTS book_positions (
    position_id  TEXT PRIMARY KEY,            -- e.g. "<book>:<symbol>:<opened_at>" (caller-supplied, stable)
    book         TEXT NOT NULL DEFAULT 'paper',   -- paper | real
    symbol       TEXT NOT NULL,
    name         TEXT,
    direction    TEXT NOT NULL DEFAULT 'long',
    qty          DOUBLE PRECISION NOT NULL,       -- shares (or lots) actually held
    avg_entry    DOUBLE PRECISION NOT NULL,
    opened_at    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open',     -- open | closed
    source       TEXT NOT NULL DEFAULT 'morgan',   -- model | morgan | user
    rec_id       TEXT,                             -- FK-ish to recommendations.rec_id (nullable for user lots)
    sizing_pct   DOUBLE PRECISION,                 -- the % of book this lot was sized to (A4)
    take_profit  DOUBLE PRECISION,
    stop_loss    DOUBLE PRECISION,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_book_open ON book_positions (book, status, symbol);

-- Every lifecycle decision, append-only — the substrate for position-management calibration (§6, A9).
CREATE TABLE IF NOT EXISTS position_actions (
    action_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    position_id  TEXT,
    symbol       TEXT NOT NULL,
    action_date  TEXT NOT NULL,
    action       TEXT NOT NULL,                    -- open | hold | add | trim | exit
    prev_qty     DOUBLE PRECISION,
    delta_qty    DOUBLE PRECISION,
    new_qty      DOUBLE PRECISION,
    reason       TEXT,
    decided_by   TEXT NOT NULL DEFAULT 'morgan',
    regime       TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posaction_recent ON position_actions (action_date, position_id);

-- macro-analyst's daily top-down call, scored later for macro-call accuracy (A9, §倉位管理 校準擴充).
CREATE TABLE IF NOT EXISTS macro_calls (
    call_id              TEXT PRIMARY KEY,         -- e.g. "<call_date>" (one per round)
    call_date            TEXT NOT NULL,
    risk_state           TEXT,                     -- risk_on | neutral | risk_off
    horizon_days         INTEGER,
    sectors_favored      TEXT,                     -- JSON list
    sectors_avoid        TEXT,                     -- JSON list
    by                   TEXT DEFAULT 'macro-analyst',
    rationale            TEXT,
    realized_index_fwd_ret DOUBLE PRECISION,       -- filled in on settlement (A9)
    correct              INTEGER,                  -- 1/0/NULL, scored by A9
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_macro_call_date ON macro_calls (call_date);

-- The structured 6-section daily report (A7). `data` is the full JSON; `summary_text` is the rendered prose.
CREATE TABLE IF NOT EXISTS daily_report (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    as_of        TEXT NOT NULL,
    ts           TEXT NOT NULL,
    regime       TEXT,
    risk_state   TEXT,
    data         TEXT NOT NULL,                    -- JSON: {sections:{...}, disclaimer}
    summary_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_daily_report_asof ON daily_report (as_of DESC, id DESC);
```

### `store.py` wiring

- Add the four tables to `_TABLES` so `reset()` wipes them (test/dev slate). **Do not** add `pipeline_lock`-style seed rows.
- Add to `_JSON_COLS`: `sectors_favored`, `sectors_avoid`, `data` (so `_row` decodes them on read).
- New CRUD (match existing signatures/upsert style; `_enc` JSON fields; return via `_row`):
  - `upsert_book_position(pos: dict) -> dict`, `get_book_position(position_id) -> dict|None`,
    `list_book_positions(book: str|None=None, status: str|None=None) -> list[dict]`, `close_book_position(position_id) -> None`.
  - `add_position_action(a: dict) -> dict`, `list_position_actions(position_id: str|None=None, since: str|None=None) -> list[dict]`.
  - `add_macro_call(c: dict) -> dict`, `get_macro_call(call_id) -> dict|None`, `list_macro_calls(since: str|None=None) -> list[dict]`,
    `update_macro_call(call_id, **fields) -> dict|None` (for A9 settlement).
  - `add_daily_report(r: dict) -> dict`, `get_daily_report(as_of: str) -> dict|None` (latest for date), `list_daily_reports() -> list[dict]`.

### `config.py` knobs (used by A3/A4/A7)

```python
book_mode: str = "paper"              # paper | real — D1 flips to real after dry-run passes (decision 3)
book_starting_cash: float = 1_000_000.0   # NT$ notional for sizing/exposure math (decision 3)
book_max_position_pct: float = 20.0       # hard per-name cap as % of book (decision 3; risk gate reads it)
```

## Acceptance criteria

- `store.connect()` on a fresh DB creates all four tables; a **second** `connect()` is a no-op (idempotent — re-run safe).
- Each CRUD round-trips: insert → get → list (with filters) returns the written row; JSON list/object columns come back as Python `list`/`dict`, not strings.
- `reset()` returns counts including the four new tables and leaves them empty; existing tables still reset as before.
- Upserts are idempotent on their PK (re-insert overwrites, no duplicate).
- `list_*` ordering is deterministic (newest-first where dated).
- **No existing `test_store` case changes** (1.0 store behaviour preserved).

## Test plan (`engine/tests/test_store.py`, stdlib + a throwaway DB per the existing harness)

- `test_book_position_roundtrip` — upsert/get/list by book+status/close.
- `test_position_actions_log` — append several, `list_position_actions(since=)` filters by date.
- `test_macro_call_roundtrip_and_update` — add, list since, `update_macro_call` sets `correct`/`realized_index_fwd_ret`.
- `test_daily_report_roundtrip` — add + `get_daily_report(as_of)` returns latest, `data` decoded to dict.
- `test_reset_includes_new_tables` — populate all four, `reset()`, all empty.

## Invariant & discipline checklist

- [ ] Token-free: storage only, no endpoints (5).
- [ ] PG for transactional state; JSON-text columns for lists/objects, matching `_JSON_COLS` pattern (5).
- [ ] No heavy deps; pure `psycopg` like the rest of `store.py` (6).
- [ ] Additive only — existing tables/behaviour untouched (DoD backward-compat).

## Risks / edge cases

- **Don't reuse `paper_positions`**: keeping `book_positions` separate preserves the 1.0 autonomous path until D1 (backward compat).
- `position_id` must be **stable & caller-supplied** (so re-running a round upserts the same lot, not a duplicate) — document the convention `"<book>:<symbol>:<opened_at>"` and enforce in A3.
- `daily_report.data` can be large-ish JSON — fine for PG `TEXT`; do not put it in parquet (it is transactional/User-facing).

## Rollout notes

Pure additive migration — safe to deploy anytime; nothing reads these tables until A3+. Land early so Wave-2 tickets parallelize.
