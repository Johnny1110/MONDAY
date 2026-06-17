#!/usr/bin/env python3
"""Task #9: OOS validation of three heavy-electrical sector hypotheses.
Computes all factors from raw FinMind data (prices, PE, revenue, balance sheet,
institutional flow), runs purged walk-forward CV.

H1: PE < 40x → rank IC with forward 20d/40d/60d returns
H2: foreign_streak ≥ 5 AND rev YoY > 20% → hit rate for 電機機械+電器電纜
H3: Contract liabilities QoQ > 10% AND dist_high_60d > -0.15 → predictive power for next-q revenue
"""
import sys, os, json, time
from datetime import date, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))
from monday.ingest.base import fetch_json
from monday.config import settings

TOKEN = settings.finmind_token
CACHE = os.path.join(os.path.dirname(__file__), '..', 'engine', 'data', 'cache')
API = "https://api.finmindtrade.com/api/v4/data"

HEAVY_CORE = ['1503', '1504', '1513', '1514', '1519', '2371']
START = "2022-01-01"
END = "2026-06-16"

# ── Data fetching ────────────────────────────────────────────────────────────

def _pull(dataset, symbols, start=START, end=END):
    """Pull FinMind dataset for list of symbols. Returns DataFrame."""
    rows = []
    for sym in symbols:
        try:
            data = fetch_json(API,
                {'dataset': dataset, 'data_id': sym,
                 'start_date': start, 'end_date': end, 'token': TOKEN},
                cache_dir=CACHE, ttl=86400)
            if data.get('data'):
                for r in data['data']:
                    r['_symbol'] = str(sym)
                rows.extend(data['data'])
        except Exception as e:
            print(f"  WARN: {dataset} pull failed for {sym}: {e}")
    return pd.DataFrame(rows)


def fetch_all_data():
    """Fetch all needed data from FinMind."""
    from monday.ingest.finmind import fetch_stock_info
    
    # Sectors
    sectors = fetch_stock_info(token=TOKEN, cache_dir=CACHE)
    heavy_sector = [s for s, sec in sectors.items() if sec in ('電機機械', '電器電纜')]
    all_stocks = sorted(set(HEAVY_CORE + heavy_sector))
    print(f"Target stocks: {len(all_stocks)} (core={len(HEAVY_CORE)}, sector={len(heavy_sector)})")
    
    print("Pulling prices..."); t0 = time.time()
    prices = _pull('TaiwanStockPrice', all_stocks)
    print(f"  {len(prices)} rows ({time.time()-t0:.1f}s)")
    
    print("Pulling PE..."); t0 = time.time()
    pe = _pull('TaiwanStockPER', HEAVY_CORE)
    print(f"  {len(pe)} rows ({time.time()-t0:.1f}s)")
    
    print("Pulling monthly revenue..."); t0 = time.time()
    rev = _pull('TaiwanStockMonthRevenue', all_stocks)
    print(f"  {len(rev)} rows ({time.time()-t0:.1f}s)")
    
    print("Pulling balance sheet..."); t0 = time.time()
    bs = _pull('TaiwanStockBalanceSheet', HEAVY_CORE)
    print(f"  {len(bs)} rows ({time.time()-t0:.1f}s)")
    
    # Contract liabilities
    cl = bs[bs['type'] == 'CurrentContractLiabilities'].copy()
    cl = cl.rename(columns={'_symbol': 'symbol', 'date': 'date'})
    print(f"  Contract liabilities rows: {len(cl)}")
    
    print("Pulling institutional chips..."); t0 = time.time()
    inst = _pull('TaiwanStockInstitutionalInvestorsBuySell', all_stocks)
    print(f"  {len(inst)} rows ({time.time()-t0:.1f}s)")
    
    return {
        'prices': prices, 'pe': pe, 'revenue': rev,
        'contract_liabilities': cl, 'institutional': inst,
        'sectors': sectors, 'all_stocks': all_stocks,
    }


# ── Factor computation ───────────────────────────────────────────────────────

def compute_forward_returns(prices_df):
    """Add forward return columns to daily prices."""
    df = prices_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.rename(columns={'_symbol': 'symbol'})
    df = df.sort_values(['symbol', 'date'])
    for h in [20, 40, 60]:
        df[f'fwd_{h}d'] = df.groupby('symbol')['close'].transform(
            lambda x: x.shift(-h) / x - 1)
    return df

def compute_dist_high(prices_df):
    """Compute dist_high_60d from prices. FinMind uses 'max' for high."""
    df = prices_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.rename(columns={'_symbol': 'symbol', 'max': 'high'})
    df = df.sort_values(['symbol', 'date'])
    df['high_60d'] = df.groupby('symbol')['high'].transform(
        lambda x: x.rolling(60, min_periods=10).max())
    df['dist_high_60d'] = (df['close'] / df['high_60d']) - 1
    return df[['date', 'symbol', 'close', 'dist_high_60d']]

def compute_foreign_streak(inst_df):
    """Compute foreign_streak from institutional flow data.
    Foreign = Foreign_Investor + Foreign_Dealer_Self."""
    df = inst_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df['_symbol'] = df['_symbol'].astype(str)
    foreign_names = {'Foreign_Investor', 'Foreign_Dealer_Self'}
    fdf = df[df['name'].isin(foreign_names)].copy()
    fdf['net'] = fdf['buy'].astype(float) - fdf['sell'].astype(float)
    daily = fdf.groupby(['date', '_symbol'])['net'].sum().reset_index()
    daily = daily.sort_values(['_symbol', 'date'])
    daily['sign'] = np.sign(daily['net'])
    # Compute streak as consecutive same-sign days
    streaks = []
    for sym, grp in daily.groupby('_symbol'):
        grp = grp.sort_values('date')
        streak = 0
        prev_sign = 0
        sym_streaks = []
        for _, row in grp.iterrows():
            s = int(row['sign'])
            if s == 0:
                streak = 0
            elif s == prev_sign:
                streak += s  # +1 for buy, -1 for sell
            else:
                streak = s
            prev_sign = s
            sym_streaks.append({'date': row['date'], 'symbol': sym, 'foreign_streak': streak})
        streaks.extend(sym_streaks)
    return pd.DataFrame(streaks)

def prepare_revenue(rev_df):
    """Prepare monthly revenue with YoY growth."""
    df = rev_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df['_symbol'] = df['_symbol'].astype(str)
    df = df.rename(columns={'_symbol': 'symbol'})
    # Actual reporting period
    df['period'] = df.apply(
        lambda r: pd.Timestamp(year=int(r['revenue_year']), month=int(r['revenue_month']), day=1),
        axis=1)
    df = df.sort_values(['symbol', 'period'])
    # YoY = same month last year
    # Compute 12-month trailing sum for each month
    df['rev_ttm'] = df.groupby('symbol')['revenue'].transform(
        lambda x: x.rolling(12, min_periods=1).sum())
    # YoY on TTM basis
    df['rev_ttm_yoy'] = df.groupby('symbol')['rev_ttm'].transform(lambda x: x.pct_change(12))
    return df


# ── Walk-forward utilities ──────────────────────────────────────────────────

def walk_forward_folds(dates, n_train_quarters=4, embargo_days=20):
    """Generate (train_end, test_start, test_end) tuples for purged walk-forward.
    Each fold: train on quarters [0..i), test on quarter i, with embargo gap."""
    quarters = pd.date_range(dates.min(), dates.max(), freq='QE')
    folds = []
    for i in range(n_train_quarters + 1, len(quarters)):
        train_end = quarters[i-1]
        test_start = quarters[i-1] + timedelta(days=embargo_days + 1)
        test_end = quarters[i]
        folds.append((train_end, test_start, test_end))
    return folds


# ── H1: PE mean reversion ───────────────────────────────────────────────────

def validate_h1(pe_df, prices_df):
    """H1: PE < 40x heavy-electric → rank IC with forward returns.
    Daily cross-sectional rank IC, aggregated across walk-forward folds."""
    print("\n" + "="*60)
    print("H1: PE Mean Reversion")
    print("="*60)
    
    # Prepare PE
    pe = pe_df.copy()
    pe['date'] = pd.to_datetime(pe['date'])
    pe['_symbol'] = pe['_symbol'].astype(str)
    pe = pe.rename(columns={'_symbol': 'symbol'})
    pe = pe[pe['symbol'].isin(HEAVY_CORE)]
    pe = pe[['date', 'symbol', 'PER']].dropna()
    pe = pe[pe['PER'] > 0]
    
    # Prepare prices with forward returns
    prices = compute_forward_returns(prices_df)
    prices = prices[prices['symbol'].isin(HEAVY_CORE)]
    
    # Merge
    merged = pd.merge(pe, prices[['date', 'symbol'] + [f'fwd_{h}d' for h in [20,40,60]]],
                      on=['date', 'symbol'], how='inner')
    
    # Walk-forward folds
    all_dates = pd.DatetimeIndex(sorted(merged['date'].unique()))
    folds = walk_forward_folds(all_dates, n_train_quarters=4)
    print(f"  Walk-forward folds: {len(folds)}")
    
    results = {}
    for horizon, label in [(20, '1M'), (40, '2M'), (60, '3M')]:
        col = f'fwd_{horizon}d'
        ic_daily = []
        
        for fold_i, (train_end, test_start, test_end) in enumerate(folds):
            test = merged[(merged['date'] >= test_start) & (merged['date'] <= test_end)]
            for d, day_data in test.groupby('date'):
                valid = day_data[col].notna()
                if valid.sum() < 2:
                    continue
                # Lower PE = better → negative correlation with PE means positive IC
                ic, _ = spearmanr(day_data.loc[valid, 'PER'], day_data.loc[valid, col])
                ic_daily.append(-ic)
        
        if ic_daily:
            mean_ic = np.mean(ic_daily)
            ic_std = np.std(ic_daily)
            ic_ir = mean_ic / ic_std if ic_std > 0 else 0
            hit_rate = sum(1 for x in ic_daily if x > 0) / len(ic_daily)
            tstat = mean_ic / (ic_std / np.sqrt(len(ic_daily))) if ic_std > 0 else 0
            results[label] = {
                'mean_rank_IC': round(mean_ic, 4),
                'IC_IR': round(ic_ir, 4),
                'hit_rate': round(hit_rate, 4),
                'n_days': len(ic_daily),
                't_stat': round(tstat, 3),
            }
            print(f"  {label}: IC={mean_ic:.4f}, IR={ic_ir:.3f}, hit={hit_rate:.2%}, "
                  f"t={tstat:.2f}, n_days={len(ic_daily)}")
        else:
            results[label] = {'error': 'no valid daily ICs'}
    
    return results


# ── H2: Foreign streak + Revenue YoY ────────────────────────────────────────

def validate_h2(prices_df, inst_df, rev_df, sectors):
    """H2: foreign_streak ≥ 5 AND rev TTM YoY > 20% → hit rate."""
    print("\n" + "="*60)
    print("H2: Foreign Streak + Revenue YoY")
    print("="*60)
    
    target = [s for s, sec in sectors.items() if sec in ('電機機械', '電器電纜')]
    print(f"  Target sector: {len(target)} stocks")
    
    # Compute factors
    prices = compute_forward_returns(prices_df)
    prices = prices[prices['symbol'].isin(target)]
    
    fstreak = compute_foreign_streak(inst_df)
    fstreak = fstreak[fstreak['symbol'].isin(target)]
    
    rev = prepare_revenue(rev_df)
    rev = rev[rev['symbol'].isin(target)]
    
    # Build daily signal panel
    all_dates = sorted(prices['date'].unique())
    
    # Pre-compute: for each symbol, for each date, get foreign_streak and rev_yoy
    # Create lookup dicts for speed
    fs_lookup = {}
    for sym in target:
        sym_fs = fstreak[fstreak['symbol'] == sym].set_index('date').sort_index()
        if len(sym_fs) > 0:
            fs_lookup[sym] = sym_fs['foreign_streak']
    
    rev_lookup = {}
    for sym in target:
        sym_rev = rev[rev['symbol'] == sym].sort_values('period')
        if len(sym_rev) > 0:
            rev_lookup[sym] = sym_rev.set_index('period')[['rev_ttm_yoy']]
    
    # Walk-forward folds
    dates_idx = pd.DatetimeIndex(all_dates)
    folds = walk_forward_folds(dates_idx, n_train_quarters=4)
    
    results = {}
    for horizon, label in [(20, '1M'), (40, '2M'), (60, '3M')]:
        col = f'fwd_{horizon}d'
        hit_rates = []
        mean_rets = []
        signal_counts = []
        
        for fold_i, (train_end, test_start, test_end) in enumerate(folds):
            test_dates = [d for d in all_dates if test_start <= d <= test_end]
            test_hits = []
            test_rets = []
            
            for d in test_dates:
                for sym in target:
                    # Get foreign_streak at date d
                    fs = None
                    if sym in fs_lookup:
                        before = fs_lookup[sym][fs_lookup[sym].index <= d]
                        if len(before) > 0:
                            fs = before.iloc[-1]
                    
                    # Get latest revenue YoY
                    ry = None
                    if sym in rev_lookup:
                        by = rev_lookup[sym][rev_lookup[sym].index <= d]
                        if len(by) > 0:
                            ry = by['rev_ttm_yoy'].iloc[-1]
                    
                    if fs is not None and ry is not None and fs >= 5 and ry > 0.20:
                        price_row = prices[(prices['symbol'] == sym) & (prices['date'] == d)]
                        if len(price_row) > 0:
                            ret = price_row[col].iloc[0]
                            if pd.notna(ret):
                                test_hits.append(ret > 0)
                                test_rets.append(ret)
            
            if len(test_hits) >= 3:
                hit_rates.append(np.mean(test_hits))
                mean_rets.append(np.mean(test_rets))
                signal_counts.append(len(test_hits))
        
        if hit_rates:
            results[label] = {
                'mean_hit_rate': round(np.mean(hit_rates), 4),
                'hit_rate_std': round(np.std(hit_rates), 4),
                'mean_fwd_return': round(np.mean(mean_rets), 4),
                'avg_signals_per_fold': round(np.mean(signal_counts), 1),
                'n_folds': len(hit_rates),
            }
            print(f"  {label}: hit={np.mean(hit_rates):.2%}, fwd_ret={np.mean(mean_rets):.4f}, "
                  f"signals/fold={np.mean(signal_counts):.0f}, folds={len(hit_rates)}")
        else:
            results[label] = {'error': 'insufficient signals'}
    
    return results


# ── H3: Contract liabilities QoQ ─────────────────────────────────────────────

def validate_h3(cl_df, prices_df, rev_df):
    """H3: Contract liabilities QoQ > 10% AND dist_high_60d > -0.15
    → rank-IC with next quarter revenue growth."""
    print("\n" + "="*60)
    print("H3: Contract Liabilities QoQ + dist_high_60d")
    print("="*60)
    
    # Prepare CL
    cl = cl_df.copy()
    cl['date'] = pd.to_datetime(cl['date'])
    cl['symbol'] = cl['symbol'].astype(str)
    cl = cl[cl['symbol'].isin(HEAVY_CORE)]
    cl = cl.sort_values(['symbol', 'date'])
    cl['cl_qoq'] = cl.groupby('symbol')['value'].transform(lambda x: x.pct_change())
    
    # Prepare dist_high_60d
    dh = compute_dist_high(prices_df)
    dh = dh[dh['symbol'].isin(HEAVY_CORE)]
    
    # Prepare quarterly revenue
    rev = prepare_revenue(rev_df)
    rev = rev[rev['symbol'].isin(HEAVY_CORE)]
    rev['quarter'] = rev['period'].dt.to_period('Q')
    qrev = rev.groupby(['symbol', 'quarter'])['revenue'].sum().reset_index()
    qrev = qrev.sort_values(['symbol', 'quarter'])
    qrev['rev_qoq'] = qrev.groupby('symbol')['revenue'].transform(lambda x: x.pct_change())
    qrev['next_q_rev_qoq'] = qrev.groupby('symbol')['rev_qoq'].shift(-1)
    qrev['next_q_rev_yoy'] = qrev.groupby('symbol')['revenue'].transform(
        lambda x: x.pct_change(4)).shift(-4)
    qrev['q_end'] = qrev['quarter'].apply(lambda q: q.end_time).dt.date
    qrev['q_end'] = pd.to_datetime(qrev['q_end'])
    
    # Merge CL with quarterly rev
    merged = pd.merge(cl, qrev, left_on=['symbol', 'date'], right_on=['symbol', 'q_end'], 
                      how='inner', suffixes=('_cl', ''))
    
    # Add dist_high_60d: for each (symbol, q_end), find closest daily dist_high
    dh_vals = []
    for _, row in merged.iterrows():
        sym = row['symbol']
        d = row['date']
        sym_dh = dh[(dh['symbol'] == sym) & (dh['date'] <= d)]
        if len(sym_dh) > 0:
            dh_vals.append(sym_dh.iloc[-1]['dist_high_60d'])
        else:
            dh_vals.append(None)
    merged['dist_high_60d'] = dh_vals
    
    # Walk-forward folds by quarter
    all_qends = sorted(merged['date'].unique())
    q_folds = walk_forward_folds(pd.DatetimeIndex(all_qends), n_train_quarters=4)
    
    results = {}
    for target, label in [('next_q_rev_qoq', 'Next-Q Revenue QoQ'),
                           ('next_q_rev_yoy', 'Next-Q Revenue YoY')]:
        ic_list = []
        
        for fold_i, (train_end, test_start, test_end) in enumerate(q_folds):
            test = merged[(merged['date'] >= test_start) & (merged['date'] <= test_end)]
            filtered = test[(test['cl_qoq'] > 0.10) & (test['dist_high_60d'] > -0.15)]
            valid = filtered.dropna(subset=[target, 'cl_qoq'])
            
            if len(valid) >= 3:
                ic, pv = spearmanr(valid['cl_qoq'], valid[target])
                ic_list.append(ic)
        
        if ic_list:
            mean_ic = np.mean(ic_list)
            results[label] = {
                'mean_IC': round(mean_ic, 4),
                'IC_std': round(np.std(ic_list), 4),
                'n_folds': len(ic_list),
                't_stat': round(mean_ic / (np.std(ic_list) / np.sqrt(len(ic_list))), 3) if np.std(ic_list) > 0 else 0,
            }
            print(f"  {label}: IC={mean_ic:.4f}, folds={len(ic_list)}")
        else:
            results[label] = {'error': 'insufficient data'}
    
    # Unconditional baseline
    all_valid = merged.dropna(subset=['cl_qoq', 'next_q_rev_qoq'])
    if len(all_valid) >= 3:
        ic_base, pv = spearmanr(all_valid['cl_qoq'], all_valid['next_q_rev_qoq'])
        print(f"  Baseline (unconditioned CL QoQ): n={len(all_valid)}, IC={ic_base:.4f}")
    
    return results


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Task #9: Heavy Electrical Sector — OOS Validation")
    print(f"Run date: {date.today()}")
    print("=" * 60)
    
    # Fetch all data
    data = fetch_all_data()
    
    # Run validations
    h1 = validate_h1(data['pe'], data['prices'])
    h2 = validate_h2(data['prices'], data['institutional'], data['revenue'], data['sectors'])
    h3 = validate_h3(data['contract_liabilities'], data['prices'], data['revenue'])
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY — Walk-Forward OOS Results")
    print("=" * 60)
    
    verdicts = {}
    
    print("\nH1: PE < 40x Mean Reversion (rank IC with forward returns)")
    for k, v in (h1 or {}).items():
        if 'error' in v:
            print(f"  {k}: ERROR — {v['error']}")
        else:
            print(f"  {k}: IC={v['mean_rank_IC']}, IR={v['IC_IR']}, "
                  f"hit_rate={v['hit_rate']:.2%}, t={v['t_stat']}, n_days={v['n_days']}")
    # Verdict: positive if mean IC > 0 and t-stat > 1.5
    ic1 = h1.get('2M', {}).get('mean_rank_IC', 0) if h1 else 0
    t1 = h1.get('2M', {}).get('t_stat', 0) if h1 else 0
    verdicts['H1'] = 'PASS' if ic1 > 0.02 and t1 > 1.5 else 'WEAK' if ic1 > 0 else 'FAIL'
    
    print("\nH2: foreign_streak ≥ 5 + rev YoY > 20% (hit rate)")
    for k, v in (h2 or {}).items():
        if 'error' in v:
            print(f"  {k}: ERROR — {v['error']}")
        else:
            print(f"  {k}: hit_rate={v['mean_hit_rate']:.2%}, fwd_ret={v['mean_fwd_return']:.4f}, "
                  f"signals/fold={v['avg_signals_per_fold']:.0f}, folds={v['n_folds']}")
    hr2 = h2.get('2M', {}).get('mean_hit_rate', 0) if h2 else 0
    verdicts['H2'] = 'PASS' if hr2 > 0.55 else 'WEAK' if hr2 > 0.50 else 'FAIL'
    
    print("\nH3: Contract Liabilities QoQ > 10% + dist_high_60d > -0.15 (predictive IC)")
    for k, v in (h3 or {}).items():
        if 'error' in v:
            print(f"  {k}: ERROR — {v['error']}")
        else:
            print(f"  {k}: IC={v['mean_IC']}, folds={v['n_folds']}, t={v['t_stat']}")
    ic3 = h3.get('Next-Q Revenue QoQ', {}).get('mean_IC', 0) if h3 else 0
    verdicts['H3'] = 'PASS' if ic3 > 0.10 else 'WEAK' if ic3 > 0.05 else 'FAIL'
    
    print(f"\nPreliminary Verdicts: {verdicts}")
    
    # Save results
    out_path = os.path.join(os.path.dirname(__file__), '..', 'agents', 'sub', 
                             'quant-researcher', 'memory', 'h1_h2_h3_validation.json')
    output = {
        'h1': {k: v for k, v in (h1 or {}).items()},
        'h2': {k: v for k, v in (h2 or {}).items()},
        'h3': {k: v for k, v in (h3 or {}).items()},
        'verdicts': verdicts,
        'run_date': str(date.today()),
        'method': 'purged walk-forward CV, 4-quarter training window, 20d embargo',
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")
    
    return verdicts

if __name__ == '__main__':
    main()
