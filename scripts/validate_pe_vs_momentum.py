#!/usr/bin/env python3
"""Task #12: Cross-sectional rank correlation between PE and momentum factors.
Determines if PE is an independent factor or just a mom_60d/mom_120d proxy.
"""
import sys, os, json, time
from datetime import date
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))
from monday.ingest.base import fetch_json
from monday.config import settings

TOKEN = settings.finmind_token
CACHE = os.path.join(os.path.dirname(__file__), '..', 'engine', 'data', 'cache')
API = "https://api.finmindtrade.com/api/v4/data"
PRICES_PATH = os.path.join(os.path.dirname(__file__), '..', 'engine', 'data', 'snapshots', 'prices.parquet')

# Use broader universe: top liquidity stocks from platform universe
# Start with what's in the features + add FinMind PE
UNIVERSE_SIZE = 450


def load_universe_stocks():
    """Get universe symbols from platform prices parquet."""
    prices = pd.read_parquet(PRICES_PATH)
    symbols = sorted(prices['symbol'].unique())
    print(f"Universe: {len(symbols)} symbols from price snapshot")
    return symbols


def pull_pe_bulk(symbols):
    """Pull PE data for universe symbols from FinMind."""
    all_rows = []
    batch_size = 20
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        for sym in batch:
            try:
                data = fetch_json(API,
                    {'dataset': 'TaiwanStockPER', 'data_id': sym,
                     'start_date': '2022-01-01', 'end_date': '2026-06-16',
                     'token': TOKEN},
                    cache_dir=CACHE, ttl=86400)
                if data.get('data'):
                    for r in data['data']:
                        all_rows.append({
                            'date': r['date'],
                            'symbol': str(sym),
                            'PER': r['PER'],
                            'PBR': r.get('PBR'),
                            'dividend_yield': r.get('dividend_yield'),
                        })
            except Exception as e:
                pass
        if (i // batch_size + 1) % 10 == 0:
            print(f"  PE pulled {i+len(batch)}/{len(symbols)} symbols...")
    return pd.DataFrame(all_rows)


def compute_momentum(prices_df):
    """Compute mom_60d and mom_120d from price snapshot."""
    df = prices_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['symbol', 'date'])
    for h, label in [(60, 'mom_60d'), (120, 'mom_120d')]:
        df[label] = df.groupby('symbol')['close'].transform(
            lambda x: x / x.shift(h) - 1)
    return df


def main():
    print("=" * 60)
    print("Task #12: PE vs Momentum Cross-Sectional Rank Correlation")
    print("=" * 60)
    
    # Load universe
    symbols = load_universe_stocks()
    
    # Pull PE data (cached)
    print("Pulling PE data for universe..."); t0 = time.time()
    pe_df = pull_pe_bulk(symbols)
    pe_df['date'] = pd.to_datetime(pe_df['date'])
    pe_df = pe_df[pe_df['PER'] > 0].dropna(subset=['PER'])
    print(f"  {len(pe_df)} PE rows, {pe_df['symbol'].nunique()} symbols "
          f"({time.time()-t0:.1f}s)")
    
    # Compute momentum from prices
    print("Computing momentum factors...")
    prices = pd.read_parquet(PRICES_PATH)
    prices = compute_momentum(prices)
    
    # Merge PE with momentum on date+symbol
    merged = pd.merge(
        pe_df[['date', 'symbol', 'PER']],
        prices[['date', 'symbol', 'mom_60d', 'mom_120d']],
        on=['date', 'symbol'], how='inner'
    )
    merged = merged.dropna(subset=['mom_60d', 'mom_120d'])
    print(f"  Merged: {len(merged)} rows across {merged['date'].nunique()} days")
    
    if len(merged) < 100:
        print("ERROR: insufficient merged data")
        return
    
    # ── Daily cross-sectional rank correlation ──
    all_dates = sorted(merged['date'].unique())
    
    # For each day, compute rank correlation between PE and each momentum factor
    daily_corrs = []
    for d in all_dates:
        day_data = merged[merged['date'] == d]
        if len(day_data) < 10:
            continue
        
        pe_rank = day_data['PER'].rank()
        
        row = {'date': d, 'n_stocks': len(day_data)}
        for col in ['mom_60d', 'mom_120d']:
            mom_rank = day_data[col].rank()
            r, p = spearmanr(pe_rank, mom_rank)
            row[f'r_{col}'] = r
            row[f'p_{col}'] = p
        daily_corrs.append(row)
    
    corr_df = pd.DataFrame(daily_corrs)
    
    # ── Results ──
    print("\n" + "=" * 60)
    print("PE vs Momentum: Cross-Sectional Rank Correlations")
    print("=" * 60)
    
    results = {}
    for col, label in [('mom_60d', '3M Momentum'), ('mom_120d', '6M Momentum')]:
        r_col = f'r_{col}'
        valid = corr_df[r_col].dropna()
        
        mean_r = valid.mean()
        std_r = valid.std()
        t_stat = mean_r / (std_r / np.sqrt(len(valid))) if std_r > 0 else 0
        
        # Also compute time-series stability: correlation of PE rank with mom rank over time
        # Check what fraction of days have |r| < 0.5 (PE would be independent)
        pct_low_corr = (valid.abs() < 0.5).mean()
        pct_high_corr = (valid.abs() > 0.7).mean()
        
        results[label] = {
            'mean_rank_corr': round(mean_r, 4),
            'std': round(std_r, 4),
            't_stat': round(t_stat, 3),
            'n_days': len(valid),
            'pct_abs_corr_below_0.5': round(pct_low_corr, 4),
            'pct_abs_corr_above_0.7': round(pct_high_corr, 4),
        }
        print(f"  {label}: mean_r={mean_r:.4f}, σ={std_r:.4f}, "
              f"t={t_stat:.2f}, days={len(valid)}")
        print(f"    |r|<0.5: {pct_low_corr:.1%}, |r|>0.7: {pct_high_corr:.1%}")
    
    # ── Also check: PE vs PE itself over time (autocorrelation of PE signal) ──
    # And PE rank IC with forward returns (confirm H1 finding on broader universe)
    print("\n── Bonus: PE Rank IC with forward returns (full universe) ──")
    prices['date'] = pd.to_datetime(prices['date'])
    prices = prices.sort_values(['symbol', 'date'])
    for h in [20, 40, 60]:
        prices[f'fwd_{h}d'] = prices.groupby('symbol')['close'].transform(
            lambda x: x.shift(-h) / x - 1)
    
    pe_merged = pd.merge(
        pe_df[['date', 'symbol', 'PER']],
        prices[['date', 'symbol', 'close'] + [f'fwd_{h}d' for h in [20,40,60]]],
        on=['date', 'symbol'], how='inner'
    )
    
    for h, label in [(20, '1M'), (40, '2M'), (60, '3M')]:
        col = f'fwd_{h}d'
        ics = []
        for d in all_dates:
            day = pe_merged[pe_merged['date'] == d]
            valid = day.dropna(subset=[col])
            if len(valid) < 10:
                continue
            ic, _ = spearmanr(valid['PER'].rank(), valid[col].rank())
            ics.append(ic)
        if ics:
            mean_ic = np.mean(ics)
            t_ic = mean_ic / (np.std(ics) / np.sqrt(len(ics))) if np.std(ics) > 0 else 0
            print(f"  PE rank IC {label}: {mean_ic:.4f} (t={t_ic:.2f}, n={len(ics)} days)")
    
    # ── Verdict ──
    print("\n── Verdict ──")
    r_60 = results['3M Momentum']['mean_rank_corr']
    pct_low = results['3M Momentum']['pct_abs_corr_below_0.5']
    
    if abs(r_60) < 0.3 and pct_low > 0.7:
        verdict = "PE is LARGELY INDEPENDENT of momentum → worth adding as separate factor"
    elif abs(r_60) < 0.5:
        verdict = "PE is MODERATELY correlated with momentum → may add incremental value, investigate further"
    elif abs(r_60) > 0.7:
        verdict = "PE is HIGHLY correlated with momentum → no incremental information, skip"
    else:
        verdict = f"PE-momentum correlation is moderate ({r_60:.3f}) → borderline, consider conditional use"
    
    print(f"  {verdict}")
    
    # ── Save ──
    out_path = os.path.join(os.path.dirname(__file__), '..', 'agents', 'sub',
                             'quant-researcher', 'memory', 'pe_vs_momentum.json')
    output = {
        'results': results,
        'verdict': verdict,
        'run_date': str(date.today()),
        'universe_size': len(symbols),
        'n_days': len(all_dates),
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    
    return results, verdict


if __name__ == '__main__':
    main()
