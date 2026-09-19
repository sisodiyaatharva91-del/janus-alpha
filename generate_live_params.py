"""
generate_live_params.py
------------------------
Produces the CURRENT live-trading Bull/Bear parameters. This is deliberately
SEPARATE from wfo_engine_updated.py's 14 historical windows -- every one of
those windows held out a real OOS test year for validation, so none of them
are "the current live parameters," they're historical backtest artifacts.

This script trains on the most recent 3 years of data (2-year Fit + 1-year
Validation, same nested min()-based selection as the main WFO engine, same
random-seed discipline) with NO held-out test year, since there's no future
data to hold out for live deployment -- the "test" is live/paper performance
itself, tracked separately.

Run this on whatever re-optimization cadence you land on (quarterly/annual
recommended per the Phase 1 cadence analysis -- avoid monthly, the random
search's own seed-to-seed variance is comparable in size to a month of real
signal, so re-fitting that often is very likely fitting noise, not adapting
to anything real).

Output: live_params.json, committed to the repo, consumed by live_pipeline.py.
"""

import pandas as pd
import numpy as np
import random
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta
import warnings

warnings.filterwarnings("ignore")

# ==========================================
# CONFIGURATION -- keep in sync with wfo_engine_updated.py
# ==========================================
DATA_FILE = 'NSE_15Y_Deployment_Ready_V9.parquet'  # or wherever the live-updated master file lives
FIT_YEARS = 2
VALIDATION_YEARS = 1
ITERATIONS = 1000
START_CAPITAL = 600000
SLIPPAGE_TAX_PCT = 0.15

# COPY PARITY FIX 2026-08-22 -- finding #34.
# These four MUST equal their namesakes in wfo_engine_updated.py. This file
# keeps its own copy of run_headless_simulation and calculate_fitness, and
# those copies had already drifted once: the engine got the idle-yield and CAGR
# units fixes and this file did not, so the params written to live_params.json
# were being SELECTED under different arithmetic than the WFO validated.
# test_engine_copy_parity.py now fails if the two copies diverge again.
TRADING_DAYS_PER_YEAR = 252        # == wfo_engine_updated.TRADING_DAYS_PER_YEAR
IDLE_YIELD_PCT = 4.0               # == wfo_engine_updated.IDLE_YIELD_PCT
MAX_GAP_LOSS_PCT = 0.03            # == wfo_engine_updated.MAX_GAP_LOSS_PCT
ASSUMED_WORST_CASE_GAP_PCT = 0.20  # == wfo_engine_updated.ASSUMED_WORST_CASE_GAP_PCT
RANDOM_SEED = 42  # keep fixed for reproducibility; document if you ever change it
OUTPUT_PATH = 'live_params.json'

W_SORTINO, W_PF, W_WINRATE, W_TRADES = 0.35, 0.20, 0.15, 0.30

random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)


def run_headless_simulation(p, daily_data, calendar_dates):
    """A COPY of wfo_engine_updated.run_headless_simulation.

    Verified equivalent to the engine's version on 2026-08-22 by a
    comment-stripped diff: same 7-tuple return, same logic, differing only in
    line-splitting and in a total_pnl accumulator the engine never returns.

    The previous version of this docstring said "kept in sync manually", and it
    was not: the engine received the idle-yield and CAGR units fixes and this
    copy did not (finding #34). Do NOT trust the claim of equivalence above --
    run test_engine_copy_parity.py, which re-derives it mechanically. If you
    edit either copy, that test tells you immediately; if you finally extract a
    shared module, delete the test along with the duplicate."""
    bb_equity, mr_equity = p['start_cap'] * 0.5, p['start_cap'] * 0.5
    bb_cash, mr_cash = bb_equity, mr_equity
    active_bb, active_mr = {}, {}
    wins, losses = 0, 0
    gross_profits, gross_losses = 0.0, 0.0
    bb_trades, mr_trades = 0, 0
    equity_curve = []
    # / TRADING_DAYS_PER_YEAR, not / 365: applied once per element of
    # calendar_dates, and those are TRADING days.
    daily_yield_rate = (p['idle_yield'] / 100) / TRADING_DAYS_PER_YEAR

    for current_date in calendar_dates:
        bb_yld = max(0, bb_cash) * daily_yield_rate
        bb_cash += bb_yld; bb_equity += bb_yld
        mr_yld = max(0, mr_cash) * daily_yield_rate
        mr_cash += mr_yld; mr_equity += mr_yld

        todays_rows = daily_data.get(current_date, [])
        today_lookup = {r['SYMBOL']: r for r in todays_rows}
        current_breadth = todays_rows[0]['Market_Breadth'] if todays_rows else 0
        today_regime = todays_rows[0].get('Regime_Label', 'NEUTRAL') if todays_rows else 'NEUTRAL'
        active_p = p['bull'] if today_regime == 'BULL' else p['bear']

        total_equity = bb_equity + mr_equity
        if today_regime == 'BULL':
            if current_breadth > 0.65: bb_frac, mr_frac = 0.80, 0.20
            elif current_breadth >= 0.50: bb_frac, mr_frac = 0.60, 0.40
            else: bb_frac, mr_frac = 0.35, 0.65
        else:
            bb_frac, mr_frac = 0.20, 0.80
        target_bb_equity, target_mr_equity = total_equity * bb_frac, total_equity * mr_frac
        bb_cash += (target_bb_equity - bb_equity)
        mr_cash += (target_mr_equity - mr_equity)
        bb_equity, mr_equity = target_bb_equity, target_mr_equity

        for sym, pos in list(active_bb.items()):
            if sym not in today_lookup: continue
            row = today_lookup[sym]
            exit_triggered, exit_price = False, 0
            if row['OPEN'] <= pos['stop_price']: exit_triggered, exit_price = True, row['OPEN']
            elif row['LOW'] <= pos['stop_price']: exit_triggered, exit_price = True, pos['stop_price']
            elif row['OPEN'] >= pos['target_price']: exit_triggered, exit_price = True, row['OPEN']
            elif row['HIGH'] >= pos['target_price']: exit_triggered, exit_price = True, pos['target_price']
            elif row['BB_Exhaustion_Today'] and row['CLOSE'] > pos['entry_price']: exit_triggered, exit_price = True, row['CLOSE']
            if exit_triggered:
                rev = pos['shares'] * exit_price
                net_rev = rev - ((rev * (p['slip_tax'] / 100)) + min(rev * 0.0015, 20.0))
                profit = net_rev - pos['net_cost']
                bb_cash += net_rev; bb_equity += profit
                bb_trades += 1
                if profit > 0: wins += 1; gross_profits += profit
                else: losses += 1; gross_losses += abs(profit)
                del active_bb[sym]

        for sym, pos in list(active_mr.items()):
            if sym not in today_lookup: continue
            row = today_lookup[sym]
            pos['trading_days'] += 1
            exit_triggered, exit_price = False, 0
            if row['CLOSE'] > row['SMA_5']: exit_triggered, exit_price = True, row['CLOSE']
            elif pos['trading_days'] >= 4 and row['CLOSE'] < pos['entry_price']: exit_triggered, exit_price = True, row['CLOSE']
            elif pos['trading_days'] >= active_p['mr_time']: exit_triggered, exit_price = True, row['CLOSE']
            if exit_triggered:
                rev = pos['shares'] * exit_price
                net_rev = rev - ((rev * (p['slip_tax'] / 100)) + min(rev * 0.0015, 20.0))
                profit = net_rev - pos['net_cost']
                mr_cash += net_rev; mr_equity += profit
                mr_trades += 1
                if profit > 0: wins += 1; gross_profits += profit
                else: losses += 1; gross_losses += abs(profit)
                del active_mr[sym]

        systemic_panic_today = todays_rows[0].get('Systemic_Panic', False) if todays_rows else False
        if current_breadth < 0.50 and systemic_panic_today and mr_cash > 0:
            cands = [r for r in todays_rows if r['MR_Base_Signal'] and r['SYMBOL'] not in active_mr]
            if cands:
                max_alloc_per_ticker = mr_equity * (active_p['mr_pos_size'] / 100)
                alloc = min(max_alloc_per_ticker, mr_cash / len(cands))
                for row in cands:
                    cap_limit = row.get('Turnover_SMA_50', 1e12) * 0.05
                    shares = int(min(alloc, cap_limit) / row['CLOSE'])
                    if shares > 0 and mr_cash >= (cost := shares * row['CLOSE']):
                        mr_cash -= cost
                        active_mr[row['SYMBOL']] = {'entry_price': row['CLOSE'], 'shares': shares, 'net_cost': cost, 'trading_days': 0}

        vix_spike_today = todays_rows[0].get('VIX_Spike', False) if todays_rows else False
        max_bb_pos = 0 if vix_spike_today else (6 if current_breadth > 0.65 else 3 if current_breadth >= 0.50 else 1)
        if max_bb_pos > 0 and bb_cash > 0 and len(active_bb) < max_bb_pos:
            cands = sorted(
                [r for r in todays_rows if r['BB_Enter_Today'] and r['SYMBOL'] not in active_bb],
                key=lambda x: (-x['RS_Percentile'], x['ATR_Contraction_Ratio'])
            )
            for row in cands:
                if len(active_bb) >= max_bb_pos or bb_cash <= 0: break
                atr = row['Target_ATR']
                if pd.isna(atr) or atr <= 0: continue
                stop, tgt = row['OPEN'] - (active_p['bb_stop'] * atr), row['OPEN'] + (active_p['bb_tgt'] * atr)
                if (risk := row['OPEN'] - stop) <= 0: continue
                cap_limit = row.get('Turnover_SMA_50', 1e12) * 0.05
                gap_safe_shares = int((bb_equity * MAX_GAP_LOSS_PCT)
                                      / (row['OPEN'] * ASSUMED_WORST_CASE_GAP_PCT))
                shares = min(int((bb_equity * (active_p['bb_risk'] / 100)) / risk), int((bb_equity * 0.20) / row['OPEN']), int(cap_limit / row['OPEN']), gap_safe_shares)
                if shares > 0 and bb_cash >= (cost := shares * row['OPEN']):
                    bb_cash -= cost
                    active_bb[row['SYMBOL']] = {'entry_price': row['OPEN'], 'stop_price': stop, 'target_price': tgt, 'shares': shares, 'net_cost': cost}

        equity_curve.append(bb_equity + mr_equity)

    return equity_curve, wins, losses, gross_profits, gross_losses, bb_trades, mr_trades


def calculate_fitness(eq_curve, wins, losses, gross_profits, gross_losses):
    if not eq_curve or len(eq_curve) < 20: return -float('inf'), 0, 0, 0, 0
    eq_series = pd.Series(eq_curve)
    pct_returns = eq_series.pct_change().dropna()
    days = len(eq_curve)
    # `days` counts TRADING days, so annualize on a 252-day year. The old
    # 365.25/days inflated a true 14.17% into 21.18% and, worse, pushed
    # candidates into the norm_sortino cap where selection stops
    # discriminating on risk. See test_cagr_units.py TEST 3.
    years = days / TRADING_DAYS_PER_YEAR
    cagr = (((eq_series.iloc[-1] / eq_series.iloc[0]) ** (1 / years) - 1) * 100
            if years > 0 else 0.0)
    dd = ((eq_series - eq_series.cummax()) / eq_series.cummax()).min() * 100
    downside_std = pct_returns[pct_returns < 0].std() * np.sqrt(252)
    sortino = (cagr / 100) / downside_std if downside_std > 0 else 0
    total_trades = wins + losses
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    pf = gross_profits / gross_losses if gross_losses > 0 else 0
    norm_sortino = min(sortino / 3.0, 1.0)
    norm_pf = min(pf / 2.5, 1.0)
    norm_wr = win_rate / 100.0
    norm_trades = min(total_trades / 100.0, 1.0)
    fitness_score = (norm_sortino * W_SORTINO) + (norm_pf * W_PF) + (norm_wr * W_WINRATE) + (norm_trades * W_TRADES)
    if total_trades < 30: fitness_score -= 2.0
    if dd < -20: fitness_score -= 3.0
    elif dd < -15: fitness_score -= 1.0
    return fitness_score, cagr, dd, sortino, pf


def main():
    print(f"Loading {DATA_FILE}...")
    df = pd.read_parquet(DATA_FILE)
    df['DATE'] = pd.to_datetime(df['DATE']).dt.date
    all_dates = sorted(df['DATE'].unique())
    records = df.to_dict('records')
    daily_data = {}
    for r in records:
        daily_data.setdefault(r['DATE'], []).append(r)

    latest_date = all_dates[-1]
    fit_start = latest_date - relativedelta(years=FIT_YEARS + VALIDATION_YEARS)
    fit_end = latest_date - relativedelta(years=VALIDATION_YEARS)

    fit_dates = [d for d in all_dates if fit_start <= d < fit_end]
    validation_dates = [d for d in all_dates if fit_end <= d <= latest_date]

    print(f"Fit period: {fit_dates[0]} to {fit_dates[-1]} ({len(fit_dates)} days)")
    print(f"Validation period: {validation_dates[0]} to {validation_dates[-1]} ({len(validation_dates)} days)")
    print(f"NO held-out test year -- this IS the live deployment fit.\n")

    best_selection_score = -float('inf')
    best_params = None

    for i in range(ITERATIONS):
        p = {
            'start_cap': START_CAPITAL, 'slip_tax': SLIPPAGE_TAX_PCT, 'idle_yield': IDLE_YIELD_PCT,
            'bull': {
                'bb_tgt': round(random.uniform(2.5, 6.0), 1), 'bb_stop': round(random.uniform(1.5, 3.0), 1),
                'bb_risk': round(random.uniform(1.5, 3.5), 1), 'mr_time': random.randint(3, 7),
                'mr_pos_size': round(random.uniform(5.0, 15.0), 1)
            },
            'bear': {
                'bb_tgt': round(random.uniform(2.0, 5.0), 1), 'bb_stop': round(random.uniform(1.5, 3.0), 1),
                'bb_risk': round(random.uniform(1.5, 3.5), 1), 'mr_time': random.randint(3, 7),
                'mr_pos_size': round(random.uniform(5.0, 15.0), 1)
            }
        }
        fit_eq, fit_w, fit_l, fit_gp, fit_gl, _, _ = run_headless_simulation(p, daily_data, fit_dates)
        fit_fitness, *_ = calculate_fitness(fit_eq, fit_w, fit_l, fit_gp, fit_gl)
        val_eq, val_w, val_l, val_gp, val_gl, _, _ = run_headless_simulation(p, daily_data, validation_dates)
        val_fitness, *_ = calculate_fitness(val_eq, val_w, val_l, val_gp, val_gl)
        selection_score = min(fit_fitness, val_fitness)
        if best_params is None or selection_score > best_selection_score:
            best_selection_score = selection_score
            best_params = p
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{ITERATIONS} iterations...")

    output = {
        "generated_at": datetime.utcnow().isoformat(),
        "generated_from_data_through": str(latest_date),
        "fit_period": [str(fit_dates[0]), str(fit_dates[-1])],
        "validation_period": [str(validation_dates[0]), str(validation_dates[-1])],
        "random_seed": RANDOM_SEED,
        "params": best_params
    }

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nLive params written to {OUTPUT_PATH}:")
    print(json.dumps(best_params, indent=2))
    print(f"\nNext re-fit recommended: per your chosen cadence (quarterly/annual). "
          f"Do NOT run this more often than monthly -- seed-to-seed search variance "
          f"is comparable in size to a month of genuine signal (see Phase 1 changelog).")


if __name__ == "__main__":
    main()
