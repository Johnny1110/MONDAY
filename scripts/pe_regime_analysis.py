#!/usr/bin/env python3
"""PE factor regime stability: bull / bear / choppy IC decomposition.
For Friday review: IC-weighted vs equal-weight factor discussion."""
import sys, os, json, hashlib, urllib.parse, pathlib
from datetime import date
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))
from monday.config import settings

TOKEN = settings.finmind_token
CACHE = pathlib.Path(os.path.join(os.path.dirname(__file__), '..', 'engine', 'data', 'cache'))
API = "https://api.finmindtrade.com/api/v4/data"
PRICES_PATH = os.path.join(os.path.dirname(__file__), '..', 'engine', 'data', 'snapshots', 'prices.parquet')

# Load prices
prices = pd.read_parquet(PRICES_PATH)
prices['date'] = pd.to_datetime(prices['date'])
symbols = sorted(prices['symbol'].unique())
print(f"Prices: {len(symbols)} symbols")

# Load PE from cache
print("Loading PE from cache...")
pe_list = []
for sym in symbols:
    params = {'dataset': 'TaiwanStockPER', 'data_id': sym,
              'start_date': '2022-01-01', 'end_date': '2026-06-16', 'token': TOKEN}
    raw = API + "?" + urllib.parse.urlencode(sorted(params.items()))
    cpath = CACHE / f"{hashlib.sha1(raw.encode()).hexdigest()}.json"
    if cpath.is_file():
        try:
            blob = json.loads(cpath.read_text(encoding="utf-8"))
            for r in blob.get("data", []):
                pe_list.append({"date": r["date"], "symbol": sym, "PER": r["PER"]})
        except Exception:
            pass

pe_df = pd.DataFrame(pe_list)
pe_df["date"] = pd.to_datetime(pe_df["date"])
pe_df = pe_df[pe_df["PER"] > 0]
print(f"PE loaded: {len(pe_df)} rows, {pe_df['symbol'].nunique()} symbols")

# Market benchmark (equal-weight)
mkt = prices.groupby("date")["close"].mean().reset_index()
mkt["mkt_ret_60d"] = mkt["close"].pct_change(60)
mkt = mkt.set_index("date")

# Forward returns
prices = prices.sort_values(["symbol", "date"])
for h in [20, 40, 60]:
    prices[f"fwd_{h}d"] = prices.groupby("symbol")["close"].transform(lambda x: x.shift(-h) / x - 1)

# Merge
merged = pd.merge(pe_df[["date", "symbol", "PER"]],
                  prices[["date", "symbol"] + [f"fwd_{h}d" for h in [20, 40, 60]]],
                  on=["date", "symbol"], how="inner")
all_dates = sorted(merged["date"].unique())
print(f"Analysis: {all_dates[0].date()} to {all_dates[-1].date()}, {len(all_dates)} days")

# Regime classification
regime_ics = {"bull": {20: [], 40: [], 60: []},
              "bear": {20: [], 40: [], 60: []},
              "choppy": {20: [], 40: [], 60: []}}

for d in all_dates:
    if d not in mkt.index:
        continue
    ret60 = mkt.loc[d, "mkt_ret_60d"]
    if pd.isna(ret60):
        continue
    if ret60 > 0.05:
        regime = "bull"
    elif ret60 < -0.05:
        regime = "bear"
    else:
        regime = "choppy"

    day_data = merged[merged["date"] == d]
    for h in [20, 40, 60]:
        col = f"fwd_{h}d"
        valid = day_data.dropna(subset=[col])
        if len(valid) < 10:
            continue
        ic, _ = spearmanr(valid["PER"].rank(), valid[col].rank())
        regime_ics[regime][h].append(ic)

# Results
print()
print("=" * 60)
print("PE Factor Regime Stability Analysis")
print("=" * 60)

regime_labels = {"bull": "Bull  (mkt +5%+)", "bear": "Bear  (mkt -5%-)", "choppy": "Choppy (mkt +/-5%)"}

for regime in ["bull", "choppy", "bear"]:
    print(f"\n-- {regime_labels[regime]} --")
    for h, label in [(20, "1M"), (40, "2M"), (60, "3M")]:
        ics = regime_ics[regime][h]
        if ics:
            mean_ic = np.mean(ics)
            std_ic = np.std(ics)
            t = mean_ic / (std_ic / np.sqrt(len(ics))) if std_ic > 0 else 0
            print(f"  PE IC {label}: {mean_ic:.4f} (t={t:.2f}), n={len(ics)} days")

# Summary
print("\n-- Summary Table --")
print(f"{'Regime':<10} {'1M IC':>8} {'2M IC':>8} {'3M IC':>8} {'Days':>6}")
for regime in ["bull", "choppy", "bear"]:
    ic1 = np.mean(regime_ics[regime][20]) if regime_ics[regime][20] else 0
    ic2 = np.mean(regime_ics[regime][40]) if regime_ics[regime][40] else 0
    ic3 = np.mean(regime_ics[regime][60]) if regime_ics[regime][60] else 0
    nd = len(regime_ics[regime][60])
    print(f"{regime:<10} {ic1:>8.4f} {ic2:>8.4f} {ic3:>8.4f} {nd:>6}")

# Check: does PE IC DECAY or GROW with horizon within each regime?
print("\n-- IC Decay Pattern --")
for regime in ["bull", "choppy", "bear"]:
    ic1 = np.mean(regime_ics[regime][20]) if regime_ics[regime][20] else 0
    ic3 = np.mean(regime_ics[regime][60]) if regime_ics[regime][60] else 0
    trend = "accelerates" if abs(ic3) > abs(ic1) * 1.5 else "decays" if abs(ic3) < abs(ic1) * 0.5 else "stable"
    print(f"  {regime}: IC 1M->3M {ic1:.4f} -> {ic3:.4f} ({trend})")

# Save
out = {}
for regime in ["bull", "bear", "choppy"]:
    out[regime] = {str(h): {"mean_ic": round(np.mean(v), 4), "n": len(v)}
                   for h, v in regime_ics[regime].items() if v}
out["run_date"] = str(date.today())

out_path = os.path.join(os.path.dirname(__file__), '..', 'agents', 'sub',
                         'quant-researcher', 'memory', 'pe_regime_analysis.json')
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w") as f:
    json.dump(out, f, indent=2, default=str)
print(f"\nSaved to {out_path}")
