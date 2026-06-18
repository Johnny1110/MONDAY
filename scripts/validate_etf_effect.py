#!/usr/bin/env python3
"""Task #25: ETF inclusion/exclusion effect as short-term signal.
Event study: CAR around ETF rebalancing announcement dates.
"""
import sys, os, json
from datetime import date, timedelta
import numpy as np
import pandas as pd
from scipy.stats import ttest_ind

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))
from monday.ingest.base import fetch_json
from monday.config import settings

TOKEN = settings.finmind_token
CACHE = os.path.join(os.path.dirname(__file__), '..', 'engine', 'data', 'cache')
API = "https://api.finmindtrade.com/api/v4/data"

# ── ETF rebalancing events ──
EVENTS = [
    # === 2026 June ===
    ("0050", "2026-06-05", "2026-06-18",
     ["8046","3443","3665","4958"],
     ["6919","2002","1301","2207"]),
    ("0056", "2026-06-05", "2026-06-18",
     ["1513","4904","1303","2408","2344"],
     ["1477","6176","1319","2006"]),
    ("00878", "2026-05-25", "2026-06-01",
     ["2603","2618","2880","2887","2912"],
     ["1402","2324","2474","2449"]),
    ("00919", "2026-06-02", "2026-06-16",
     ["1210","1319","1402","2105","2347","2379","2382","2542","2597","2855","2883","3293","4938","5871","6890","8454","9910","9941"],
     ["1215","2027","2303","2404","2451","2609","3036","3211","3702","5347","6005","6176","6239","6278","6412","6757","8070","8422"]),
    
    # === 2025 Dec ===
    ("0056", "2025-12-05", "2025-12-22",
     ["2884","2645","3045"],
     ["5871"]),
    ("00919", "2025-12-02", "2025-12-17",
     ["2887","2357","1215","3036","3702","2027","2211","8422"],
     ["8299","2439","2547","2371","2520","2457","8411"]),
    
    # === 2025 Nov ===
    ("00878", "2025-11-25", "2025-12-01",
     ["2324","2301","2891"],
     ["2615","2606","2204"]),
    
    # === 2025 Jun ===
    ("0050", "2025-06-06", "2025-06-20",
     ["2382","3034","2327"],
     ["2002","1326"]),
    ("0056", "2025-06-06", "2025-06-20",
     ["2618","2606","2207","2204","2379"],
     ["2609","2383","3533","2548","2539"]),
    ("00878", "2025-05-26", "2025-06-02",
     ["2618","2887"],
     ["2301","2324"]),
    ("00919", "2025-05-27", "2025-06-17",
     ["2408","2881","2809","2344","3376","2610"],
     ["2353","3231","2324","2615","5876"]),
    
    # === 2024 Dec ===
    ("0050", "2024-12-06", "2024-12-20",
     ["2603","2327","3533"],
     ["1326","2105"]),
]

ALL_SYMBOLS = sorted(set(s for ev in EVENTS for s in (ev[3] + ev[4])))
print(f"Events: {len(EVENTS)}, symbols: {len(ALL_SYMBOLS)}")

# ── Pull prices ──
print("Pulling prices...")
rows = []
for sym in ALL_SYMBOLS:
    d = fetch_json(API, {'dataset': 'TaiwanStockPrice', 'data_id': sym,
        'start_date': '2024-01-01', 'end_date': '2026-06-16', 'token': TOKEN},
        cache_dir=CACHE, ttl=86400)
    for r in d.get('data', []):
        rows.append({'symbol': str(sym), 'date': r['date'], 'close': float(r['close'])})
prices = pd.DataFrame(rows)
prices['date'] = pd.to_datetime(prices['date'])
prices = prices.sort_values(['symbol', 'date'])

# Pre-compute daily returns for all stocks
prices['ret'] = prices.groupby('symbol')['close'].pct_change()

# Market return per day = average of all stock returns
mkt_ret = prices.groupby('date')['ret'].mean().rename('mkt_ret')
print(f"  {len(prices)} price rows, {prices['date'].nunique()} dates")

# ── CAR computation ──
def event_car(symbol, event_date_str, window=10):
    """CAR for symbol around event_date. Abnormal = stock_ret - market_ret."""
    ed = pd.Timestamp(event_date_str)
    sym_ret = prices[(prices['symbol'] == symbol) & 
                     (prices['date'] >= ed - timedelta(days=window+5)) &
                     (prices['date'] <= ed + timedelta(days=window+5))].set_index('date')
    if len(sym_ret) < 5:
        return None
    
    m = pd.DataFrame({'stock': sym_ret['ret'], 'mkt': mkt_ret})
    m['abn'] = m['stock'] - m['mkt']
    
    pre = m[(m.index >= ed - timedelta(days=window)) & (m.index < ed)]['abn']
    post = m[(m.index >= ed) & (m.index <= ed + timedelta(days=window))]['abn']
    
    return {
        'symbol': symbol, 'event_date': event_date_str,
        'car_pre': pre.sum() if len(pre) > 0 else np.nan,
        'car_post': post.sum() if len(post) > 0 else np.nan,
        'car_total': pre.sum() + post.sum() if len(pre) > 0 else np.nan,
        'n_pre': len(pre), 'n_post': len(post),
        'ret_pre_mean': pre.mean() if len(pre) > 0 else np.nan,
        'ret_post_mean': post.mean() if len(post) > 0 else np.nan,
    }

# ── Run ──
print("\nComputing CARs...")
cars = []
for etf, ad, ed, added, removed in EVENTS:
    for sym in added:
        c = event_car(sym, ad)
        if c: c.update({'etf': etf, 'type': 'inclusion', 'eff_date': ed}); cars.append(c)
    for sym in removed:
        c = event_car(sym, ad)
        if c: c.update({'etf': etf, 'type': 'exclusion', 'eff_date': ed}); cars.append(c)

df = pd.DataFrame(cars)
inc = df[df['type'] == 'inclusion']
exc = df[df['type'] == 'exclusion']
print(f"Inclusion: {len(inc)}, Exclusion: {len(exc)}")

# ── Results ──
print("\n" + "="*60)
print("RESULTS")
print("="*60)

for label, col in [('Pre-announce 10d', 'car_pre'), ('Post-announce 10d', 'car_post'), ('Announce ±10d', 'car_total')]:
    i = inc[col].dropna()
    e = exc[col].dropna()
    if len(i) >= 3 and len(e) >= 3:
        t, p = ttest_ind(i, e, equal_var=False)
        diff = i.mean() - e.mean()
        cohens_d = diff / np.sqrt((i.var() + e.var())/2)
        print(f"\n{label}:")
        print(f"  Incl: mean={i.mean():.4f}, median={i.median():.4f}, std={i.std():.4f}, n={len(i)}, >0={(i>0).mean():.1%}")
        print(f"  Excl: mean={e.mean():.4f}, median={e.median():.4f}, std={e.std():.4f}, n={len(e)}, >0={(e>0).mean():.1%}")
        print(f"  t={t:.3f}, p={p:.4f}, Cohen's d={cohens_d:.3f}")

# By ETF
print("\n── By ETF ──")
for etf_name in sorted(df['etf'].unique()):
    sub = df[df['etf'] == etf_name]
    si = sub[sub['type']=='inclusion']['car_total'].dropna()
    se = sub[sub['type']=='exclusion']['car_total'].dropna()
    if len(si)>=2 and len(se)>=2:
        t, p = ttest_ind(si, se, equal_var=False)
        print(f"  {etf_name}: incl={si.mean():.4f} (n={len(si)}), excl={se.mean():.4f} (n={len(se)}), diff={si.mean()-se.mean():.4f}, p={p:.3f}")

# 1519 case study
print("\n── Case: 1519 中興電 (0056 inclusion Jun 2026) ──")
zxd = df[(df['symbol']=='1513')]
for _, r in zxd.iterrows():
    print(f"  {r['etf']} {r['type']}: pre={r['car_pre']:.4f}, post={r['car_post']:.4f}, total={r['car_total']:.4f}")

# Verdict
print("\n" + "="*60)
print("VERDICT")
print("="*60)
i_total = inc['car_total'].dropna()
e_total = exc['car_total'].dropna()
if len(i_total) >= 10 and len(e_total) >= 10:
    t, p = ttest_ind(i_total, e_total, equal_var=False)
    diff = i_total.mean() - e_total.mean()
    print(f"Inclusion CAR (announce±10d): {i_total.mean():.4f} (n={len(i_total)}, >0={(i_total>0).mean():.1%})")
    print(f"Exclusion CAR (announce±10d): {e_total.mean():.4f} (n={len(e_total)}, >0={(e_total>0).mean():.1%})")
    print(f"Diff: {diff:.4f}, t={t:.3f}, p={p:.4f}")
    
    if p < 0.10 and diff > 0:
        print("\n→ PASS: ETF inclusion has significant positive CAR vs exclusion.")
    elif diff > 0 and p < 0.30:
        print("\n→ WEAK: Direction positive, not significant. Marginal overlay value.")
    else:
        print("\n→ FAIL: No evidence of ETF inclusion premium.")

# Save
out_path = os.path.join(os.path.dirname(__file__), '..', 'agents', 'sub',
                         'quant-researcher', 'memory', 'etf_effect_validation.json')
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w') as f:
    json.dump({
        'n_events': len(EVENTS), 'n_inclusion': len(inc), 'n_exclusion': len(exc),
        'inc_car_mean': round(i_total.mean(), 4) if len(i_total) > 0 else None,
        'exc_car_mean': round(e_total.mean(), 4) if len(e_total) > 0 else None,
        'run_date': str(date.today()),
    }, f, indent=2, default=str)
print(f"Saved to {out_path}")
