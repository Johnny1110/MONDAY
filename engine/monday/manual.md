# Monday engine — agent API manual (`GET /manual`)

You drive Monday over plain HTTP. **Every endpoint is token-free** — the platform holds all
data-source keys; you hold only HTTP (invariants 1–2). List endpoints return the uniform
envelope `{items, page, page_size, total, has_more}` (invariant 3); pass `?page=&page_size=`.

**Production**: data is real free-core market data — **FinMind** primary (prices + 法人/margin chips +
sector), **TWSE** fallback — selected via `?source=` (default `finmind`). The model is a GBDT trained on
accumulated PIT data (a baseline momentum ranker is the fallback). News/sentiment feeds are still being
wired. There is no synthetic/fake source — paper portfolio only, research opinion not investment advice.

Base URL: `http://127.0.0.1:7790`

## System
- `GET /health` — liveness ping.
- `GET /api/system/status` — versions, last pipeline day, counts, `finmind_token_loaded` (is the
  data-source key live this process), `universe_size`, and `pipeline` (the currently-running run, if any).
- `POST /api/system/run-pipeline?source=finmind&model=gbdt&finalize=true&days=180` — trigger the
  chain (ingest → clean → PIT snapshot → features → model → signals [→ recommend → mark]).
  **ASYNC**: returns `{task_id, status:"running"}` (202) at once and runs in the background — **poll
  `GET /api/system/tasks/{task_id}`** for stage/result; do not expect the result on this call.
  **Single-flight**: a second trigger while one is running returns **409** (with the holder) — don't retry-spam.
  Params: `source` ∈ {`finmind`,`twse`}; `model` ∈ {`baseline`,`gbdt`}; **`finalize=false` stops after
  signals** (the swarm composes the book); `days` (history depth — use ≥120 or long-window momentum
  factors go null and the ranking degrades, reported as `degraded_factors`); `universe_size` /
  `symbols` (comma list e.g. `2330,2317`) scope the run; `as_of`; `force` (overwrite signals even if
  the day is already finalized); `post`/`notify` fire swarm webhooks / Telegram.
- `GET /api/system/tasks?limit=20` · `GET /api/system/tasks/{task_id}` — recent runs / one run's
  status (`running|succeeded|failed`), current `stage`, and `result`/`error`.
- `GET /api/system/quota` — FinMind usage (`today` per-day tally + `live` this process), with
  `rate_limited_recently` — **when true the free tier is spent; stop hitting `/api/chips` and rely on
  cache until reset** (chips returns 503 on quota).

## Data plane (read)
- `GET /api/universe?as_of=` — analysable pool after the liquidity gate (§4.1).
- `GET /api/prices?symbol=2330&as_of=` — daily OHLCV from the PIT snapshot.
- `GET /api/factors` — factor catalog (what each feature column means).
- `GET /api/features?as_of=&symbol=` — computed feature rows for a day (§4.3).
- `GET /api/chips?symbol=2330&as_of=` — institutional-flow / margin chip factors (籌碼, §5.6):
  foreign/investment-trust net-flow + streak, margin/short balance change. a-chips's data.
- `GET /api/models` · `GET /api/models/{version}` — the model registry (§5.4).
- `POST /api/models/train?source=finmind&days=400` — train + register a cold-start GBDT; reports OOS rank IC.

## Macro plane (top-down read, §4.3)
The 2.0 day starts top-down: read world indices / overnight moves to set risk-on/off. Free key-less
source (Yahoo), **PIT-snapshotted** like prices (stamped `as_of`, append-only — never backfilled).
macro-analyst reads this and adds world-news colour via `web_search`.
- `GET /api/macro?as_of=` — latest (or `as_of`) snapshot: `{as_of, indices:[{symbol, name, asset_class,
  close, prev_close, chg_pct, date}], overnight:{leaders, laggards, risk_proxies}}`. `asset_class` ∈
  {`equity_index`,`vol`,`fx`,`rate`,`commodity`}; `chg_pct` is last close vs prior close (not intraday).
  Small fixed list → returned whole (no pagination).
- `GET /api/macro/{date}` — the IMMUTABLE PIT macro snapshot archived for that day (or a clear empty note).
- `POST /api/macro/refresh?as_of=` — pull the indices + write today's snapshot now (synchronous, fast,
  cached). data-engineer calls this each morning (STEP 0b). Returns `{as_of, n, rows_on_disk, symbols}`.
  A dead/blocked ticker is omitted (logged), the rest succeed; a rate-limit degrades, never crashes.

## Decision plane
- `GET /api/signals/today` — the model's LATEST candidate ranking (you overlay/veto WITHIN this set;
  never invent a name outside it — cardinal discipline 1, §5.6). Carries `signals_version` +
  `degraded_factors`.
- `GET /api/signals/{date}` — the IMMUTABLE signals snapshot archived for that day — the exact set a
  finalized book was built against, preserved even after later runs (decision traceability). Once a day
  is finalized, a later prepare run won't overwrite `today` unless `force=true`.
- `GET /api/recommendations/today` — the daily envelope (appendix C contract).
- `GET /api/recommendations?as_of=` — persisted ideas (paginated).
- `POST /api/recommendations` — commit one finalised idea `{rec_id, symbol, as_of_date, …}`;
  opens its paper position.
- `POST /api/recommendations/finalize` `{symbols:[…]}` — compose the day's ≤20 book from today's
  candidates after the analyst overlay (morgan, §5.7); opens positions, returns the envelope
  (with the `risk` gate result attached — advisory).

## Portfolio + ledger + calibration
- `GET /api/portfolio?status=open` — paper positions + summary.
- `GET /api/portfolio/risk` — §5.7 risk gate on the open book (sector concentration / name count /
  liquidity); advisory (risk-monitor's read-only patrol).
- `GET /api/ledger/marks?rec_id=|date=` · `GET /api/ledger/outcomes` — the calibration ledger.
- `POST /api/ledger/reconcile?source=finmind` — daily mark-to-market of open positions (reviewer-calibrator).
- `GET /api/calibration` — live scorecard (IC / hit-rate / calibration curve / attribution).
- `GET /api/calibration/runs` · `POST /api/calibration/run?window=weekly` — snapshot a scorecard
  (the weekly review's input, §6.2).

## Book / positions (2.0 managed book, §倉位管理)
The real/paper book the User trades — one lot per (book, symbol) with weighted cost basis + a daily
hold/add/trim/exit lifecycle. **The swarm proposes fills; the User confirms; the engine records them —
it NEVER places an order** (invariant 11, you are the air-gap; no broker integration). `book` ∈
{`paper`,`real`} and defaults to the engine's `book_mode` (`paper` until D1's cutover).
- `GET /api/book?book=&status=open|all` — holdings (paginated) + an exposure `summary`
  {n, gross, net, cash, total, by_sector, weights}.
- `POST /api/book/fill` — record one fill (decision-agnostic): body `{symbol, side, qty, price, book?,
  at?, source?, rec_id?, name?, reason?, regime?, take_profit?, stop_loss?, fill_key?}`. `side ∈
  {buy, sell}`; `buy` opens/adds (avg re-weighted), `sell` trims/exits (avg held, realized booked); a
  sell clamps to the held qty (never negative). Pass `fill_key` to make a User double-confirm
  **idempotent**. `at` defaults to the last pipeline day. Returns the updated lot + the logged action.
- `POST /api/book/targets` — set a lot's TP/SL: body `{symbol, book?, take_profit?, stop_loss?}` (A5).
- `GET /api/book/actions?since=&position_id=` — the append-only lifecycle log (paginated; calibration
  + the weekly review read it).
- `GET /api/book/exposure?book=` — current gross/net/cash/by-sector exposure (risk-monitor's GATE 2 input).

## Event sources (P1 stubs)
- `GET /api/news?symbol=` · `GET /api/sentiment?symbol=` — return empty + a note in P0.

## Memory / journal / reports
- `GET /api/memory/{agent}` · `PUT /api/memory/{agent}` `{content}` — your public board (§6.5).
- `GET /api/memory` — all boards.
- `GET /api/journal?author=` · `POST /api/journal` `{body, title?, author?}` — team work log.
- `GET /api/reports?kind=` · `POST /api/reports` `{title, body, kind?}` — User-facing notices.

## Conventions
- All writes are JSON bodies. Dates are ISO `YYYY-MM-DD`; `as_of` defaults to the latest
  pipeline day when omitted.
- Calibration depends on the ledger: every recommendation is recorded at birth with its
  model_version / feature_snapshot_id / predicted_return / prob_tp so it can be regressed (§6.1).
