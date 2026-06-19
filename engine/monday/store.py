"""Transactional durable state — PostgreSQL (engine-internal, creds engine-side).

The platform keeps its *transactional* state here: recommendations, the paper portfolio,
the calibration ledger (marks + outcomes), the model registry, calibration-run scorecards,
agent memory, the work journal, User reports, a small kv, and the single-flight pipeline lock.
Large analysis tables (PIT snapshots / prices / features) live in parquet (``parquetio``), not here.

Concurrency: a **psycopg connection pool** + PostgreSQL MVCC — each request/thread borrows its own
connection, and PG serializes writers at the row level. (This replaced a single shared sqlite
connection guarded by a global RLock + WAL/busy_timeout: the workaround that the 2026-06-15 run hit as
SQLITE_BUSY, B11.) ``connect(dsn)`` takes the DSN explicitly so the logic stays config-free and
unit-testable against a throwaway database. Every op runs inside one ``_cur()`` block = one transaction
(psycopg commits on clean exit, rolls back on exception); the one multi-statement atomic op
(``open_position``) keeps both statements in a single block.

The schema mirrors whitepaper appendix B (recommendations / ledger_marks / outcomes /
model_registry / calibration_runs) plus the paper-portfolio position table, the generic
memory/journal/report/kv tables, and the pipeline_lock lease.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None

_SCHEMA = """
-- Every idea, fully recorded AT BIRTH — without these columns it cannot be regressed
-- (whitepaper §6.1). List columns (factors/analysts) are JSON text.
CREATE TABLE IF NOT EXISTS recommendations (
    rec_id              TEXT PRIMARY KEY,
    as_of_date          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    name                TEXT,
    direction           TEXT NOT NULL DEFAULT 'long',
    entry_ref_price     DOUBLE PRECISION,
    predicted_return    DOUBLE PRECISION,
    predicted_prob_tp   DOUBLE PRECISION,
    conviction          DOUBLE PRECISION,
    model_version       TEXT,
    feature_snapshot_id TEXT,
    regime_label        TEXT,
    take_profit_price   DOUBLE PRECISION,
    stop_loss_price     DOUBLE PRECISION,
    holding_window_days INTEGER,
    contributing_factors  TEXT,   -- JSON list
    contributing_analysts TEXT,   -- JSON list
    rationale           TEXT,
    risk_notes          TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recs_date ON recommendations (as_of_date, symbol);

-- The paper portfolio: one live row per open idea (qty fixed at 1 = equal-weight in P0).
-- A position is "open" until its outcome is settled (TP/SL/timeout).
CREATE TABLE IF NOT EXISTS paper_positions (
    rec_id      TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    direction   TEXT NOT NULL DEFAULT 'long',
    entry_price DOUBLE PRECISION NOT NULL,
    entry_date  TEXT NOT NULL,
    qty         DOUBLE PRECISION NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'open'   -- open | closed
);
CREATE INDEX IF NOT EXISTS idx_pos_open ON paper_positions (status, symbol);

-- Daily mark-to-market, one row per idea per day (whitepaper §6.1).
CREATE TABLE IF NOT EXISTS ledger_marks (
    rec_id        TEXT NOT NULL,
    mark_date     TEXT NOT NULL,
    close_price   DOUBLE PRECISION,
    mtm_return    DOUBLE PRECISION,
    max_favorable DOUBLE PRECISION,
    max_adverse   DOUBLE PRECISION,
    tp_hit        INTEGER DEFAULT 0,
    sl_hit        INTEGER DEFAULT 0,
    days_held     INTEGER,
    PRIMARY KEY (rec_id, mark_date)
);

-- Settlement at exit (touched TP/SL or held the full window).
CREATE TABLE IF NOT EXISTS outcomes (
    rec_id          TEXT PRIMARY KEY,
    exit_date       TEXT,
    exit_price      DOUBLE PRECISION,
    realized_return DOUBLE PRECISION,
    hit             INTEGER,   -- realized_return > 0
    tp_hit          INTEGER,
    sl_hit          INTEGER,
    exit_reason     TEXT,      -- tp | sl | timeout
    error           DOUBLE PRECISION  -- realized_return - predicted_return
);

CREATE TABLE IF NOT EXISTS model_registry (
    model_version TEXT PRIMARY KEY,
    trained_at    TEXT,
    train_window  TEXT,
    cv_ic         DOUBLE PRECISION,
    factor_set    TEXT,        -- JSON list
    regime_weights TEXT,       -- JSON object
    notes         TEXT
);

-- One scorecard snapshot per review run (whitepaper §6.1/§6.2).
CREATE TABLE IF NOT EXISTS calibration_runs (
    run_id         TEXT PRIMARY KEY,
    run_date       TEXT,
    "window"       TEXT,             -- quoted: `window` is a reserved keyword in PostgreSQL
    hit_rate       DOUBLE PRECISION,
    tp_hit_rate    DOUBLE PRECISION,
    avg_win        DOUBLE PRECISION,
    avg_loss       DOUBLE PRECISION,
    ic             DOUBLE PRECISION,
    excess_vs_taiex DOUBLE PRECISION,
    attribution    TEXT,       -- JSON
    adjustments    TEXT        -- JSON (ADR-linked)
);

-- Two-board memory (whitepaper §6.5): morgan's constitution + researcher journals.
CREATE TABLE IF NOT EXISTS memory (
    agent      TEXT PRIMARY KEY,
    content    TEXT NOT NULL DEFAULT '',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS journal (
    id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts     TEXT NOT NULL,
    date   TEXT,
    author TEXT NOT NULL DEFAULT 'reviewer-calibrator',
    title  TEXT,
    body   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_recent ON journal (id DESC);

CREATE TABLE IF NOT EXISTS report (
    id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts    TEXT NOT NULL,
    kind  TEXT NOT NULL DEFAULT 'info',   -- info | recommendation | review | alert
    title TEXT,
    body  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_recent ON report (id DESC);

CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT
);

-- The 2.0 MANAGED BOOK (A1): one row per held lot, qty-aware. Distinct from paper_positions (the 1.0
-- auto sim, qty=1), so the autonomous pipeline keeps working until D1 cuts over. "book" separates the
-- dry-run paper book from the User's real book, "source" records who originated the lot, "rec_id" links
-- to a model rec when one exists. The swarm never places orders (invariant 11) -- fills land here only
-- on the User's confirmation.
CREATE TABLE IF NOT EXISTS book_positions (
    position_id  TEXT PRIMARY KEY,            -- "<book>:<symbol>:<opened_at>" (caller-supplied, stable)
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
    call_id              TEXT PRIMARY KEY,         -- "<call_date>" (one per round)
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

-- The structured 6-section daily report (A7). "data" is the full JSON, "summary_text" the rendered prose.
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

-- Single-flight pipeline mutex (B11): one row, taken via an atomic conditional UPDATE so the lock
-- holds ACROSS processes (the HTTP server and a CLI run are separate OS processes). A stale heartbeat
-- reclaims a crashed run. NOT in _TABLES so reset() never wipes the seed row.
CREATE TABLE IF NOT EXISTS pipeline_lock (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    task_id      TEXT,
    holder       TEXT,
    started_at   TEXT,
    heartbeat_at TEXT
);
INSERT INTO pipeline_lock (id, task_id) VALUES (1, NULL) ON CONFLICT (id) DO NOTHING;
"""

_TABLES = ("recommendations", "paper_positions", "ledger_marks", "outcomes",
           "model_registry", "calibration_runs", "memory", "journal", "report", "kv",
           "book_positions", "position_actions", "macro_calls", "daily_report")

# Columns that carry JSON-encoded lists/objects (decoded on read).
_JSON_COLS = {"contributing_factors", "contributing_analysts", "factor_set",
              "regime_weights", "attribution", "adjustments",
              "sectors_favored", "sectors_avoid", "data"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enc(v) -> str | None:
    return None if v is None else json.dumps(v, ensure_ascii=False)


def _row(row: dict | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for c in _JSON_COLS:
        if c in d and isinstance(d[c], str):
            try:
                d[c] = json.loads(d[c])
            except (ValueError, TypeError):
                pass
    return d


def connect(dsn: str, min_size: int = 1, max_size: int = 10) -> None:
    """Open the connection pool to ``dsn`` and create the schema (idempotent). ``dsn`` is a libpq URI
    (postgresql://user:pw@host:port/db) — engine-side only, never exposed to agents."""
    global _pool
    if _pool is not None:                  # idempotent: close a prior pool before replacing it
        _pool.close()
    _pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size,
                           kwargs={"row_factory": dict_row}, open=True)
    _pool.wait(timeout=10)                 # fail fast on a bad DSN (like sqlite's connect-time failure)
    _create_schema()


def _create_schema() -> None:
    with _cur() as cur:
        for stmt in (s.strip() for s in _SCHEMA.split(";")):
            if stmt:
                cur.execute(stmt)
        _migrate(cur)


def _migrate(cur) -> None:
    """Idempotent, additive-only migrations (CREATE TABLE IF NOT EXISTS can't add a column to a
    pre-existing table). Safe to run on every connect."""
    # B9/B13 — which immutable signals snapshot a rec was built from.
    cur.execute("ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS signals_version TEXT")


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def _cur():
    """Borrow a pooled connection + cursor for one transaction (commit on clean exit, rollback on
    error). Multi-statement atomic ops put all statements in a single ``with _cur()`` block."""
    if _pool is None:
        raise RuntimeError("store not connected — call connect() first")
    with _pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur


def reset() -> dict[str, int]:
    """Wipe ALL durable state (schema preserved) — a clean test/dev slate. Table names are fixed
    constants, so the f-string is not an injection surface. pipeline_lock is excluded (its seed row
    must survive)."""
    counts: dict[str, int] = {}
    with _cur() as cur:
        for t in _TABLES:
            cur.execute(f"DELETE FROM {t}")
            counts[t] = cur.rowcount
    return counts


# --------------------------------------------------------------------------
# kv
# --------------------------------------------------------------------------

def kv_get(k: str, default: str | None = None) -> str | None:
    with _cur() as cur:
        row = cur.execute("SELECT v FROM kv WHERE k = %s", (k,)).fetchone()
        return row["v"] if row else default


def kv_set(k: str, v: str) -> None:
    with _cur() as cur:
        cur.execute("INSERT INTO kv (k, v) VALUES (%s, %s) "
                    "ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v", (k, v))


# --------------------------------------------------------------------------
# Single-flight pipeline lock (B11) — cross-process via one atomic UPDATE
# --------------------------------------------------------------------------

def acquire_pipeline_lock(task_id: str, holder: str = "", stale_seconds: int = 1800) -> bool:
    """Take the single pipeline slot. Succeeds only if it's free OR the current holder's heartbeat is
    older than ``stale_seconds`` (a crashed run is reclaimed). One conditional UPDATE → atomic across
    processes (PG row lock). Returns True iff acquired."""
    now = _now()
    stale_before = (datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)).isoformat()
    with _cur() as cur:
        cur.execute(
            "UPDATE pipeline_lock SET task_id=%s, holder=%s, started_at=%s, heartbeat_at=%s "
            "WHERE id=1 AND (task_id IS NULL OR heartbeat_at < %s)",
            (task_id, holder, now, now, stale_before))
        return cur.rowcount == 1


def heartbeat_pipeline_lock(task_id: str) -> None:
    """Refresh the holder's heartbeat so a long (legitimate) run isn't reclaimed as stale."""
    with _cur() as cur:
        cur.execute("UPDATE pipeline_lock SET heartbeat_at=%s WHERE task_id=%s", (_now(), task_id))


def release_pipeline_lock(task_id: str) -> None:
    """Free the slot — only if ``task_id`` still owns it (never steals another run's lock)."""
    with _cur() as cur:
        cur.execute(
            "UPDATE pipeline_lock SET task_id=NULL, holder=NULL, started_at=NULL, heartbeat_at=NULL "
            "WHERE task_id=%s", (task_id,))


def pipeline_lock_holder() -> dict | None:
    """The current holder row ({task_id, holder, started_at, heartbeat_at}), or None if free."""
    with _cur() as cur:
        row = cur.execute(
            "SELECT task_id, holder, started_at, heartbeat_at FROM pipeline_lock "
            "WHERE id=1 AND task_id IS NOT NULL").fetchone()
        return dict(row) if row else None


# --------------------------------------------------------------------------
# Recommendations (whitepaper §6.1 — recorded at birth)
# --------------------------------------------------------------------------

_REC_FIELDS = ("rec_id", "as_of_date", "symbol", "name", "direction", "entry_ref_price",
               "predicted_return", "predicted_prob_tp", "conviction", "model_version",
               "feature_snapshot_id", "regime_label", "take_profit_price", "stop_loss_price",
               "holding_window_days", "contributing_factors", "contributing_analysts",
               "rationale", "risk_notes", "signals_version")


def add_recommendation(rec: dict) -> dict:
    """Insert one recommendation (upsert on rec_id). JSON-list fields are encoded."""
    cols = (*_REC_FIELDS, "created_at")
    vals = [_enc(rec.get(f)) if f in _JSON_COLS else rec.get(f) for f in _REC_FIELDS]
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "rec_id")
    with _cur() as cur:
        cur.execute(
            f"INSERT INTO recommendations ({','.join(cols)}) "
            f"VALUES ({','.join(['%s'] * len(cols))}) "
            f"ON CONFLICT (rec_id) DO UPDATE SET {updates}", (*vals, _now()))
    return get_recommendation(rec["rec_id"])


def get_recommendation(rec_id: str) -> dict | None:
    with _cur() as cur:
        return _row(cur.execute(
            "SELECT * FROM recommendations WHERE rec_id = %s", (rec_id,)).fetchone())


def list_recommendations(as_of_date: str | None = None) -> list[dict]:
    with _cur() as cur:
        if as_of_date:
            rows = cur.execute("SELECT * FROM recommendations WHERE as_of_date = %s "
                               "ORDER BY conviction DESC", (as_of_date,)).fetchall()
        else:
            rows = cur.execute("SELECT * FROM recommendations "
                               "ORDER BY as_of_date DESC, conviction DESC").fetchall()
        return [_row(r) for r in rows]


# --------------------------------------------------------------------------
# Paper portfolio (positions)
# --------------------------------------------------------------------------

def open_position(rec_id: str, symbol: str, direction: str, entry_price: float,
                  entry_date: str, qty: float = 1.0) -> dict:
    with _cur() as cur:
        cur.execute(
            "INSERT INTO paper_positions "
            "(rec_id, symbol, direction, entry_price, entry_date, qty, status) "
            "VALUES (%s,%s,%s,%s,%s,%s, 'open') "
            "ON CONFLICT (rec_id) DO UPDATE SET symbol=EXCLUDED.symbol, direction=EXCLUDED.direction, "
            "entry_price=EXCLUDED.entry_price, entry_date=EXCLUDED.entry_date, qty=EXCLUDED.qty, "
            "status='open'",
            (rec_id, symbol, direction, entry_price, entry_date, qty))
        # Re-opening voids any prior settlement (keeps a re-run idempotent: a rec is never both
        # 'open' and settled). Same transaction as the upsert.
        cur.execute("DELETE FROM outcomes WHERE rec_id = %s", (rec_id,))
    return get_position(rec_id)


def get_position(rec_id: str) -> dict | None:
    with _cur() as cur:
        return _row(cur.execute(
            "SELECT * FROM paper_positions WHERE rec_id = %s", (rec_id,)).fetchone())


def list_positions(status: str | None = None) -> list[dict]:
    with _cur() as cur:
        if status:
            rows = cur.execute("SELECT * FROM paper_positions WHERE status = %s "
                               "ORDER BY entry_date DESC", (status,)).fetchall()
        else:
            rows = cur.execute("SELECT * FROM paper_positions "
                               "ORDER BY entry_date DESC").fetchall()
        return [_row(r) for r in rows]


def close_position(rec_id: str) -> None:
    with _cur() as cur:
        cur.execute("UPDATE paper_positions SET status='closed' WHERE rec_id = %s", (rec_id,))


# --------------------------------------------------------------------------
# Ledger marks (daily mark-to-market) + outcomes (settlement)
# --------------------------------------------------------------------------

def add_mark(mark: dict) -> None:
    """Upsert one daily mark (PK rec_id+mark_date) — re-marking a day overwrites it."""
    with _cur() as cur:
        cur.execute(
            "INSERT INTO ledger_marks "
            "(rec_id, mark_date, close_price, mtm_return, max_favorable, max_adverse, "
            " tp_hit, sl_hit, days_held) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (rec_id, mark_date) DO UPDATE SET close_price=EXCLUDED.close_price, "
            "mtm_return=EXCLUDED.mtm_return, max_favorable=EXCLUDED.max_favorable, "
            "max_adverse=EXCLUDED.max_adverse, tp_hit=EXCLUDED.tp_hit, sl_hit=EXCLUDED.sl_hit, "
            "days_held=EXCLUDED.days_held",
            (mark["rec_id"], mark["mark_date"], mark.get("close_price"), mark.get("mtm_return"),
             mark.get("max_favorable"), mark.get("max_adverse"),
             1 if mark.get("tp_hit") else 0, 1 if mark.get("sl_hit") else 0,
             mark.get("days_held")))


def marks_for(rec_id: str) -> list[dict]:
    with _cur() as cur:
        rows = cur.execute("SELECT * FROM ledger_marks WHERE rec_id = %s "
                           "ORDER BY mark_date", (rec_id,)).fetchall()
        return [dict(r) for r in rows]


def list_marks(mark_date: str | None = None) -> list[dict]:
    with _cur() as cur:
        if mark_date:
            rows = cur.execute("SELECT * FROM ledger_marks WHERE mark_date = %s "
                               "ORDER BY rec_id", (mark_date,)).fetchall()
        else:
            rows = cur.execute("SELECT * FROM ledger_marks "
                               "ORDER BY mark_date DESC, rec_id").fetchall()
        return [dict(r) for r in rows]


def add_outcome(outcome: dict) -> None:
    with _cur() as cur:
        cur.execute(
            "INSERT INTO outcomes "
            "(rec_id, exit_date, exit_price, realized_return, hit, tp_hit, sl_hit, "
            " exit_reason, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (rec_id) DO UPDATE SET exit_date=EXCLUDED.exit_date, "
            "exit_price=EXCLUDED.exit_price, realized_return=EXCLUDED.realized_return, "
            "hit=EXCLUDED.hit, tp_hit=EXCLUDED.tp_hit, sl_hit=EXCLUDED.sl_hit, "
            "exit_reason=EXCLUDED.exit_reason, error=EXCLUDED.error",
            (outcome["rec_id"], outcome.get("exit_date"), outcome.get("exit_price"),
             outcome.get("realized_return"), 1 if outcome.get("hit") else 0,
             1 if outcome.get("tp_hit") else 0, 1 if outcome.get("sl_hit") else 0,
             outcome.get("exit_reason"), outcome.get("error")))


def get_outcome(rec_id: str) -> dict | None:
    with _cur() as cur:
        return _row(cur.execute("SELECT * FROM outcomes WHERE rec_id = %s", (rec_id,)).fetchone())


def list_outcomes() -> list[dict]:
    with _cur() as cur:
        rows = cur.execute("SELECT * FROM outcomes ORDER BY exit_date DESC").fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Model registry
# --------------------------------------------------------------------------

def register_model(model_version: str, train_window: str = "", cv_ic: float | None = None,
                   factor_set: list | None = None, regime_weights: dict | None = None,
                   notes: str = "") -> dict:
    with _cur() as cur:
        cur.execute(
            "INSERT INTO model_registry "
            "(model_version, trained_at, train_window, cv_ic, factor_set, regime_weights, notes) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (model_version) DO UPDATE SET trained_at=EXCLUDED.trained_at, "
            "train_window=EXCLUDED.train_window, cv_ic=EXCLUDED.cv_ic, factor_set=EXCLUDED.factor_set, "
            "regime_weights=EXCLUDED.regime_weights, notes=EXCLUDED.notes",
            (model_version, _now(), train_window, cv_ic, _enc(factor_set or []),
             _enc(regime_weights or {}), notes))
    return get_model(model_version)


def get_model(model_version: str) -> dict | None:
    with _cur() as cur:
        return _row(cur.execute(
            "SELECT * FROM model_registry WHERE model_version = %s", (model_version,)).fetchone())


def list_models() -> list[dict]:
    with _cur() as cur:
        rows = cur.execute("SELECT * FROM model_registry ORDER BY trained_at DESC").fetchall()
        return [_row(r) for r in rows]


def latest_model() -> dict | None:
    models = list_models()
    return models[0] if models else None


# --------------------------------------------------------------------------
# Calibration runs (scorecards)
# --------------------------------------------------------------------------

def add_calibration_run(run: dict) -> dict:
    with _cur() as cur:
        cur.execute(
            "INSERT INTO calibration_runs "
            '(run_id, run_date, "window", hit_rate, tp_hit_rate, avg_win, avg_loss, ic, '
            " excess_vs_taiex, attribution, adjustments) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            'ON CONFLICT (run_id) DO UPDATE SET run_date=EXCLUDED.run_date, "window"=EXCLUDED."window", '
            "hit_rate=EXCLUDED.hit_rate, tp_hit_rate=EXCLUDED.tp_hit_rate, avg_win=EXCLUDED.avg_win, "
            "avg_loss=EXCLUDED.avg_loss, ic=EXCLUDED.ic, excess_vs_taiex=EXCLUDED.excess_vs_taiex, "
            "attribution=EXCLUDED.attribution, adjustments=EXCLUDED.adjustments",
            (run["run_id"], run.get("run_date"), run.get("window"), run.get("hit_rate"),
             run.get("tp_hit_rate"), run.get("avg_win"), run.get("avg_loss"), run.get("ic"),
             run.get("excess_vs_taiex"), _enc(run.get("attribution")),
             _enc(run.get("adjustments"))))
        return _row(cur.execute(
            "SELECT * FROM calibration_runs WHERE run_id = %s", (run["run_id"],)).fetchone())


def list_calibration_runs() -> list[dict]:
    with _cur() as cur:
        rows = cur.execute("SELECT * FROM calibration_runs ORDER BY run_date DESC").fetchall()
        return [_row(r) for r in rows]


# --------------------------------------------------------------------------
# Memory / journal / reports (generic, carried from Sunday)
# --------------------------------------------------------------------------

def get_memory(agent: str) -> dict | None:
    with _cur() as cur:
        return _row(cur.execute(
            "SELECT agent, content, updated_at FROM memory WHERE agent = %s", (agent,)).fetchone())


def set_memory(agent: str, content: str) -> dict:
    ts = _now()
    with _cur() as cur:
        cur.execute(
            "INSERT INTO memory (agent, content, updated_at) VALUES (%s,%s,%s) "
            "ON CONFLICT (agent) DO UPDATE SET content=EXCLUDED.content, updated_at=EXCLUDED.updated_at",
            (agent, content, ts))
    return {"agent": agent, "content": content, "updated_at": ts}


def list_memory() -> list[dict]:
    with _cur() as cur:
        rows = cur.execute("SELECT agent, content, updated_at FROM memory").fetchall()
        return [dict(r) for r in rows]


def add_journal(body: str, title: str | None = None, date: str | None = None,
                author: str = "reviewer-calibrator") -> dict:
    with _cur() as cur:
        return dict(cur.execute(
            "INSERT INTO journal (ts, date, author, title, body) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (_now(), date or _now()[:10], author, title, body)).fetchone())


def list_journal(author: str | None = None, since: str | None = None) -> list[dict]:
    # since = inclusive YYYY-MM-DD lower bound on the journal date (the weekly review reads a window).
    clauses, params = [], []
    if author:
        clauses.append("author = %s"); params.append(author)
    if since:
        clauses.append("date >= %s"); params.append(since)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _cur() as cur:
        rows = cur.execute(
            f"SELECT * FROM journal{where} ORDER BY id DESC", params).fetchall()
        return [dict(r) for r in rows]


def add_report(title: str, body: str, kind: str = "info") -> dict:
    with _cur() as cur:
        return dict(cur.execute(
            "INSERT INTO report (ts, kind, title, body) VALUES (%s,%s,%s,%s) RETURNING *",
            (_now(), kind, title, body)).fetchone())


def list_reports(kind: str | None = None) -> list[dict]:
    with _cur() as cur:
        if kind:
            rows = cur.execute("SELECT * FROM report WHERE kind = %s ORDER BY id DESC",
                               (kind,)).fetchall()
        else:
            rows = cur.execute("SELECT * FROM report ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# 2.0 managed book (A1) — qty-aware real/paper lots, distinct from the 1.0
# paper_positions auto-sim. The autonomous pipeline keeps using paper_positions
# until D1 cuts over (backward compat). The swarm never places orders
# (invariant 11); fills land here only on the User's confirmation (A3).
# --------------------------------------------------------------------------

_BOOK_FIELDS = ("position_id", "book", "symbol", "name", "direction", "qty", "avg_entry",
                "opened_at", "status", "source", "rec_id", "sizing_pct",
                "take_profit", "stop_loss")


def upsert_book_position(pos: dict) -> dict:
    """Insert/replace one held lot (upsert on position_id). ``position_id`` is caller-supplied and
    stable (convention ``"<book>:<symbol>:<opened_at>"``) so re-running a round updates the same lot
    rather than duplicating it. The NOT-NULL-with-default columns (book/direction/status/source) fall
    back to the schema defaults when omitted."""
    p = {**pos}
    p.setdefault("book", "paper")
    p.setdefault("direction", "long")
    p.setdefault("status", "open")
    p.setdefault("source", "morgan")
    cols = (*_BOOK_FIELDS, "updated_at")
    vals = [p.get(f) for f in _BOOK_FIELDS]
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "position_id")
    with _cur() as cur:
        cur.execute(
            f"INSERT INTO book_positions ({','.join(cols)}) "
            f"VALUES ({','.join(['%s'] * len(cols))}) "
            f"ON CONFLICT (position_id) DO UPDATE SET {updates}", (*vals, _now()))
    return get_book_position(p["position_id"])


def get_book_position(position_id: str) -> dict | None:
    with _cur() as cur:
        return _row(cur.execute(
            "SELECT * FROM book_positions WHERE position_id = %s", (position_id,)).fetchone())


def list_book_positions(book: str | None = None, status: str | None = None) -> list[dict]:
    clauses, params = [], []
    if book:
        clauses.append("book = %s"); params.append(book)
    if status:
        clauses.append("status = %s"); params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _cur() as cur:
        rows = cur.execute(
            f"SELECT * FROM book_positions{where} ORDER BY opened_at DESC, symbol", params).fetchall()
        return [_row(r) for r in rows]


def close_book_position(position_id: str) -> None:
    with _cur() as cur:
        cur.execute("UPDATE book_positions SET status='closed', updated_at=%s "
                    "WHERE position_id = %s", (_now(), position_id))


# --------------------------------------------------------------------------
# Position-action log (A1) — append-only hold/add/trim/exit decisions (A5/A9)
# --------------------------------------------------------------------------

_POSACTION_FIELDS = ("position_id", "symbol", "action_date", "action", "prev_qty",
                     "delta_qty", "new_qty", "reason", "decided_by", "regime")


def add_position_action(a: dict) -> dict:
    """Append one lifecycle decision (action_id is DB-assigned). ``decided_by`` defaults to morgan."""
    rec = {**a, "decided_by": a.get("decided_by") or "morgan"}
    cols = (*_POSACTION_FIELDS, "created_at")
    vals = [rec.get(f) for f in _POSACTION_FIELDS]
    with _cur() as cur:
        row = cur.execute(
            f"INSERT INTO position_actions ({','.join(cols)}) "
            f"VALUES ({','.join(['%s'] * len(cols))}) RETURNING *", (*vals, _now())).fetchone()
    return _row(row)


def list_position_actions(position_id: str | None = None, since: str | None = None) -> list[dict]:
    # since = inclusive YYYY-MM-DD lower bound on action_date (the calibration read uses a window).
    clauses, params = [], []
    if position_id:
        clauses.append("position_id = %s"); params.append(position_id)
    if since:
        clauses.append("action_date >= %s"); params.append(since)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _cur() as cur:
        rows = cur.execute(
            f"SELECT * FROM position_actions{where} ORDER BY action_date DESC, action_id DESC",
            params).fetchall()
        return [_row(r) for r in rows]


# --------------------------------------------------------------------------
# Macro calls (A1) — macro-analyst's daily top-down call, scored by A9
# --------------------------------------------------------------------------

_MACRO_CALL_FIELDS = ("call_id", "call_date", "risk_state", "horizon_days", "sectors_favored",
                      "sectors_avoid", "by", "rationale", "realized_index_fwd_ret", "correct")


def add_macro_call(c: dict) -> dict:
    """Insert one macro call (upsert on call_id — one per round). ``by`` defaults to macro-analyst;
    sectors_favored/avoid are JSON-encoded."""
    rec = {**c, "by": c.get("by") or "macro-analyst"}
    cols = (*_MACRO_CALL_FIELDS, "created_at")
    vals = [_enc(rec.get(f)) if f in _JSON_COLS else rec.get(f) for f in _MACRO_CALL_FIELDS]
    updates = ", ".join(f"{col}=EXCLUDED.{col}" for col in cols if col != "call_id")
    with _cur() as cur:
        cur.execute(
            f"INSERT INTO macro_calls ({','.join(cols)}) "
            f"VALUES ({','.join(['%s'] * len(cols))}) "
            f"ON CONFLICT (call_id) DO UPDATE SET {updates}", (*vals, _now()))
    return get_macro_call(rec["call_id"])


def get_macro_call(call_id: str) -> dict | None:
    with _cur() as cur:
        return _row(cur.execute(
            "SELECT * FROM macro_calls WHERE call_id = %s", (call_id,)).fetchone())


def list_macro_calls(since: str | None = None) -> list[dict]:
    with _cur() as cur:
        if since:
            rows = cur.execute("SELECT * FROM macro_calls WHERE call_date >= %s "
                               "ORDER BY call_date DESC, call_id DESC", (since,)).fetchall()
        else:
            rows = cur.execute("SELECT * FROM macro_calls "
                               "ORDER BY call_date DESC, call_id DESC").fetchall()
        return [_row(r) for r in rows]


def update_macro_call(call_id: str, **fields) -> dict | None:
    """Patch selected columns (A9 settlement: realized_index_fwd_ret / correct). Only known columns are
    applied (the whitelist is the fixed field tuple, so callers can't inject column names); JSON fields
    are encoded. No-op patch returns the current row."""
    allowed = {f for f in _MACRO_CALL_FIELDS if f != "call_id"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = %s")
        params.append(_enc(v) if k in _JSON_COLS else v)
    if not sets:
        return get_macro_call(call_id)
    params.append(call_id)
    with _cur() as cur:
        cur.execute(f"UPDATE macro_calls SET {', '.join(sets)} WHERE call_id = %s", params)
    return get_macro_call(call_id)


# --------------------------------------------------------------------------
# Daily report v2 (A1) — the structured 6-section User report (A7)
# --------------------------------------------------------------------------

def add_daily_report(r: dict) -> dict:
    """Append one structured daily report (id is DB-assigned; re-posting a date keeps both, latest wins
    on read). ``data`` is the full JSON contract ({sections, disclaimer})."""
    with _cur() as cur:
        row = cur.execute(
            "INSERT INTO daily_report (as_of, ts, regime, risk_state, data, summary_text) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
            (r["as_of"], r.get("ts") or _now(), r.get("regime"), r.get("risk_state"),
             _enc(r.get("data") or {}), r.get("summary_text"))).fetchone()
    return _row(row)


def get_daily_report(as_of: str) -> dict | None:
    """The latest report for a date (newest id wins if several were posted that day)."""
    with _cur() as cur:
        return _row(cur.execute(
            "SELECT * FROM daily_report WHERE as_of = %s ORDER BY id DESC LIMIT 1",
            (as_of,)).fetchone())


def list_daily_reports() -> list[dict]:
    with _cur() as cur:
        rows = cur.execute(
            "SELECT * FROM daily_report ORDER BY as_of DESC, id DESC").fetchall()
        return [_row(r) for r in rows]
