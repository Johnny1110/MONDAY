# A9 — Calibration extensions (macro-call accuracy + position-management value-add)

- **Epic**: A (engine foundations) · **Owner**: evva · **Size**: M
- **Status**: Proposed
- **Depends on**: A1 (macro_calls / position_actions tables), A2 (macro snapshot for settlement), A3 (book/actions), A5 (review actions feed this)
- **Blocks**: B4 (reviewer-calibrator reads these), C1 (calibration v2 panel)
- **PRD ref**: PRD-002 §倉位管理 (校準擴充：記「倉位管理對不對」與「宏觀判斷對不對」), §風險 (discretionary drift → reality check); whitepaper §6 (calibration core)
- **Files**: `engine/monday/calibration.py`, `engine/monday/routers/calibration.py`, `engine/monday/triggers.py`, `engine/monday/events.py`, `engine/monday/manual.md`, `engine/tests/test_calibration.py` (extend)

## Problem

2.0 adds two judgement layers that 1.0's calibration ledger doesn't measure: **macro calls** (was risk-on/off right?) and
**position management** (did trims/exits add value vs. holding?). Without scoring them, the committee can drift into
good-sounding-but-edgeless narrative (the PRD's named risk). Calibration is the reality check — extend it to these dims so
the weekly review can say which judgements actually earn their keep.

## Goal

Pure calibration math + token-free endpoints for **macro-call accuracy** and **position-management value-add**, settled from
the macro snapshot (A2) and the action log (A3/A5), folded into the weekly scorecard and (optionally) a drift trigger.

## Scope (in)

- `calibration.py` pure: `macro_call_accuracy`, `position_mgmt_value`.
- Settlement of matured macro calls against forward index returns.
- Endpoints: `POST /api/calibration/macro/call` (record), `GET /api/calibration/macro`, `POST /api/calibration/macro/settle`, `GET /api/calibration/positions`.
- Fold both dims into `POST /api/calibration/run`'s stored scorecard (`adjustments`/`attribution` JSON — **no schema change**).
- Optional `macro_drift` trigger; manual + tests.

## Out of scope

- The existing stock-pick scorecard (IC/hit/brier/attribution) — unchanged; we *add* dims beside it.
- Changing `calibration_runs` columns (reuse JSON fields).

## Design

### `calibration.py` (pure, stdlib)

```python
def macro_call_accuracy(calls) -> dict:
    """calls: settled macro_calls with realized_index_fwd_ret + correct. Returns
    {n, hit_rate, by_risk_state:{risk_on:{n,hit_rate}, ...}, avg_fwd_when_risk_on, avg_fwd_when_risk_off}."""

def position_mgmt_value(actions, realized_lookup) -> dict:
    """For each trim/exit action, value-add = realized_at_action − counterfactual_hold_return (what the
    lot would have returned had it been held to the window end / latest mark). realized_lookup maps
    (symbol, action_date) → both numbers. Returns {n, exit_value_add_mean, trim_value_add_mean,
    pct_actions_value_positive}. Positive ⇒ the discipline helped."""
```

`correct` scoring rule (settlement): `risk_on` correct if forward benchmark return > +ε; `risk_off` correct if < −ε;
`neutral` correct if |return| ≤ ε. Benchmark = TAIEX proxy from A2's macro snapshot (or the TW equal-weight index from
`regime.market_index` as a fallback). ε in config (`macro_call_eps_pct`).

### Settlement

```python
# pipeline-side helper or in routers/calibration.py:
def settle_macro_calls(as_of) -> dict:
    """For each macro_call whose call_date + horizon_days ≤ as_of and correct IS NULL, compute the
    realized forward benchmark return from the macro snapshots and store.update_macro_call(correct, fwd)."""
```

### Endpoints (token-free; `routers/calibration.py`)

- `POST /api/calibration/macro/call` — record today's call. Body `{call_date?, risk_state, horizon_days?, sectors_favored?, sectors_avoid?, by?, rationale?}` → `store.add_macro_call` (call_id = call_date; upsert). **macro-analyst (B1) writes its own call here** (`by="macro-analyst"`) so its accuracy is attributable; morgan's consolidated stance lives in the report (A7).
- `GET /api/calibration/macro` — `macro_call_accuracy(store.list_macro_calls())` over settled calls.
- `POST /api/calibration/macro/settle?as_of=` — run settlement; returns counts settled.
- `GET /api/calibration/positions` — `position_mgmt_value(...)` from `store.list_position_actions()` + realized lookup (book marks / counterfactual from prices).
- Extend `POST /api/calibration/run`: include `macro` + `position_mgmt` blocks in the stored `adjustments` JSON (so the weekly scorecard snapshot carries them) and in the response.

### Optional trigger (`triggers.py` + `events.py`)

`detect_macro_drift(macro_accuracy_history, floor, periods)` → `macro_drift_event` (wake morgan/macro-analyst) when macro
hit-rate is below floor for N reviews — mirror `detect_calibration_drift`. Wire into `evaluate_calibration`'s callers. Keep
behind config so it can ship dark first.

## Acceptance criteria

- `POST /api/calibration/macro/call` records/updates today's macro call (upsert on call_date) with `by` attribution; lists via `GET /api/calibration/macro`.
- `POST /api/calibration/macro/settle` scores matured calls (correct/realized_fwd) from snapshots; idempotent (won't re-score a settled call); returns counts.
- `GET /api/calibration/macro` returns overall + by-risk_state hit rates over settled calls.
- `GET /api/calibration/positions` returns trim/exit value-add means and the share of value-positive actions, from the action log.
- `POST /api/calibration/run` now stores the macro + position-mgmt dims inside the scorecard's JSON (verifiable via `GET /api/calibration/runs`), with **no `calibration_runs` schema change**.
- Pure functions unit-tested; the existing stock-pick scorecard output is unchanged.

## Test plan (`engine/tests/test_calibration.py` — extend)

- `test_macro_call_accuracy` — synthetic settled calls → correct overall + per-state hit rates.
- `test_macro_correct_rule` — risk_on/off/neutral scored correctly around ε.
- `test_position_mgmt_value` — a well-timed exit scores positive value-add; a premature exit (missed a run-up) scores negative.
- `test_settle_idempotent` — settling twice doesn't double-score.
- `test_scorecard_carries_new_dims` — `POST /run` stores macro + position_mgmt in JSON, scorecard stock-pick fields intact.

## Invariant & discipline checklist

- [ ] Pure stdlib calibration math, unit-tested (6); reuses `calibration_runs` JSON (no schema churn) (5).
- [ ] Token-free endpoints; triggers via webhook, fire-and-forget (2,7,8).
- [ ] Settlement reads only PIT macro snapshots (no look-ahead, §4.2) (9).
- [ ] Honest reality-check: surfaces value-add even when negative (don't hide a discipline that isn't working) (§9 honesty).

## Risks / edge cases

- **Counterfactual definition**: "held instead of trimmed" needs a clear horizon (to window-end or to latest mark) — pick one, document it, keep it consistent across runs (changing it mid-stream breaks comparability).
- **Thin samples early**: report `n` and suppress conclusions below a min-sample (like `calibration_min_samples`) — don't over-read 3 macro calls.
- **Benchmark choice**: TAIEX vs equal-weight index changes the macro score — fix it in config and note it in the scorecard.

## Rollout notes

After A1/A2/A3/A5. reviewer-calibrator (B4) reads these in the Friday review; C1 adds the panels. The macro_drift trigger can ship disabled and be enabled once enough calls settle.
