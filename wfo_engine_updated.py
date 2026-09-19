import pandas as pd
import numpy as np
import random
import datetime
from dateutil.relativedelta import relativedelta
import warnings

warnings.filterwarnings("ignore")

# ==========================================
# 1. CONFIGURATION & FITNESS WEIGHTS
# ==========================================
DATA_FILE = 'NSE_15Y_Deployment_Ready_V9.parquet'
TRAIN_YEARS = 3
TEST_YEARS = 1
FIT_YEARS = 2          # NEW: portion of TRAIN_YEARS used to fit each candidate
VALIDATION_YEARS = 1   # NEW: remaining portion of TRAIN_YEARS, held out for selection
                        # FIT_YEARS + VALIDATION_YEARS must equal TRAIN_YEARS.
                        # This does NOT touch the true OOS test year -- it's a second
                        # split entirely inside the existing training window, used only
                        # to stop the optimizer from selecting parameters that only work
                        # on the exact noise of the full 3-year training stretch.
ITERATIONS_PER_WINDOW = 1000
START_CAPITAL = 600000
SLIPPAGE_TAX_PCT = 0.15

# REPRODUCIBILITY FIX: random.seed() was never called anywhere in this
# script, in ANY prior version -- every run drew a completely different set
# of 1,000 random parameter candidates per window, with no way to reproduce
# results or cleanly isolate the effect of a code change from ordinary
# random-sampling variance. This is very likely a major, possibly dominant,
# contributor to how different the v2 -> v3 results looked.
#
# Set RANDOM_SEED to a fixed integer for a reproducible run (same code +
# same seed = identical results, every time). To test how much run-to-run
# variance exists purely from random sampling (independent of any code
# change), run this script multiple times with DIFFERENT seeds (e.g. 42,
# 43, 44) and compare the spread of Chained CAGR / Chained Max DD across
# them BEFORE trusting any single run's numbers as "the" answer.
RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)
print(f"Random seed fixed at {RANDOM_SEED} for reproducibility.")

# Trade-Weighted Fitness Function
W_SORTINO = 0.35
W_PF = 0.20
W_WINRATE = 0.15
W_TRADES = 0.30

# DIAGNOSTIC FIX 2: gap-risk position sizing safeguard.
# Trigger case: PARAS (2025 seed-42 diagnostic) gapped down and stopped out
# at -47.7% in 2 days, losing 32,821 -- 73% of that ENTIRE year's Sniper
# sleeve loss came from this ONE trade. The ATR-based stop assumes the exit
# fills AT or NEAR the intended stop price, but a gap (overnight news,
# lower-circuit lockdown) can blow straight through it -- the position was
# simply too large relative to what a worst-case gap could do to it. This
# can't be prevented after the fact (can't un-gap a stock), but position
# SIZE can be capped up front so that even an assumed worst-case gap can't
# cost more than a bounded % of sleeve equity, independent of the normal
# ATR-based risk sizing.
# Idle yield on uninvested sleeve cash. Both numbers below are load-bearing
# and were wrong together until 2026-08-22.
#
# THE UNITS BUG: run_headless_simulation accrues yield once per element of
# calendar_dates, and calendar_dates is built from the panel's DATE column --
# i.e. TRADING days, ~252 a year, not 365. Dividing an annual rate by 365 and
# then accruing it only 252 times delivers 252/365 = 69% of the stated rate.
# Every Phase 1 number was produced with idle_yield = 6.0 meaning an effective
# 4.23%/yr. Dividing by TRADING_DAYS_PER_YEAR makes the parameter mean what it
# says, so this constant is now honest rather than nominal.
#
# THE RATE: 4.0 is dell's chosen assumption (2026-08-22), replacing 6.0. It is
# also very close to what the old code was ACTUALLY delivering, so this change
# should barely move the headline -- see the note in ENGINEERING_CHANGELOG.md.
#
# REALITY CHECK, because this is modelled income and not a trade: 4%/yr on
# idle cash is only real if idle cash is genuinely swept into a liquid or
# overnight fund. If it sits in an un-swept broker ledger earning nothing, this
# constant should be 0.0 and every CAGR here is overstated by roughly the
# average idle fraction times 4%.
TRADING_DAYS_PER_YEAR = 252
IDLE_YIELD_PCT = 4.0

MAX_GAP_LOSS_PCT = 0.03        # no single trade should be able to lose more than
                                # ~3% of sleeve equity even in an assumed worst-case gap
ASSUMED_WORST_CASE_GAP_PCT = 0.20  # assume up to a 20% overnight gap is possible
                                    # (roughly a lower-circuit-level move for many
                                    # mid/small-cap NSE names)

# ==========================================
# 2. HEADLESS SIMULATION ENGINE
# ==========================================
def run_headless_simulation(p, daily_data, calendar_dates):
    bb_equity, mr_equity = p['start_cap'] * 0.5, p['start_cap'] * 0.5
    bb_cash, mr_cash = bb_equity, mr_equity
    active_bb, active_mr = {}, {}

    wins, losses, total_pnl = 0, 0, 0
    gross_profits, gross_losses = 0.0, 0.0
    bb_trades, mr_trades = 0, 0
    equity_curve = []

    # / TRADING_DAYS_PER_YEAR, not / 365: this rate is applied once per
    # element of calendar_dates, and those are TRADING days. See the
    # IDLE_YIELD_PCT comment at the top of this file.
    daily_yield_rate = (p['idle_yield'] / 100) / TRADING_DAYS_PER_YEAR

    for current_date in calendar_dates:
        # 1. Accrue Idle Yield
        bb_yld = max(0, bb_cash) * daily_yield_rate
        bb_cash += bb_yld; bb_equity += bb_yld

        mr_yld = max(0, mr_cash) * daily_yield_rate
        mr_cash += mr_yld; mr_equity += mr_yld

        todays_rows = daily_data.get(current_date, [])
        today_lookup = {r['SYMBOL']: r for r in todays_rows}
        # MACRO GATES ARRIVE PRE-LAGGED (since 2026-08-22, finding #32).
        # Market_Breadth, Regime_Label and VIX_Spike on this row are as of
        # the PREVIOUS trading session, because the Sniper block below fills
        # at this row's OPEN and may not use this row's own close. The lag
        # lives in coiled_alpha_logic.py (sections 7b and
        # compute_macro_regime), NOT here -- do not add a second shift.
        # Systemic_Panic is deliberately still same-bar: MR fills at CLOSE.
        current_breadth = todays_rows[0]['Market_Breadth'] if todays_rows else 0

        # --- DYNAMIC REGIME HOT-SWAPPING ---
        today_regime = todays_rows[0].get('Regime_Label', 'NEUTRAL') if todays_rows else 'NEUTRAL'

        active_p = p['bull'] if today_regime == 'BULL' else p['bear']

        # Dynamic Capital Allocation
        # DIAGNOSTIC FIX 1: previously gated ONLY on Regime_Label (Nifty
        # 200-SMA), which in 2018 said BULL for 79% of the year while
        # Market_Breadth averaged only 0.416 -- a real, historically
        # documented divergence (2018 IL&FS crisis: Nifty50, large-cap
        # weighted, stayed roughly flat while the broader mid/small-cap
        # universe -- where Sniper actually trades -- fell 25-30%+
        # underneath it). The old logic deployed 80% of capital to Sniper
        # based purely on the index level, even while the actual stock
        # universe's own health signal (breadth) was flashing distress.
        # The slot-count throttle already reacted to weak breadth, but the
        # ALLOCATION PERCENTAGE itself never did. Now it does: full
        # conviction (80/20) only when regime AND breadth agree; scaled
        # back hard when the index says bull but breadth disagrees.
        total_equity = bb_equity + mr_equity
        if today_regime == 'BULL':
            if current_breadth > 0.65:
                bb_frac, mr_frac = 0.80, 0.20   # regime + breadth agree: full conviction
            elif current_breadth >= 0.50:
                bb_frac, mr_frac = 0.60, 0.40   # regime bullish, breadth so-so: moderate
            else:
                bb_frac, mr_frac = 0.35, 0.65   # regime says bull, breadth says danger (the 2018 pattern) -- scale WAY back
        else:
            bb_frac, mr_frac = 0.20, 0.80        # bear regime: unchanged from before

        target_bb_equity = total_equity * bb_frac
        target_mr_equity = total_equity * mr_frac

        bb_cash += (target_bb_equity - bb_equity)
        mr_cash += (target_mr_equity - mr_equity)
        bb_equity = target_bb_equity
        mr_equity = target_mr_equity

        # --- EXITS: V21 SNIPER ---
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
                total_pnl += profit
                bb_trades += 1
                if profit > 0: wins += 1; gross_profits += profit
                else: losses += 1; gross_losses += abs(profit)
                del active_bb[sym]

        # --- EXITS: MEAN REVERSION ---
        for sym, pos in list(active_mr.items()):
            if sym not in today_lookup: continue
            row = today_lookup[sym]
            pos['trading_days'] += 1

            exit_triggered, exit_price = False, 0

            if row['CLOSE'] > row['SMA_5']:
                exit_triggered, exit_price = True, row['CLOSE']
            elif pos['trading_days'] >= 4 and row['CLOSE'] < pos['entry_price']:
                exit_triggered, exit_price = True, row['CLOSE']
            elif pos['trading_days'] >= active_p['mr_time']: # Regimed Time Stop
                exit_triggered, exit_price = True, row['CLOSE']

            if exit_triggered:
                rev = pos['shares'] * exit_price
                net_rev = rev - ((rev * (p['slip_tax'] / 100)) + min(rev * 0.0015, 20.0))
                profit = net_rev - pos['net_cost']
                mr_cash += net_rev; mr_equity += profit
                total_pnl += profit
                mr_trades += 1
                if profit > 0: wins += 1; gross_profits += profit
                else: losses += 1; gross_losses += abs(profit)
                del active_mr[sym]

        # --- ENTRIES: MEAN REVERSION ---
        systemic_panic_today = todays_rows[0].get('Systemic_Panic', False) if todays_rows else False
        if current_breadth < 0.50 and systemic_panic_today and mr_cash > 0:
            cands = [r for r in todays_rows if r['MR_Base_Signal'] and r['SYMBOL'] not in active_mr]
            if cands:
                max_alloc_per_ticker = mr_equity * (active_p['mr_pos_size'] / 100) # Regimed Sizing
                alloc = min(max_alloc_per_ticker, mr_cash / len(cands))

                for row in cands:
                    cap_limit = row.get('Turnover_SMA_50', 1e12) * 0.05
                    shares = int(min(alloc, cap_limit) / row['CLOSE'])
                    if shares > 0 and mr_cash >= (cost := shares * row['CLOSE']):
                        mr_cash -= cost
                        active_mr[row['SYMBOL']] = {'entry_price': row['CLOSE'], 'shares': shares, 'net_cost': cost, 'trading_days': 0}

        # --- ENTRIES: V21 SNIPER ---
        vix_spike_today = todays_rows[0].get('VIX_Spike', False) if todays_rows else False
        if vix_spike_today:
            max_bb_pos = 0
        else:
            # THROUGHPUT FIX: raised slot counts (6/3/1 vs old 4/2/0), and
            # removed the hard lockout below 0.50 breadth. The old version
            # gave ZERO Sniper slots on any day where current_breadth < 0.50
            # -- but a stock can still be a genuine top-decile Relative
            # Strength leader even when the broader market is weak (that's
            # part of what "relative" strength means). Fully locking out
            # entries in that regime was very likely a major contributor to
            # the low trade counts (6-34 Sniper trades/window) driving the
            # noisy, unstable fitness estimates seen in the overfitting
            # analysis. Now allows a single cautious slot even in weak
            # breadth, rather than mandatory zero.
            max_bb_pos = 6 if current_breadth > 0.65 else 3 if current_breadth >= 0.50 else 1

        if max_bb_pos > 0 and bb_cash > 0 and len(active_bb) < max_bb_pos:
            # ------------------------------------------------------------------
            # CANDIDATE SORT ORDER -- CHANGED from Target_ATR descending to
            # RS_Percentile descending (tightest ATR_Contraction_Ratio as
            # tiebreak).
            #
            # WHY: with Coiled Alpha routinely producing far more BB_Enter_Today
            # signals per day than there are open slots (max_bb_pos caps at
            # 2-4), this sort order IS the effective selection alpha -- it
            # decides which candidates actually get capital and which don't.
            # The old sort (raw ATR descending) rewarded whichever candidate
            # happened to be most volatile that day, which has nothing to do
            # with "true relative strength leader" -- the actual entry thesis.
            # Sorting by RS_Percentile descending means: when multiple stocks
            # clear all four entry filters and compete for a limited number of
            # slots, take the strongest relative-strength leaders first.
            # ATR_Contraction_Ratio ascending as the tiebreak means: among
            # equally-strong leaders, prefer the tighter coil (more volatility
            # compression = more "coiled" per the entry thesis).
            #
            # NOTE: RS_Percentile and ATR_Contraction_Ratio must be present in
            # the parquet -- added to columns_to_keep in data_prep.py. If you
            # are running this against an older deployment file that predates
            # that change, this will KeyError.
            # ------------------------------------------------------------------
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
                # DD FIX 2: max per-position size cut from 40% to 20% of
                # bb_equity. The 40% cap was calibrated when slots were
                # capped at 2-4 (needed larger individual sizing to deploy
                # capital). With up to 6 slots now available, 20% per
                # position still allows near-full capital deployment across
                # the sleeve while capping how much damage any single bad
                # name can do to overall equity. Trade COUNT is unaffected
                # -- this only caps size, not frequency.
                #
                # DIAGNOSTIC FIX 2: added gap_safe_shares as a fourth cap.
                # Ensures that even if this stock gapped down by
                # ASSUMED_WORST_CASE_GAP_PCT (20%) the very next day, the
                # dollar loss couldn't exceed MAX_GAP_LOSS_PCT (3%) of
                # sleeve equity -- directly bounds the PARAS-style tail
                # event regardless of how tight/loose the ATR-based stop
                # happens to be for this particular trade.
                gap_safe_shares = int((bb_equity * MAX_GAP_LOSS_PCT) / (row['OPEN'] * ASSUMED_WORST_CASE_GAP_PCT))
                shares = min(
                    int((bb_equity * (active_p['bb_risk'] / 100)) / risk),
                    int((bb_equity * 0.20) / row['OPEN']),
                    int(cap_limit / row['OPEN']),
                    gap_safe_shares
                )

                if shares > 0 and bb_cash >= (cost := shares * row['OPEN']):
                    bb_cash -= cost
                    active_bb[row['SYMBOL']] = {'entry_price': row['OPEN'], 'stop_price': stop, 'target_price': tgt, 'shares': shares, 'net_cost': cost}

        equity_curve.append(bb_equity + mr_equity)

    return equity_curve, wins, losses, gross_profits, gross_losses, bb_trades, mr_trades

# ==========================================
# 3. METRICS & FITNESS SCORING
# ==========================================
def calculate_fitness(eq_curve, wins, losses, gross_profits, gross_losses):
    if not eq_curve or len(eq_curve) < 20: return -float('inf'), 0, 0, 0, 0

    eq_series = pd.Series(eq_curve)
    pct_returns = eq_series.pct_change().dropna()

    # UNITS FIX 2026-08-22: `days` counts TRADING days (equity_curve gets one
    # append per entry in calendar_dates, which is the list of trading dates),
    # so annualizing with 365.25/days treated a 252-day year as 365.25 days
    # long and inflated CAGR by the exponent 365.25/252 = 1.4494. A true
    # 14.17% printed as 21.18%. Note the chained-CAGR block further down this
    # file already used days/252 and was correct -- the two disagreed.
    #
    # This was not only a reporting error: fitness uses
    # sortino = (cagr/100)/downside_std with norm_sortino = min(sortino/3, 1),
    # so inflated CAGR pushed candidates INTO that cap, where the
    # risk-adjusted term stopped discriminating between them and selection
    # fell through to profit factor / win rate / trade count. Demonstrated to
    # be able to flip the selected candidate -- see test_cagr_units.py and
    # test_cagr_units_selection.py.
    TRADING_DAYS_PER_YEAR = 252
    days = len(eq_curve)
    years = days / TRADING_DAYS_PER_YEAR
    cagr = ((eq_series.iloc[-1] / eq_series.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0.0
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

    if total_trades < 30:
        fitness_score -= 2.0

    # DD FIX 1: tightened from -25% to a graduated penalty starting at -15%
    # (your actual stated ceiling) and escalating past -20% (hard limit).
    # The old single threshold at -25% never penalized anything in the
    # 15-25% range at all -- exactly the range most of your OOS windows
    # were breaching. This directly aligns the optimizer's objective with
    # the real constraint, without touching stop-width/slot-count (so
    # throughput should be largely unaffected -- this only discourages
    # candidates whose DD profile was already a problem, not trade
    # frequency itself).
    if dd < -20:
        fitness_score -= 3.0   # hard ceiling breach -- strong penalty
    elif dd < -15:
        fitness_score -= 1.0   # soft ceiling breach -- moderate penalty

    return fitness_score, cagr, dd, sortino, pf

# ==========================================
# 4. WALK-FORWARD OPTIMIZER (WFO) ENGINE
# ==========================================
print(f"Loading Parquet: {DATA_FILE}")
df = pd.read_parquet(DATA_FILE)
df['DATE'] = pd.to_datetime(df['DATE']).dt.date
all_dates = sorted(df['DATE'].unique())

print("Preparing zero-copy dictionary (O(1) lookups)...")
records = df.to_dict('records')
daily_data = {}
for r in records: daily_data.setdefault(r['DATE'], []).append(r)

assert FIT_YEARS + VALIDATION_YEARS == TRAIN_YEARS, "FIT_YEARS + VALIDATION_YEARS must equal TRAIN_YEARS"

windows = []
start_idx = 0
while True:
    try:
        train_start = all_dates[start_idx]
        train_end = train_start + relativedelta(years=TRAIN_YEARS)
        test_end = train_end + relativedelta(years=TEST_YEARS)

        train_dates = [d for d in all_dates if train_start <= d < train_end]
        test_dates = [d for d in all_dates if train_end <= d < test_end]

        if len(test_dates) < 50: break

        # NEW: split the training window into Fit (first FIT_YEARS) and
        # Validation (remaining VALIDATION_YEARS) sub-periods, both still
        # entirely inside the training window -- the true OOS test_dates
        # above are untouched by this split.
        fit_end = train_start + relativedelta(years=FIT_YEARS)
        fit_dates = [d for d in train_dates if d < fit_end]
        validation_dates = [d for d in train_dates if d >= fit_end]

        windows.append((train_dates, fit_dates, validation_dates, test_dates))

        start_idx = next(i for i, d in enumerate(all_dates) if d >= train_start + relativedelta(years=TEST_YEARS))
    except StopIteration:
        break

print(f"Found {len(windows)} Walk-Forward Windows (3Y Train / 1Y Test). Starting Dual-Brain Optimization...\n")

wfo_results = []
chained_oos_returns = []  # NEW: collects each window's daily returns in sequence to build one continuous OOS equity curve across all 14 windows

for i, (train_dates, fit_dates, validation_dates, test_dates) in enumerate(windows):
    train_yr = f"{train_dates[0].year}-{train_dates[-1].year}"
    fit_yr = f"{fit_dates[0].year}-{fit_dates[-1].year}"
    val_yr = f"{validation_dates[0].year}-{validation_dates[-1].year}"
    test_yr = f"{test_dates[0].year}"
    print(f"--- Window {i+1}/{len(windows)} | Fit: {fit_yr} | Validation: {val_yr} | Test (OOS): {test_yr} ---")

    best_selection_score = -float('inf')
    best_params = None
    best_fit_cagr, best_fit_sortino = 0, 0
    best_val_cagr, best_val_sortino = 0, 0

    for _ in range(ITERATIONS_PER_WINDOW):
        p = {
            'start_cap': START_CAPITAL, 'slip_tax': SLIPPAGE_TAX_PCT, 'idle_yield': IDLE_YIELD_PCT,
            'bull': {
                # THROUGHPUT FIX: narrowed from (4.0-10.0)/(2.5-4.5) to bias the
                # search toward faster-resolving trades. Wide targets/stops let
                # a position sit occupying a slot for a long time before hitting
                # either bound -- with only a handful of slots, long-duration
                # trades directly cap how many trades/year can execute even
                # when signal supply is abundant. Still leaves the optimizer
                # room to find wider setups if they genuinely perform better;
                # this only shifts the search distribution, doesn't eliminate
                # the wide end entirely.
                'bb_tgt': round(random.uniform(2.5, 6.0), 1),
                'bb_stop': round(random.uniform(1.5, 3.0), 1),
                # DD FIX 3: risk-per-trade nudged down from (2.0-4.0) to
                # (1.5-3.5) -- smaller, complementary lever alongside Fix 2.
                'bb_risk': round(random.uniform(1.5, 3.5), 1),
                'mr_time': random.randint(3, 7),
                'mr_pos_size': round(random.uniform(5.0, 15.0), 1)
            },
            'bear': {
                # Same narrowing rationale as bull above.
                'bb_tgt': round(random.uniform(2.0, 5.0), 1),
                'bb_stop': round(random.uniform(1.5, 3.0), 1),
                'bb_risk': round(random.uniform(1.5, 3.5), 1),
                'mr_time': random.randint(3, 7),
                'mr_pos_size': round(random.uniform(5.0, 15.0), 1)
            }
        }

        # Score on BOTH sub-periods -- this is the anti-overfitting change.
        fit_eq, fit_w, fit_l, fit_gp, fit_gl, _, _ = run_headless_simulation(p, daily_data, fit_dates)
        fit_fitness, fit_cagr, fit_dd, fit_sortino, fit_pf = calculate_fitness(fit_eq, fit_w, fit_l, fit_gp, fit_gl)

        val_eq, val_w, val_l, val_gp, val_gl, _, _ = run_headless_simulation(p, daily_data, validation_dates)
        val_fitness, val_cagr, val_dd, val_sortino, val_pf = calculate_fitness(val_eq, val_w, val_l, val_gp, val_gl)

        # Selection score = the WORSE of the two. A parameter set that aces
        # Fit but collapses on Validation gets dragged down by its weak
        # Validation score and loses to a set that performs consistently
        # across both -- directly penalizes exactly the overfitting pattern
        # seen in the original single-period-fitness version (e.g. strong
        # in-sample Sortino, wildly negative OOS CAGR).
        selection_score = min(fit_fitness, val_fitness)

        if best_params is None or selection_score > best_selection_score:
            best_selection_score = selection_score
            best_params = p
            best_fit_cagr, best_fit_sortino = fit_cagr, fit_sortino
            best_val_cagr, best_val_sortino = val_cagr, val_sortino

    print(f"   Fit Best         -> CAGR: {best_fit_cagr:.2f}% | Sortino: {best_fit_sortino:.2f}")
    print(f"   Validation Best  -> CAGR: {best_val_cagr:.2f}% | Sortino: {best_val_sortino:.2f}")

    eq, w, l, gp, gl, oos_bb_trades, oos_mr_trades = run_headless_simulation(best_params, daily_data, test_dates)
    oos_fitness, oos_cagr, oos_dd, oos_sortino, oos_pf = calculate_fitness(eq, w, l, gp, gl)

    # NEW: convert this window's equity curve to daily RETURNS (scale-invariant)
    # and append to the chained sequence. Each window's simulation independently
    # resets to START_CAPITAL, so raw equity values can't be concatenated directly
    # -- but returns can, which is what lets us build one continuous multi-year
    # OOS curve out of 14 independently-simulated windows.
    eq_series = pd.Series(eq)
    window_returns = eq_series.pct_change().dropna().tolist()
    if len(eq_series) > 0:
        first_day_return = (eq_series.iloc[0] / best_params['start_cap']) - 1
        window_returns = [first_day_return] + window_returns
    chained_oos_returns.extend(window_returns)

    market_return = (daily_data[test_dates[-1]][0]['CLOSE'] / daily_data[test_dates[0]][0]['CLOSE']) - 1
    regime = "BULL" if market_return > 0 else "BEAR / CHOP"

    print(f"   Out-Of-Sample    -> CAGR: {oos_cagr:.2f}% | Max DD: {oos_dd:.2f}% | Trades: [Sniper: {oos_bb_trades} | MR: {oos_mr_trades}] | Regime: {regime}\n")

    wfo_results.append({
        'Test_Year': test_yr,
        'Regime': regime,
        'Fit_CAGR': round(best_fit_cagr, 2),
        'Fit_Sortino': round(best_fit_sortino, 2),
        'Validation_CAGR': round(best_val_cagr, 2),
        'Validation_Sortino': round(best_val_sortino, 2),
        'Fit_Val_Sortino_Gap': round(abs(best_fit_sortino - best_val_sortino), 2),  # NEW: overfitting indicator to track over time
        'OOS_CAGR': round(oos_cagr, 2),
        'OOS_Max_DD': round(oos_dd, 2),
        'OOS_Sortino': round(oos_sortino, 2),
        'OOS_Sniper_Trades': oos_bb_trades,
        'OOS_MR_Trades': oos_mr_trades,
        'Bull_BB_Tgt': best_params['bull']['bb_tgt'],
        'Bull_BB_Stop': best_params['bull']['bb_stop'],
        'Bull_BB_Risk': best_params['bull']['bb_risk'],
        'Bull_MR_Time': best_params['bull']['mr_time'],
        'Bull_MR_Pos_Size': best_params['bull']['mr_pos_size'],
        'Bear_BB_Tgt': best_params['bear']['bb_tgt'],
        'Bear_BB_Stop': best_params['bear']['bb_stop'],
        'Bear_BB_Risk': best_params['bear']['bb_risk'],
        'Bear_MR_Time': best_params['bear']['mr_time'],
        'Bear_MR_Pos_Size': best_params['bear']['mr_pos_size']
    })

# ==========================================
# 5. FINAL EXPORT & ANALYSIS
# ==========================================
results_df = pd.DataFrame(wfo_results)

# Save to Drive (PROJECT_DIR), not local /content -- a runtime crash after this
# line wiped out the previous run's results because they were only ever
# written to ephemeral local disk. Set PROJECT_DIR to match your Drive setup.
PROJECT_DIR = '/content/drive/MyDrive/NSE_Trading_System'
output_path = f'{PROJECT_DIR}/WFO_Dual_Brain_Optimization_v3_dd_fix.csv'
results_df.to_csv(output_path, index=False)
print(f"Results saved to: {output_path}")

print("\nWALK-FORWARD OPTIMIZATION COMPLETE")
print(f"File Saved: {output_path}")
print("\n--- Summary of Out-Of-Sample Performance (per-window average -- can overstate true performance, see below) ---")
print(f"Average OOS CAGR: {results_df['OOS_CAGR'].mean():.2f}%")
print(f"Median OOS CAGR: {results_df['OOS_CAGR'].median():.2f}%")
print(f"Average OOS Max DD: {results_df['OOS_Max_DD'].mean():.2f}%")

# ==========================================
# 6. CHAINED FULL-PERIOD ANALYSIS -- the honest number
# ==========================================
# Per-window CAGR/DD are each computed on an independently-reset capital
# base and can't reveal what a REAL continuously-deployed strategy would
# have experienced -- specifically, a multi-year losing streak spanning
# several windows compounds into a much deeper drawdown than any single
# window's isolated Max DD can show. This chains all 14 OOS windows'
# returns into one continuous equity curve to get the true numbers.
print("\n--- Chained Full-Period OOS Performance (the honest number) ---")
chained_equity = pd.Series([1.0] + list(pd.Series([1 + r for r in chained_oos_returns]).cumprod()))
chained_days = len(chained_oos_returns)
chained_years = chained_days / 252  # approx trading days/year
chained_total_return = chained_equity.iloc[-1] - 1
chained_cagr = ((chained_equity.iloc[-1]) ** (1 / chained_years) - 1) * 100 if chained_years > 0 else 0
chained_dd = ((chained_equity - chained_equity.cummax()) / chained_equity.cummax()).min() * 100

first_test_year = windows[0][3][0].year
last_test_year = windows[-1][3][-1].year
print(f"Total compounded return, {first_test_year}-{last_test_year}: {chained_total_return*100:.2f}%")
print(f"Chained CAGR (true compounded annual growth): {chained_cagr:.2f}%")
print(f"Chained Max DD (true multi-year peak-to-trough, NOT visible in any single window): {chained_dd:.2f}%")

# EXPORT the actual chained curve for direct visual verification -- don't
# just trust the summary print above. Includes the running drawdown series
# so you can see exactly WHERE the deepest point occurs and which
# window(s) it spans, rather than reasoning about it abstractly.
all_test_dates = []
for w in windows:
    all_test_dates.extend(w[3])  # w[3] = test_dates for that window
chained_dates = [all_test_dates[0]] + all_test_dates  # +1 to match the leading 1.0 anchor point

chained_curve_df = pd.DataFrame({
    'Date': chained_dates[:len(chained_equity)],
    'Chained_Equity_Normalized': chained_equity.values,
    'Running_Peak': chained_equity.cummax().values,
    'Drawdown_Pct': ((chained_equity - chained_equity.cummax()) / chained_equity.cummax() * 100).values
})
chained_curve_path = f'{PROJECT_DIR}/chained_equity_curve_seed{RANDOM_SEED}.csv'
chained_curve_df.to_csv(chained_curve_path, index=False)
print(f"\nFull chained equity curve (for plotting/verification) saved to: {chained_curve_path}")
deepest_dd_row = chained_curve_df.loc[chained_curve_df['Drawdown_Pct'].idxmin()]
print(f"Deepest drawdown point: {deepest_dd_row['Date']} at {deepest_dd_row['Drawdown_Pct']:.2f}%")
print("\nCompare Chained Max DD against your actual survival constraint (15-20% ceiling) --")
print("this is the number that matters for real deployment, not any individual window's DD.")

print("\n--- Overfitting Diagnostic ---")
print(f"Average Fit/Validation Sortino gap: {results_df['Fit_Val_Sortino_Gap'].mean():.2f}")
print("NOTE: this raw gap can look inflated due to Sortino's known small-sample fragility")
print("(near-zero downside deviation can spike the ratio). The actual selection score caps")
print("normalized Sortino at 1.0, so this diagnostic is informative but not literally what")
print("was optimized against -- judge overfitting primarily by OOS CAGR dispersion instead.")
