# A2 — Macro data layer + `GET /api/macro`

- **Epic**: A (engine foundations) · **Owner**: evva · **Size**: L
- **Status**: Proposed
- **Depends on**: — (independent of A1; needs only `main`)
- **Blocks**: B1 (macro-analyst), A9 (macro-call scoring reads the macro snapshot), C1 (macro panel)
- **PRD ref**: PRD-002 §平台改動 (全球宏觀數據), §資料重點, §保留的紀律 (PIT); whitepaper §4.2 (PIT), §4.3 (market/regime features)
- **Files**: new `engine/monday/ingest/macro.py`, new `engine/monday/macro.py`, new `engine/monday/routers/macro.py`, `engine/monday/app.py`, `engine/monday/config.py`, `engine/monday/manual.md`, new `engine/tests/test_macro.py`, fixture under `engine/tests/fixtures/`

## Problem

2.0 is **top-down**: macro-analyst sets the day's risk-on/off from world indices + overnight moves. Today the engine has
**no macro layer** — `regime.py` builds an equal-weight index from the *TW universe only* (not world indices), and there is
no clean read endpoint. The PRD locks (decision 6) that evva builds a real `/api/macro` (not just agent `web_search`), with
the same **PIT snapshot** discipline as prices (look-ahead is still the #1 threat, §4.2).

## Goal

A token-free `GET /api/macro` serving world indices with overnight change, backed by a cached/rate-limited free adapter and
a daily **PIT snapshot** (parquet, stamped `as_of`), refreshable each morning after the US close.

## Scope (in)

- `ingest/macro.py` — fetch world indices from a **free, key-less** source (Yahoo Finance chart JSON), via `ingest/base.fetch_json` (cache + rate-limit + retry + quota).
- `macro.py` — pure shaping (`build_macro_rows`, `overnight_changes`) + PIT snapshot read/write (parquet via `parquetio`, mirroring `snapshot.py`).
- `routers/macro.py` — `GET /api/macro`, `GET /api/macro/{date}`, `POST /api/macro/refresh`.
- Mount in `app.py`; document in `manual.md` (new "Macro plane" section); config index map.
- A `macro.refresh()` step folded into `pipeline.run()` (so a full run also archives macro) — idempotent per `as_of`.

## Out of scope

- Feeding macro into the GBDT/`regime.py` ensemble (future ticket — A2 only *exposes* macro; the model still uses TW features).
- World **news** ingest (decision 6: macro-analyst uses `web_search`; the brief is PIT-archived in A7/A9, not here).

## Design

### Index universe (config `macro_symbols`, overridable)

`^SOX, ^IXIC, ^GSPC, ^DJI, 000001.SS, ^HSI, ^N225, ^STOXX50E, ^VIX, USDTWD=X, ^TNX, GC=F, CL=F`
— each mapped to a display name + `asset_class ∈ {equity_index, vol, fx, rate, commodity}`.

### `ingest/macro.py`

```python
def fetch_indices(symbols: list[str], *, cache_dir: str, days: int = 7) -> dict[str, list[dict]]:
    """Per symbol: GET Yahoo chart (query1.finance.yahoo.com/v8/finance/chart/{sym}?range=…&interval=1d)
    via base.fetch_json (key-less, cached, rate-limited). Returns {symbol: [{date, close}, …]} latest-last.
    Tolerates a per-symbol failure (logs + omits it) so one dead ticker never sinks the batch."""
```

- Reuse `base.fetch_json(..., rate_key="yahoo", min_interval=0.4, cache_dir=...)`; raise nothing fatal on a single miss.
- TTL the cache so re-pulls within the morning don't re-hit the source; respect `RateLimitError` (degrade, omit symbol).

### `macro.py` (pure + snapshot)

```python
def build_macro_rows(as_of, raw, meta) -> list[dict]   # {as_of, symbol, name, asset_class, close, prev_close, chg_pct}
def overnight_changes(rows) -> dict                     # {risk_proxies, leaders, laggards} convenience for the dashboard/brief
def macro_snapshot_path(data_dir) -> str                # data_dir/snapshots/macro.parquet
def write_macro_snapshot(data_dir, as_of, rows) -> int  # parquetio.upsert(..., keys=["as_of"]) — append-only, idempotent
def read_macro_snapshot(data_dir, as_of=None) -> list[dict]
def refresh(data_dir, cache_dir, symbols, as_of=None) -> dict  # fetch → shape → snapshot; returns {as_of, n}
```

`chg_pct = (close/prev_close - 1) * 100`. `as_of` defaults to the latest common date across symbols. **Snapshot is PIT**:
stamp `as_of`, append-only, never mutate a past day (invariant 9, §4.2).

### `routers/macro.py` (token-free)

- `GET /api/macro?as_of=` — latest (or `as_of`) snapshot: `{as_of, indices:[…rows…], overnight:{…}}`. Small fixed list → return whole (like `/api/portfolio/equity`).
- `GET /api/macro/{date}` — the immutable PIT snapshot for `date` (mirrors `/api/signals/{date}`).
- `POST /api/macro/refresh?as_of=` — pull + snapshot now (synchronous; ~13 cached fetches, fast). Returns `{as_of, n}`. data-engineer calls this each morning (STEP 0b).

### Wiring

- `app.py`: add `macro` to the import + `include_router` tuple.
- `pipeline.run()`: after ingest, call `macro.refresh(...)` (best-effort, never fatal — a macro miss must not sink the TW pipeline; log + continue) and add a `stages["macro"]` summary.
- `config.py`: `macro_symbols: dict` (symbol→{name,asset_class}), `macro_source: str = "yahoo"`.
- `manual.md`: new "## Macro plane" documenting the three endpoints + the PIT note.

## Acceptance criteria

- `POST /api/macro/refresh` pulls the configured indices and writes a parquet snapshot stamped `as_of`; re-running the same `as_of` overwrites (idempotent), a prior `as_of` is untouched.
- `GET /api/macro` returns each index with `close`, `prev_close`, `chg_pct`, `asset_class`; `GET /api/macro/{date}` returns the archived snapshot or a clear empty note.
- One dead ticker degrades gracefully (omitted + logged), the rest succeed.
- A FinMind/Yahoo rate-limit (`RateLimitError`) does not crash the endpoint — it returns what it has.
- `pipeline.run()` still succeeds end-to-end with macro folded in (and still succeeds if macro fetch fails).
- Token-free; no key required for Yahoo.

## Test plan (`engine/tests/test_macro.py`)

- Record a small **fixture** of Yahoo chart JSON for 2–3 symbols (`engine/tests/fixtures/macro_sample.json`) — no live network in tests (mirrors `tw_sample.json`).
- `test_build_macro_rows` — fixture → rows with correct `chg_pct`, `prev_close`, `asset_class`.
- `test_overnight_changes` — leaders/laggards/risk-proxy extraction.
- `test_macro_snapshot_roundtrip` — write/read parquet, `as_of` stamping, idempotent re-write.
- `test_fetch_indices_degrades` — a symbol returning malformed JSON is omitted, others survive (monkeypatch `base.fetch_json`).

## Invariant & discipline checklist

- [ ] Token-free endpoints; Yahoo needs no key; any future keyed source lives in `config.py` only (1,2).
- [ ] One router module `routers/macro.py` for the `/api/macro` prefix (4).
- [ ] Macro snapshot in **parquet**, PIT-stamped `as_of`, append-only (5, 9).
- [ ] `ingest/base.fetch_json` reused for cache/rate-limit/retry/quota; stdlib urllib only; heavy deps lazy (6).
- [ ] Outbound/refresh never raises fatally into the pipeline (8 spirit — best-effort).

## Risks / edge cases

- **Yahoo endpoint instability / terms**: keep the adapter swappable (config `macro_source`); document stooq as a fallback if Yahoo blocks.
- **TZ / "overnight"**: world closes span TZs; define `as_of` as the latest common trading date and treat `chg_pct` as "last close vs prior close" — don't over-claim intraday.
- **PIT honesty**: only ever snapshot what's visible that morning; never backfill a past `as_of` with later values.

## Rollout notes

Independent of A1 — can build in Wave 2 immediately. B1 (macro-analyst) and C1 (dashboard) are its consumers; A9 reads the snapshot to score macro calls.
