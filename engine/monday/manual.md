# Monday engine — agent API manual (`GET /manual`)

You drive Monday over plain HTTP. **Every endpoint is token-free** — the platform holds all
data-source keys; you hold only HTTP (invariants 1–2). List endpoints return the uniform
envelope `{items, page, page_size, total, has_more}` (invariant 3); pass `?page=&page_size=`.

This is the **P0 scaffold**: data defaults to synthetic (NOT investable), but real free-core
sources (**FinMind**, **TWSE**) are selectable via `?source=`. The model is an untrained baseline
momentum ranker, and the news/sentiment feeds are stubs. The *contract shape* below is stable;
the *content* gets fully real in P1.

Base URL: `http://127.0.0.1:7790`

## System
- `GET /health` — liveness ping.
- `GET /api/system/status` — versions, last pipeline day, counts.
- `POST /api/system/run-pipeline?source=synthetic&model=baseline&finalize=true&days=180` — run the
  chain (ingest → clean → PIT snapshot → features → model → signals [→ recommend → mark]). `source` ∈
  {`synthetic`,`finmind`,`twse`}; `model` ∈ {`baseline`,`gbdt`}; **`finalize=false` stops after signals**
  (the swarm composes the book); `post`/`notify` fire swarm webhooks / Telegram.

## Data plane (read)
- `GET /api/universe?as_of=` — analysable pool after the liquidity gate (§4.1).
- `GET /api/prices?symbol=2330&as_of=` — daily OHLCV from the PIT snapshot.
- `GET /api/factors` — factor catalog (what each feature column means).
- `GET /api/features?as_of=&symbol=` — computed feature rows for a day (§4.3).
- `GET /api/models` · `GET /api/models/{version}` — the model registry (§5.4).
- `POST /api/models/train?source=finmind&days=400` — train + register a cold-start GBDT; reports OOS rank IC.

## Decision plane
- `GET /api/signals/today` — the model's candidate ranking (you overlay/veto WITHIN this set;
  never invent a name outside it — cardinal discipline 1, §5.6).
- `GET /api/recommendations/today` — the daily envelope (appendix C contract).
- `GET /api/recommendations?as_of=` — persisted ideas (paginated).
- `POST /api/recommendations` — commit one finalised idea `{rec_id, symbol, as_of_date, …}`;
  opens its paper position.
- `POST /api/recommendations/finalize` `{symbols:[…]}` — compose the day's ≤20 book from today's
  candidates after the analyst overlay (morgan, §5.7); opens positions, returns the envelope.

## Portfolio + ledger + calibration
- `GET /api/portfolio?status=open` — paper positions + summary.
- `GET /api/ledger/marks?rec_id=|date=` · `GET /api/ledger/outcomes` — the calibration ledger.
- `POST /api/ledger/reconcile?source=finmind` — daily mark-to-market of open positions (reviewer-calibrator).
- `GET /api/calibration` — live scorecard (IC / hit-rate / calibration curve / attribution).
- `GET /api/calibration/runs` · `POST /api/calibration/run?window=weekly` — snapshot a scorecard
  (the weekly review's input, §6.2).

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
