"""Transactional durable state — a single SQLite file (invariant 5).

The platform keeps its *transactional* state here: recommendations, the paper portfolio,
the calibration ledger (marks + outcomes), the model registry, calibration-run scorecards,
agent memory, the work journal, User reports, and a small kv. Large analysis tables (PIT
snapshots / prices / features) live in parquet (``parquetio``), not here.

Concurrency (load-bearing, copied from Sunday's proven pattern): FastAPI serves sync
endpoints from a threadpool, so the one connection is shared across threads
(``check_same_thread=False``). A single SQLite connection is NOT safe for concurrent use and
concurrent writers deadlock, so **every** access — reads included — is serialized through one
**reentrant** write mutex ``_LOCK`` (a write helper re-reads via a getter while still holding
the lock; a plain Lock would self-deadlock). WAL + ``busy_timeout`` are the second line of
defence. ``connect(path)`` takes the path explicitly so the logic stays unit-testable against
``:memory:`` (no config import).

The schema mirrors whitepaper appendix B (recommendations / ledger_marks / outcomes /
model_registry / calibration_runs) plus the paper-portfolio position table and the generic
memory/journal/report/kv tables carried over from Sunday.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

_conn: sqlite3.Connection | None = None
_LOCK = threading.RLock()  # reentrant write mutex — serializes ALL connection access

_SCHEMA = """
-- Every idea, fully recorded AT BIRTH — without these columns it cannot be regressed
-- (whitepaper §6.1). List columns (factors/analysts) are JSON text.
CREATE TABLE IF NOT EXISTS recommendations (
    rec_id              TEXT PRIMARY KEY,
    as_of_date          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    name                TEXT,
    direction           TEXT NOT NULL DEFAULT 'long',
    entry_ref_price     REAL,
    predicted_return    REAL,
    predicted_prob_tp   REAL,
    conviction          REAL,
    model_version       TEXT,
    feature_snapshot_id TEXT,
    regime_label        TEXT,
    take_profit_price   REAL,
    stop_loss_price     REAL,
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
    entry_price REAL NOT NULL,
    entry_date  TEXT NOT NULL,
    qty         REAL NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'open'   -- open | closed
);
CREATE INDEX IF NOT EXISTS idx_pos_open ON paper_positions (status, symbol);

-- Daily mark-to-market, one row per idea per day (whitepaper §6.1).
CREATE TABLE IF NOT EXISTS ledger_marks (
    rec_id        TEXT NOT NULL,
    mark_date     TEXT NOT NULL,
    close_price   REAL,
    mtm_return    REAL,
    max_favorable REAL,
    max_adverse   REAL,
    tp_hit        INTEGER DEFAULT 0,
    sl_hit        INTEGER DEFAULT 0,
    days_held     INTEGER,
    PRIMARY KEY (rec_id, mark_date)
);

-- Settlement at exit (touched TP/SL or held the full window).
CREATE TABLE IF NOT EXISTS outcomes (
    rec_id          TEXT PRIMARY KEY,
    exit_date       TEXT,
    exit_price      REAL,
    realized_return REAL,
    hit             INTEGER,   -- realized_return > 0
    tp_hit          INTEGER,
    sl_hit          INTEGER,
    exit_reason     TEXT,      -- tp | sl | timeout
    error           REAL       -- realized_return - predicted_return
);

CREATE TABLE IF NOT EXISTS model_registry (
    model_version TEXT PRIMARY KEY,
    trained_at    TEXT,
    train_window  TEXT,
    cv_ic         REAL,
    factor_set    TEXT,        -- JSON list
    regime_weights TEXT,       -- JSON object
    notes         TEXT
);

-- One scorecard snapshot per review run (whitepaper §6.1/§6.2).
CREATE TABLE IF NOT EXISTS calibration_runs (
    run_id         TEXT PRIMARY KEY,
    run_date       TEXT,
    window         TEXT,
    hit_rate       REAL,
    tp_hit_rate    REAL,
    avg_win        REAL,
    avg_loss       REAL,
    ic             REAL,
    excess_vs_taiex REAL,
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
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    date   TEXT,
    author TEXT NOT NULL DEFAULT 'reviewer-calibrator',
    title  TEXT,
    body   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_recent ON journal (id DESC);

CREATE TABLE IF NOT EXISTS report (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
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
"""

_TABLES = ("recommendations", "paper_positions", "ledger_marks", "outcomes",
           "model_registry", "calibration_runs", "memory", "journal", "report", "kv")

# Columns that carry JSON-encoded lists/objects (decoded on read).
_JSON_COLS = {"contributing_factors", "contributing_analysts", "factor_set",
              "regime_weights", "attribution", "adjustments"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enc(v) -> str | None:
    return None if v is None else json.dumps(v, ensure_ascii=False)


def _row(row: sqlite3.Row | None) -> dict | None:
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


def connect(path: str) -> None:
    global _conn
    with _LOCK:
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.executescript(_SCHEMA)
        _conn.commit()


def close() -> None:
    global _conn
    with _LOCK:
        if _conn is not None:
            _conn.close()
            _conn = None


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("store not connected — call connect() first")
    return _conn


def reset() -> dict[str, int]:
    """Wipe ALL durable state (schema preserved) — a clean test/dev slate. Table names are
    fixed constants, so the f-string is not an injection surface."""
    with _LOCK:
        counts = {t: _db().execute(f"DELETE FROM {t}").rowcount for t in _TABLES}
        _db().commit()
        return counts


# --------------------------------------------------------------------------
# kv
# --------------------------------------------------------------------------

def kv_get(k: str, default: str | None = None) -> str | None:
    with _LOCK:
        row = _db().execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
        return row["v"] if row else default


def kv_set(k: str, v: str) -> None:
    with _LOCK:
        _db().execute("INSERT INTO kv (k, v) VALUES (?, ?) "
                      "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, v))
        _db().commit()


# --------------------------------------------------------------------------
# Recommendations (whitepaper §6.1 — recorded at birth)
# --------------------------------------------------------------------------

_REC_FIELDS = ("rec_id", "as_of_date", "symbol", "name", "direction", "entry_ref_price",
               "predicted_return", "predicted_prob_tp", "conviction", "model_version",
               "feature_snapshot_id", "regime_label", "take_profit_price", "stop_loss_price",
               "holding_window_days", "contributing_factors", "contributing_analysts",
               "rationale", "risk_notes")


def add_recommendation(rec: dict) -> dict:
    """Insert one recommendation (replace on same rec_id). JSON-list fields are encoded."""
    vals = []
    for f in _REC_FIELDS:
        v = rec.get(f)
        vals.append(_enc(v) if f in _JSON_COLS else v)
    with _LOCK:
        _db().execute(
            f"INSERT OR REPLACE INTO recommendations ({','.join(_REC_FIELDS)}, created_at) "
            f"VALUES ({','.join('?' * len(_REC_FIELDS))}, ?)", (*vals, _now()))
        _db().commit()
    return get_recommendation(rec["rec_id"])


def get_recommendation(rec_id: str) -> dict | None:
    with _LOCK:
        return _row(_db().execute(
            "SELECT * FROM recommendations WHERE rec_id = ?", (rec_id,)).fetchone())


def list_recommendations(as_of_date: str | None = None) -> list[dict]:
    with _LOCK:
        if as_of_date:
            rows = _db().execute("SELECT * FROM recommendations WHERE as_of_date = ? "
                                 "ORDER BY conviction DESC", (as_of_date,)).fetchall()
        else:
            rows = _db().execute("SELECT * FROM recommendations "
                                 "ORDER BY as_of_date DESC, conviction DESC").fetchall()
        return [_row(r) for r in rows]


# --------------------------------------------------------------------------
# Paper portfolio (positions)
# --------------------------------------------------------------------------

def open_position(rec_id: str, symbol: str, direction: str, entry_price: float,
                  entry_date: str, qty: float = 1.0) -> dict:
    with _LOCK:
        _db().execute(
            "INSERT OR REPLACE INTO paper_positions "
            "(rec_id, symbol, direction, entry_price, entry_date, qty, status) "
            "VALUES (?,?,?,?,?,?, 'open')",
            (rec_id, symbol, direction, entry_price, entry_date, qty))
        # Re-opening voids any prior settlement (keeps a re-run idempotent: a rec is never both
        # 'open' and settled). In normal daily ops rec_ids are date-stamped, so this is a no-op.
        _db().execute("DELETE FROM outcomes WHERE rec_id = ?", (rec_id,))
        _db().commit()
    return get_position(rec_id)


def get_position(rec_id: str) -> dict | None:
    with _LOCK:
        return _row(_db().execute(
            "SELECT * FROM paper_positions WHERE rec_id = ?", (rec_id,)).fetchone())


def list_positions(status: str | None = None) -> list[dict]:
    with _LOCK:
        if status:
            rows = _db().execute("SELECT * FROM paper_positions WHERE status = ? "
                                 "ORDER BY entry_date DESC", (status,)).fetchall()
        else:
            rows = _db().execute("SELECT * FROM paper_positions "
                                 "ORDER BY entry_date DESC").fetchall()
        return [_row(r) for r in rows]


def close_position(rec_id: str) -> None:
    with _LOCK:
        _db().execute("UPDATE paper_positions SET status='closed' WHERE rec_id = ?", (rec_id,))
        _db().commit()


# --------------------------------------------------------------------------
# Ledger marks (daily mark-to-market) + outcomes (settlement)
# --------------------------------------------------------------------------

def add_mark(mark: dict) -> None:
    """Upsert one daily mark (PK rec_id+mark_date) — re-marking a day overwrites it."""
    with _LOCK:
        _db().execute(
            "INSERT OR REPLACE INTO ledger_marks "
            "(rec_id, mark_date, close_price, mtm_return, max_favorable, max_adverse, "
            " tp_hit, sl_hit, days_held) VALUES (?,?,?,?,?,?,?,?,?)",
            (mark["rec_id"], mark["mark_date"], mark.get("close_price"), mark.get("mtm_return"),
             mark.get("max_favorable"), mark.get("max_adverse"),
             1 if mark.get("tp_hit") else 0, 1 if mark.get("sl_hit") else 0,
             mark.get("days_held")))
        _db().commit()


def marks_for(rec_id: str) -> list[dict]:
    with _LOCK:
        rows = _db().execute("SELECT * FROM ledger_marks WHERE rec_id = ? "
                             "ORDER BY mark_date", (rec_id,)).fetchall()
        return [dict(r) for r in rows]


def list_marks(mark_date: str | None = None) -> list[dict]:
    with _LOCK:
        if mark_date:
            rows = _db().execute("SELECT * FROM ledger_marks WHERE mark_date = ? "
                                 "ORDER BY rec_id", (mark_date,)).fetchall()
        else:
            rows = _db().execute("SELECT * FROM ledger_marks "
                                 "ORDER BY mark_date DESC, rec_id").fetchall()
        return [dict(r) for r in rows]


def add_outcome(outcome: dict) -> None:
    with _LOCK:
        _db().execute(
            "INSERT OR REPLACE INTO outcomes "
            "(rec_id, exit_date, exit_price, realized_return, hit, tp_hit, sl_hit, "
            " exit_reason, error) VALUES (?,?,?,?,?,?,?,?,?)",
            (outcome["rec_id"], outcome.get("exit_date"), outcome.get("exit_price"),
             outcome.get("realized_return"), 1 if outcome.get("hit") else 0,
             1 if outcome.get("tp_hit") else 0, 1 if outcome.get("sl_hit") else 0,
             outcome.get("exit_reason"), outcome.get("error")))
        _db().commit()


def get_outcome(rec_id: str) -> dict | None:
    with _LOCK:
        return _row(_db().execute("SELECT * FROM outcomes WHERE rec_id = ?", (rec_id,)).fetchone())


def list_outcomes() -> list[dict]:
    with _LOCK:
        rows = _db().execute("SELECT * FROM outcomes ORDER BY exit_date DESC").fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Model registry
# --------------------------------------------------------------------------

def register_model(model_version: str, train_window: str = "", cv_ic: float | None = None,
                   factor_set: list | None = None, regime_weights: dict | None = None,
                   notes: str = "") -> dict:
    with _LOCK:
        _db().execute(
            "INSERT OR REPLACE INTO model_registry "
            "(model_version, trained_at, train_window, cv_ic, factor_set, regime_weights, notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (model_version, _now(), train_window, cv_ic, _enc(factor_set or []),
             _enc(regime_weights or {}), notes))
        _db().commit()
    return get_model(model_version)


def get_model(model_version: str) -> dict | None:
    with _LOCK:
        return _row(_db().execute(
            "SELECT * FROM model_registry WHERE model_version = ?", (model_version,)).fetchone())


def list_models() -> list[dict]:
    with _LOCK:
        rows = _db().execute("SELECT * FROM model_registry ORDER BY trained_at DESC").fetchall()
        return [_row(r) for r in rows]


def latest_model() -> dict | None:
    models = list_models()
    return models[0] if models else None


# --------------------------------------------------------------------------
# Calibration runs (scorecards)
# --------------------------------------------------------------------------

def add_calibration_run(run: dict) -> dict:
    with _LOCK:
        _db().execute(
            "INSERT OR REPLACE INTO calibration_runs "
            "(run_id, run_date, window, hit_rate, tp_hit_rate, avg_win, avg_loss, ic, "
            " excess_vs_taiex, attribution, adjustments) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run["run_id"], run.get("run_date"), run.get("window"), run.get("hit_rate"),
             run.get("tp_hit_rate"), run.get("avg_win"), run.get("avg_loss"), run.get("ic"),
             run.get("excess_vs_taiex"), _enc(run.get("attribution")),
             _enc(run.get("adjustments"))))
        _db().commit()
    with _LOCK:
        return _row(_db().execute(
            "SELECT * FROM calibration_runs WHERE run_id = ?", (run["run_id"],)).fetchone())


def list_calibration_runs() -> list[dict]:
    with _LOCK:
        rows = _db().execute("SELECT * FROM calibration_runs ORDER BY run_date DESC").fetchall()
        return [_row(r) for r in rows]


# --------------------------------------------------------------------------
# Memory / journal / reports (generic, carried from Sunday)
# --------------------------------------------------------------------------

def get_memory(agent: str) -> dict | None:
    with _LOCK:
        return _row(_db().execute(
            "SELECT agent, content, updated_at FROM memory WHERE agent = ?", (agent,)).fetchone())


def set_memory(agent: str, content: str) -> dict:
    ts = _now()
    with _LOCK:
        _db().execute(
            "INSERT INTO memory (agent, content, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(agent) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
            (agent, content, ts))
        _db().commit()
    return {"agent": agent, "content": content, "updated_at": ts}


def list_memory() -> list[dict]:
    with _LOCK:
        rows = _db().execute("SELECT agent, content, updated_at FROM memory").fetchall()
        return [dict(r) for r in rows]


def add_journal(body: str, title: str | None = None, date: str | None = None,
                author: str = "reviewer-calibrator") -> dict:
    with _LOCK:
        cur = _db().execute(
            "INSERT INTO journal (ts, date, author, title, body) VALUES (?,?,?,?,?)",
            (_now(), date or _now()[:10], author, title, body))
        _db().commit()
        return dict(_db().execute(
            "SELECT * FROM journal WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_journal(author: str | None = None) -> list[dict]:
    with _LOCK:
        if author:
            rows = _db().execute("SELECT * FROM journal WHERE author = ? ORDER BY id DESC",
                                 (author,)).fetchall()
        else:
            rows = _db().execute("SELECT * FROM journal ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def add_report(title: str, body: str, kind: str = "info") -> dict:
    ts = _now()
    with _LOCK:
        cur = _db().execute("INSERT INTO report (ts, kind, title, body) VALUES (?,?,?,?)",
                            (ts, kind, title, body))
        _db().commit()
        rid = cur.lastrowid
    return {"id": rid, "ts": ts, "kind": kind, "title": title, "body": body}


def list_reports(kind: str | None = None) -> list[dict]:
    with _LOCK:
        if kind:
            rows = _db().execute("SELECT * FROM report WHERE kind = ? ORDER BY id DESC",
                                 (kind,)).fetchall()
        else:
            rows = _db().execute("SELECT * FROM report ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
