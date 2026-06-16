# ADR 0001 — Transactional store: SQLite → PostgreSQL

**Date:** 2026-06-16  **Status:** Accepted (User-directed)  **Supersedes:** whitepaper §1 invariant 5 / §0.1 "No Postgres/Redis"

## Context

The engine's transactional state (recommendations / paper portfolio / ledger / calibration /
model registry / memory / journal / reports / kv / pipeline lock) ran on **SQLite** behind a single
shared connection serialized by a global `RLock` + WAL/`busy_timeout` — a deliberate workaround,
since one sqlite connection isn't safe for concurrent use. The 2026-06-15 production cutover hit
exactly this wall: concurrent pipeline runs racing the single writer (`SQLITE_BUSY`), recorded as
blocker **B11**. The single-writer serialization is a structural ceiling as the swarm and the
async pipeline (B10) drive more concurrent writes.

The original whitepaper locked **"No Postgres/Redis"** for operational simplicity (one file, no
server). The User has chosen to override that decision.

## Decision

Move the transactional store to **PostgreSQL**, **engine-internal**:

- `store.py` re-implemented on **psycopg 3 + `psycopg_pool.ConnectionPool`** (`dict_row`), keeping
  **every public function signature identical** — no other module changed (routers, `pipeline.py`,
  `tasks.py`, `models/train.py`, `app.py` all call the same `store.*` API). The global `RLock` +
  `PRAGMA` WAL/`busy_timeout` single-connection workaround is **retired**; PG MVCC + the pool handle
  concurrency, one transaction per op.
- The cross-process single-flight `pipeline_lock` (B11) keeps its atomic CAS (`UPDATE … WHERE … OR
  heartbeat stale`) — now backed by a true PG row lock.
- The DSN holds credentials and lives **engine-side only** (`DATABASE_URL` in `.env`), never exposed
  to agents — agents still speak only token-free HTTP (invariants 1–2 intact).
- **Greenfield**: the schema is recreated empty in PG; the live `monday.db` is **not** migrated
  (accepted loss of the prior paper-portfolio + calibration history — the science restarts its
  accumulation).
- **Parquet stays** for the large feature/price/PIT-snapshot tables (columnar is right for the GBDT's
  bulk numeric scans). No third datastore.
- **Tests** run against a throwaway Postgres (`MONDAY_TEST_DSN`) and **auto-skip** when none is
  reachable (mirrors the pyarrow-gated skips); pure-logic suites are unchanged. `engine/docker-compose.yml`
  brings up a local PG for dev.

## Consequences

- **+** Removes the single-writer serialization ceiling and the B11 contention class; real concurrency
  via the pool + MVCC.
- **+** Standard ops tooling (backups, replicas, observability) and room to grow (JSONB / timestamptz /
  partitioning later — kept as TEXT/ISO for now to minimise the diff).
- **−** A new runtime dependency: the engine now needs a reachable Postgres (compose for dev, a managed
  DSN in prod) — no longer a single self-contained file.
- **−** The bare-interpreter, zero-dependency test path is gone for store-backed tests (they need PG or
  skip).

## When to revisit

If the operational cost of running Postgres outweighs the concurrency benefit (e.g. the project stays
single-writer in practice), or if a managed serverless Postgres changes the calculus. Any reversal is a
new ADR.
