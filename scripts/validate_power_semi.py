#!/usr/bin/env python3
"""Task #24: OOS validation of power semiconductor hypotheses.
H1: Gross margin QoQ > 2pp + rev QoQ > 5% → excess returns
H2: Institutional streak + rev peak → hit rate
H3: Rev CAGR > 15% + 40 < RSI < 70 → predictive IC
"""
import sys, os, json, time
from datetime import date, timedelta
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))
from monday.ingest.base import fetch_json
from monday.config import settings

TOKEN = settings.finmind_token
CACHE = os.path.join(os.path.dirname(__file__), '..', 'engine', 'data', 'cache')
API = "https://api.finmindtrade.com/api/v4/data"

POWER_SEMI = ['2481', '8261', '2351', '6415', '2342', '3016', '6525', '2303']
START = "2021-01-01"
END = "2026-06-16"


# ── Data fetching ────────────────────────────────────────────────────────────

def pull_data():
    """Pull all needed FinMind data for power semi stocks."""
    data = {}
    
    # Prices
    print("Pulling prices..."); t0 = time.time()
    rows = []
    for sym in POWER_SEMI:
        d = fetch_json(API, {'dataset': 'TaiwanStockPrice', 'data_id': sym,
            'start_date': START, 'end_date': END, 'token': TOKEN}, cache_dir=CACHE, ttl=86400)
        for r in d.get('data', []):
            r['_symbol'] = sym
        rows.extend(d.get('data', []))
    data['prices'] = pd.DataFrame(rows)
    print(f"  {len(data['prices'])} rows ({time.time()-t0:.1f}s)")
    
    # Financial statements (quarterly: Revenue, GrossProfit, OperatingIncome)
    print("Pulling financial statements..."); t0 = time.time()
    fs_rows = []
    for sym in POWER_SEMI:
        d = fetch_json(API, {'dataset': 'TaiwanStockFinancialStatements', 'data_id': sym,
            'start_date': START, 'end_date': END, 'token': TOKEN}, cache_dir=CACHE, ttl=86400)
        for r in d.get('data', []):
            fs_rows.append({'date': r['date'], 'symbol': sym, 'type': r['type'], 'value': r['value']})
    data['fs'] = pd.DataFrame(fs_rows)
    print(f"  {len(data['fs'])} rows ({time.time()-t0:.1f}s)")
    
    # Monthly revenue
    print("Pulling monthly revenue..."); t0 = time.time()
    rev_rows = []
    for sym in POWER_SEMI:
        d = fetch_json(API, {'dataset': 'TaiwanStockMonthRevenue', 'data_id': sym,
            'start_date': START, 'end_date': END, 'token': TOKEN}, cache_dir=CACHE, ttl=86400)
        for r in d.get('data', []):
            rev_rows.append({'date': r['date'], 'symbol': sym,
                           'revenue': r['revenue'], 'rmonth': int(r['revenue_month']),
                           'ryear': int(r['revenue_year'])})
    data['mrev'] = pd.DataFrame(rev_rows)
    print(f"  {len(data['mrev'])} rows ({time.time()-t0:.1f}s)")
    
    # Institutional flow
    print("Pulling institutional flow..."); t0 = time.time()
    inst_rows = []
    for sym in POWER_SEMI:
        d = fetch_json(API, {'dataset': 'TaiwanStockInstitutionalInvestorsBuySell',
            'data_id': sym, 'start_date': START, 'end_date': END, 'token': TOKEN},
            cache_dir=CACHE, ttl=86400)
        for r in d.get('data', []):
            r['_symbol'] = sym
        inst_rows.extend(d.get('data', []))
    data['inst'] = pd.DataFrame(inst_rows)
    print(f"  {len(data['inst'])} rows ({time.time()-t0:.1f}s)")
    
    return data


# ── Factor computation ──────────────────────────────────────────────────────

def compute_price_factors(prices_df):
    """Forward returns + RSI from daily prices."""
    df = prices_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.rename(columns={'_symbol': 'symbol', 'max': 'high', 'min': 'low'})
    df = df.sort_values(['symbol', 'date'])
    for h in [20, 40, 60]:
        df[f'fwd_{h}d'] = df.groupby('symbol')['close'].transform(lambda x: x.shift(-h)/x - 1)
    # RSI 14
    delta = df.groupby('symbol')['close'].transform(lambda x: x.diff())
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.groupby(df['symbol']).transform(lambda x: x.rolling(14).mean())
    avg_loss = loss.groupby(df['symbol']).transform(lambda x: x.rolling(14).mean())
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi_14'] = 100 - 100/(1 + rs)
    return df

def compute_institutional_streaks(inst_df):
    """Foreign streak + invtrust streak per symbol per date."""
    df = inst_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df['_symbol'] = df['_symbol'].astype(str)
    foreign_names = {'Foreign_Investor', 'Foreign_Dealer_Self'}
    
    def compute_streak(grp_df, name_filter):
        sub = grp_df[grp_df['name'].isin(name_filter)].copy()
        sub['net'] = sub['buy'].astype(float) - sub['sell'].astype(float)
        daily = sub.groupby('date')['net'].sum().reset_index().sort_values('date')
        daily['sign'] = np.sign(daily['net'])
        streak, prev = 0, 0
        result = []
        for _, row in daily.iterrows():
            s = int(row['sign'])
            streak = streak + s if s == prev and s != 0 else s
            prev = s
            result.append({'date': row['date'], 'streak': streak})
        return pd.DataFrame(result)
    
    all_streaks = []
    for sym, grp in df.groupby('_symbol'):
        f_streak = compute_streak(grp, foreign_names).rename(columns={'streak': 'foreign_streak'})
        i_streak = compute_streak(grp, {'Investment_Trust'}).rename(columns={'streak': 'invtrust_streak'})
        merged = pd.merge(f_streak, i_streak, on='date', how='outer').fillna(0)
        merged['symbol'] = sym
        all_streaks.append(merged)
    result = pd.concat(all_streaks, ignore_index=True)
    result['date'] = pd.to_datetime(result['date'])
    return result

def prepare_financials(fs_df):
    """Quarterly gross margin from financial statements."""
    df = fs_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    # Pivot to get Revenue and GrossProfit per date/symbol
    piv = df.pivot_table(index=['date', 'symbol'], columns='type', values='value', aggfunc='sum').reset_index()
    if 'Revenue' in piv.columns and 'GrossProfit' in piv.columns:
        piv['gross_margin'] = piv['GrossProfit'] / piv['Revenue'].replace(0, np.nan)
        piv = piv.sort_values(['symbol', 'date'])
        piv['gm_qoq'] = piv.groupby('symbol')['gross_margin'].diff() * 100  # in pp
        piv['rev_qoq'] = piv.groupby('symbol')['Revenue'].pct_change()
    return piv

def prepare_monthly_revenue(mrev_df):
    """Monthly revenue with 12M max check."""
    df = mrev_df.copy()
    df['date'] = pd.to_datetime(df['date'])  # report date
    df['period'] = df.apply(lambda r: pd.Timestamp(year=int(r['ryear']), month=int(r['rmonth']), day=1), axis=1)
    df = df.sort_values(['symbol', 'period'])
    df['rev_12m_max'] = df.groupby('symbol')['revenue'].transform(lambda x: x.rolling(12, min_periods=1).max())
    df['is_12m_high'] = (df['revenue'] >= df['rev_12m_max']).astype(int)
    # Also compute 4Q CAGR
    df['q_rev'] = df.groupby('symbol')['revenue'].transform(lambda x: x.rolling(3, min_periods=3).sum())
    df['q_rev_4q_ago'] = df.groupby('symbol')['q_rev'].shift(4)
    df['rev_4q_cagr'] = (df['q_rev'] / df['q_rev_4q_ago']) - 1
    return df


# ── Validation ──────────────────────────────────────────────────────────────

def walk_forward_folds(dates, n_train_quarters=4, embargo_days=20):
    quarters = pd.date_range(dates.min(), dates.max(), freq='QE')
    folds = []
    for i in range(n_train_quarters + 1, len(quarters)):
        train_end = quarters[i-1]
        test_start = quarters[i-1] + timedelta(days=embargo_days + 1)
        test_end = quarters[i]
        folds.append((train_end, test_start, test_end))
    return folds


def validate_h1(prices, financials):
    """H1: Gross margin QoQ > 2pp AND rev QoQ > 5% → rank IC with forward returns."""
    print("\n" + "="*60)
    print("H1: Gross Margin Expansion + Revenue Growth")
    print("="*60)
    
    fin = prepare_financials(financials)
    prices_wf = compute_price_factors(prices)
    prices_wf = prices_wf[prices_wf['symbol'].isin(POWER_SEMI)]
    
    # Lag financials by 45 days (earnings publication delay) to avoid look-ahead
    # For each date, use the latest financial statement published at least 45 days ago
    fin['available_date'] = fin['date'] + timedelta(days=45)
    
    # Build daily signal: for each price date, find latest available financial data
    all_dates = sorted(prices_wf['date'].unique())
    folds = walk_forward_folds(pd.DatetimeIndex(all_dates))
    print(f"  WF folds: {len(folds)}")
    
    results = {}
    for horizon, label in [(20, '1M'), (40, '2M'), (60, '3M')]:
        col = f'fwd_{horizon}d'
        ic_list = []
        signal_count = 0
        
        for fold_i, (train_end, test_start, test_end) in enumerate(folds):
            test_dates = [d for d in all_dates if test_start <= d <= test_end]
            for d in test_dates:
                day_prices = prices_wf[prices_wf['date'] == d]
                for _, prow in day_prices.iterrows():
                    sym = prow['symbol']
                    # Find latest financial data available before d
                    sym_fin = fin[(fin['symbol'] == sym) & (fin['available_date'] <= d)]
                    if len(sym_fin) == 0:
                        continue
                    latest = sym_fin.iloc[-1]
                    gm_qoq = latest.get('gm_qoq')
                    rev_qoq = latest.get('rev_qoq')
                    
                    if pd.notna(gm_qoq) and pd.notna(rev_qoq) and gm_qoq > 2 and rev_qoq > 0.05:
                        ret = prow.get(col)
                        if pd.notna(ret):
                            # Store for IC computation per fold
                            signal_count += 1
        
            if signal_count >= 3:
                # Aggregate IC by quarter for more robust stats
                test = prices_wf[prices_wf['date'].isin(test_dates)]
                # Merge with financial signals
                merged = []
                for _, prow in test.iterrows():
                    sym = prow['symbol']
                    sym_fin = fin[(fin['symbol'] == sym) & (fin['available_date'] <= prow['date'])]
                    if len(sym_fin) == 0:
                        continue
                    latest = sym_fin.iloc[-1]
                    gm_qoq = latest.get('gm_qoq')
                    rev_qoq = latest.get('rev_qoq')
                    ret = prow.get(col)
                    if pd.notna(gm_qoq) and pd.notna(rev_qoq) and pd.notna(ret):
                        signal = 1 if (gm_qoq > 2 and rev_qoq > 0.05) else 0
                        merged.append({'signal': signal, 'ret': ret, 'gm_qoq': gm_qoq, 'rev_qoq': rev_qoq})
                
                if len(merged) >= 5 and sum(r['signal'] for r in merged) >= 3:
                    df_m = pd.DataFrame(merged)
                    # IC of the composite (gm_qoq + rev_qoq) with forward returns, for signal=1 subset
                    sig_pos = df_m[df_m['signal'] == 1]
                    ic, _ = spearmanr(sig_pos['gm_qoq'].rank(), sig_pos['ret'].rank())
                    ic_list.append(ic)
        
        if ic_list:
            mean_ic = np.mean(ic_list)
            std_ic = np.std(ic_list)
            results[label] = {
                'mean_IC': round(mean_ic, 4),
                'IC_std': round(std_ic, 4),
                't_stat': round(mean_ic/(std_ic/np.sqrt(len(ic_list))), 3) if std_ic > 0 else 0,
                'n_folds': len(ic_list),
            }
            print(f"  {label}: IC={mean_ic:.4f}, t={results[label]['t_stat']}, folds={len(ic_list)}")
        else:
            results[label] = {'error': 'insufficient signals'}
            print(f"  {label}: insufficient signals")
    
    return results


def validate_h2(prices, inst, mrev):
    """H2: (foreign_streak >= 5 OR invtrust_streak >= 5) AND latest revenue = 12M high → hit rate."""
    print("\n" + "="*60)
    print("H2: Institutional Streak + Revenue Peak")
    print("="*60)
    
    prices_wf = compute_price_factors(prices)
    prices_wf = prices_wf[prices_wf['symbol'].isin(POWER_SEMI)]
    streaks = compute_institutional_streaks(inst)
    mrev_df = prepare_monthly_revenue(mrev)
    
    all_dates = sorted(prices_wf['date'].unique())
    folds = walk_forward_folds(pd.DatetimeIndex(all_dates))
    
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
                for sym in POWER_SEMI:
                    # Get streaks at date d
                    sym_streak = streaks[(streaks['symbol'] == sym) & (streaks['date'] <= d)]
                    if len(sym_streak) == 0:
                        continue
                    latest_streak = sym_streak.iloc[-1]
                    fs = latest_streak.get('foreign_streak', 0)
                    its = latest_streak.get('invtrust_streak', 0)
                    
                    if not (fs >= 5 or its >= 5):
                        continue
                    
                    # Check if latest monthly revenue is 12M high
                    sym_rev = mrev_df[(mrev_df['symbol'] == sym) & (mrev_df['date'] <= d)]
                    if len(sym_rev) == 0:
                        continue
                    latest_rev = sym_rev.iloc[-1]
                    if latest_rev.get('is_12m_high', 0) != 1:
                        continue
                    
                    # Both conditions met
                    price_row = prices_wf[(prices_wf['symbol'] == sym) & (prices_wf['date'] == d)]
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
            print(f"  {label}: hit_rate={np.mean(hit_rates):.2%}, fwd_ret={np.mean(mean_rets):.4f}, "
                  f"signals/fold={np.mean(signal_counts):.0f}, folds={len(hit_rates)}")
        else:
            results[label] = {'error': 'insufficient signals'}
            print(f"  {label}: insufficient signals")
    
    return results


def validate_h3(prices, mrev):
    """H3: 4Q revenue CAGR > 15% AND 40 < RSI < 70 → rank IC."""
    print("\n" + "="*60)
    print("H3: Revenue CAGR + RSI Sweet Spot")
    print("="*60)
    
    prices_wf = compute_price_factors(prices)
    prices_wf = prices_wf[prices_wf['symbol'].isin(POWER_SEMI)]
    mrev_df = prepare_monthly_revenue(mrev)
    
    all_dates = sorted(prices_wf['date'].unique())
    folds = walk_forward_folds(pd.DatetimeIndex(all_dates))
    
    results = {}
    for horizon, label in [(20, '1M'), (40, '2M'), (60, '3M')]:
        col = f'fwd_{horizon}d'
        ic_list = []
        
        for fold_i, (train_end, test_start, test_end) in enumerate(folds):
            test_dates = [d for d in all_dates if test_start <= d <= test_end]
            fold_signals = []
            
            for d in test_dates:
                for sym in POWER_SEMI:
                    # Get RSI
                    sym_price = prices_wf[(prices_wf['symbol'] == sym) & (prices_wf['date'] == d)]
                    if len(sym_price) == 0:
                        continue
                    rsi = sym_price['rsi_14'].iloc[0]
                    ret = sym_price[col].iloc[0]
                    
                    if pd.isna(rsi) or pd.isna(ret):
                        continue
                    
                    # Get 4Q CAGR
                    sym_rev = mrev_df[(mrev_df['symbol'] == sym) & (mrev_df['date'] <= d)]
                    if len(sym_rev) == 0:
                        continue
                    cagr = sym_rev.iloc[-1].get('rev_4q_cagr')
                    if pd.isna(cagr):
                        continue
                    
                    signal = 1 if (cagr > 0.15 and 40 < rsi < 70) else 0
                    fold_signals.append({'signal': signal, 'ret': ret, 'cagr': cagr, 'rsi': rsi})
            
            if len(fold_signals) >= 5:
                df_m = pd.DataFrame(fold_signals)
                sig_pos = df_m[df_m['signal'] == 1]
                if len(sig_pos) >= 3:
                    ic, _ = spearmanr(sig_pos['cagr'].rank(), sig_pos['ret'].rank())
                    ic_list.append(ic)
        
        if ic_list:
            mean_ic = np.mean(ic_list)
            std_ic = np.std(ic_list)
            results[label] = {
                'mean_IC': round(mean_ic, 4),
                'IC_std': round(std_ic, 4),
                't_stat': round(mean_ic/(std_ic/np.sqrt(len(ic_list))), 3) if std_ic > 0 else 0,
                'n_folds': len(ic_list),
            }
            print(f"  {label}: IC={mean_ic:.4f}, t={results[label]['t_stat']}, folds={len(ic_list)}")
        else:
            results[label] = {'error': 'insufficient signals'}
            print(f"  {label}: insufficient signals")
    
    # Also: check unconditioned CAGR IC
    all_signals = []
    for d in all_dates:
        for sym in POWER_SEMI:
            sym_price = prices_wf[(prices_wf['symbol'] == sym) & (prices_wf['date'] == d)]
            if len(sym_price) == 0:
                continue
            ret = sym_price['fwd_40d'].iloc[0]
            sym_rev = mrev_df[(mrev_df['symbol'] == sym) & (mrev_df['date'] <= d)]
            if len(sym_rev) == 0:
                continue
            cagr = sym_rev.iloc[-1].get('rev_4q_cagr')
            if pd.notna(cagr) and pd.notna(ret):
                all_signals.append({'cagr': cagr, 'ret': ret})
    
    if len(all_signals) >= 5:
        df_all = pd.DataFrame(all_signals)
        ic_base, pv = spearmanr(df_all['cagr'].rank(), df_all['ret'].rank())
        print(f"  Baseline (unconditioned 4Q CAGR): n={len(df_all)}, IC={ic_base:.4f}")
    
    return results


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("="*60)
    print(f"Task #24: Power Semiconductor OOS Validation")
    print(f"Targets: {POWER_SEMI}")
    print(f"Run: {date.today()}")
    print("="*60)
    
    data = pull_data()
    
    h1 = validate_h1(data['prices'], data['fs'])
    h2 = validate_h2(data['prices'], data['inst'], data['mrev'])
    h3 = validate_h3(data['prices'], data['mrev'])
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    verdicts = {}
    
    print("\nH1 (GM QoQ > 2pp + Rev QoQ > 5%):")
    for k, v in (h1 or {}).items():
        if 'error' in v: print(f"  {k}: ERROR - {v['error']}")
        else: print(f"  {k}: IC={v['mean_IC']}, t={v['t_stat']}, folds={v['n_folds']}")
    ic1 = h1.get('2M', {}).get('mean_IC', 0) if h1 else 0
    verdicts['H1'] = 'PASS' if ic1 > 0.05 else 'WEAK' if ic1 > 0 else 'FAIL'
    
    print("\nH2 (Institutional streak + Rev peak):")
    for k, v in (h2 or {}).items():
        if 'error' in v: print(f"  {k}: ERROR - {v['error']}")
        else: print(f"  {k}: hit={v['mean_hit_rate']:.2%}, ret={v['mean_fwd_return']:.4f}, sig/fold={v['avg_signals_per_fold']:.0f}")
    hr2 = h2.get('1M', {}).get('mean_hit_rate', 0) if h2 else 0
    verdicts['H2'] = 'PASS' if hr2 > 0.55 else 'WEAK' if hr2 > 0.50 else 'FAIL'
    
    print("\nH3 (Rev CAGR > 15% + 40 < RSI < 70):")
    for k, v in (h3 or {}).items():
        if 'error' in v: print(f"  {k}: ERROR - {v['error']}")
        else: print(f"  {k}: IC={v['mean_IC']}, t={v['t_stat']}, folds={v['n_folds']}")
    ic3 = h3.get('2M', {}).get('mean_IC', 0) if h3 else 0
    verdicts['H3'] = 'PASS' if ic3 > 0.05 else 'WEAK' if ic3 > 0 else 'FAIL'
    
    print(f"\nVerdicts: {verdicts}")
    
    # Save
    out_path = os.path.join(os.path.dirname(__file__), '..', 'agents', 'sub',
                             'quant-researcher', 'memory', 'power_semi_validation.json')
    output = {'h1': {k: v for k, v in (h1 or {}).items()},
              'h2': {k: v for k, v in (h2 or {}).items()},
              'h3': {k: v for k, v in (h3 or {}).items()},
              'verdicts': verdicts, 'run_date': str(date.today())}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    
    return verdicts

if __name__ == '__main__':
    main()
