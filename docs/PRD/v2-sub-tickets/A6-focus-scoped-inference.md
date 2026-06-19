# A6 — Focus-scoped inference + holdings scoring

- **Epic**: A (engine foundations) · **Owner**: evva · **Size**: M
- **Status**: Proposed
- **Depends on**: — (extends existing `signals`/`pipeline`; uses `main`). Pairs with A3 for "holdings".
- **Blocks**: B3 (morgan SYNC A→quant), B4 (quant agent)
- **PRD ref**: PRD-002 §flow STEP A1 + 同步點規則 "quant 在定調之後跑：對全池橫斷面排名、輸出只收斂到聚焦板塊 + 現有持倉"; decision 2 (quant kept as input)
- **Files**: `engine/monday/signals.py`, `engine/monday/pipeline.py`, new `engine/monday/routers/signals.py` endpoint, `engine/monday/parquetio.py` usage, `engine/monday/manual.md`, `engine/tests/test_signals.py`

## Problem

In the 2.0 DAG, **quant runs after SYNC A**: the GBDT still ranks the **full pool** (cross-sectional ranking is only valid over
the whole universe), but its candidate **output is scoped to the focus sectors morgan set + the current holdings**. Today
`signals.build_envelope` just takes the top-`candidate_pool` of one ranking with no sector scoping and no guarantee that held
names are scored. We need (a) the full ranked predictions persisted so scoping is cheap (no re-inference), (b) a rescope step
that filters to focus sectors and **always includes holdings**, preserving the immutability/`signals_version` discipline (B9/B13).

## Goal

A two-phase signal flow: the prepare run persists **all** ranked predictions; a `POST /api/signals/rescope` produces a
focus+holdings candidate envelope from them — full-pool ranking preserved, held names always scored, sector-labelled.

## Scope (in)

- Persist the full ranked predictions for `as_of` (parquet, e.g. `data/predictions/{as_of}.parquet`, or a kv blob if small).
- Extend `signals.build_envelope` to accept `focus_sectors`, `holdings`, `sector_lookup`; tag each candidate `sector`, `in_focus`, `held`.
- `POST /api/signals/rescope {focus_sectors, holdings?}` → rescoped envelope; updates `signals_today` (new `signals_version`) without re-running inference; **archives** the full predictions immutably.
- Sector labels via `ingest/finmind.fetch_stock_info` (as `routers/portfolio.risk_view` already does); holdings from A3's book (fallback: `?holdings=` query / `paper_positions`).
- manual + tests.

## Out of scope

- Retraining / model changes (quant-researcher / `models/`).
- Re-running ingest/features (rescope reuses persisted predictions).

## Design

### Persist full predictions (prepare run)

In `pipeline.run()` after step 5 (inference), persist the full `preds` (all ranked rows, not just `candidate_pool`) to
`data/predictions/{as_of}.parquet` (via `parquetio.upsert`, keys=["as_of","symbol"]) and stamp `kv: predictions_version:{as_of}`.
This is the immutable basis a rescope reads — consistent with the PIT discipline.

### `signals.build_envelope` (extend, keep backward-compatible)

```python
def build_envelope(as_of, model_version, regime, predictions, pool, *, signals_version=None,
                   degraded=None, focus_sectors=None, holdings=None, sector_lookup=None) -> dict:
    """Unchanged when focus_sectors/holdings are None (1.0 behaviour preserved). When given:
      - rank the FULL `predictions` (already sorted), take top `pool` whose sector ∈ focus_sectors as candidates,
      - ALWAYS append every `holdings` symbol present in predictions (flag held=True), de-duplicated,
      - tag each candidate {sector, in_focus, held}; keep `all_ranked` count + `focus_sectors` in the envelope."""
```

Ranking is computed over the whole pool (validity); only the **selection** narrows. Holdings outside focus are still scored
(so morgan's hold/trim/exit has the model's view, per the §flow rule).

### `POST /api/signals/rescope` (token-free; in `routers/signals.py`)

- Body `{focus_sectors:[...], holdings?:[...], pool?}`. Reads persisted predictions for `last_as_of` + sector map + holdings (A3 book or body), calls `build_envelope(...)`, writes `signals_today` + `signals:{as_of}` with a **new** `signals_version` (mutable latest + immutable per-version archive). Returns the rescoped envelope.
- Preserve B9/B13: if the day is already `finalized:{as_of}`, refuse to clobber unless `force=true` (mirror `pipeline.run`'s guard).

## Acceptance criteria

- After a prepare run, `data/predictions/{as_of}.parquet` holds the **full** ranked pool (not just top-N).
- `rescope` with `focus_sectors=["半導體"]` returns only focus-sector candidates **plus** all current holdings (held=True), each with `sector`/`in_focus`/`held`; full-pool `rank`/`score` are unchanged from the prepare run (no re-inference).
- `build_envelope` with no focus args returns the **exact** 1.0 envelope (backward compatible — existing tests pass).
- Rescope respects the finalized-day guard (no silent clobber).
- Holdings with no prediction row (e.g. delisted/illiquid) are reported in a `holdings_unscored` list, not dropped silently.

## Test plan (`engine/tests/test_signals.py` — extend)

- `test_envelope_backcompat` — no focus args ⇒ identical to current output (guards the 1.0 path).
- `test_focus_filter` — only focus-sector names selected as fresh candidates.
- `test_holdings_always_included` — a held name outside focus appears with `held=True` and its real score.
- `test_full_ranking_preserved` — ranks/scores match the unscoped ranking (scoping ≠ re-ranking).
- `test_holdings_unscored_reported` — a holding absent from predictions surfaces in `holdings_unscored`.

## Invariant & discipline checklist

- [ ] Cross-sectional ranking stays full-pool (correctness — the §flow rule); only output is scoped (6).
- [ ] Immutability/`signals_version` discipline preserved; finalized-day guard intact (B9/B13).
- [ ] Full predictions archived (PIT-consistent, parquet) (5,9).
- [ ] Token-free; one signals router (2,4); backward-compatible envelope (DoD).

## Risks / edge cases

- **Sector map gaps**: `unknown`-sector names can't be focus-matched — surface a count so morgan knows coverage (don't silently exclude a big chunk).
- **Empty focus result**: if focus sectors yield too few candidates, return what exists + a note (morgan may widen focus) — never error.
- **Storage growth**: `data/predictions/*` — note retention (prune older than the calibration window in a future housekeeping task).

## Rollout notes

Backward-compatible: the autonomous `pipeline.run()` ignores rescope unless called. B3 wires the round: prepare run → SYNC A focus → `POST /api/signals/rescope` → analysts overlay → finalize.
