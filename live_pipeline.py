"""
live_pipeline.py
------------------
Main daily execution script. Run by GitHub Actions Mon-Fri after NSE close.

Pipeline:
  1. Data Updater      -> fetch today's NSE bhavcopy + updated Nifty data,
                           append to master raw parquet
  2. Quantitative Engine -> run apply_coiled_alpha_logic + apply_mean_reversion_logic
                           on a trailing window (reuses PRODUCTION code, not a
                           reimplementation -- this is what guarantees live
                           signals match what was backtested)
  3. Portfolio Evaluator -> load state/paper_portfolio_state.json (source of
                           truth), evaluate exits for open positions, evaluate
                           new entries using live_params.json, update state
  4. Reporting          -> push a Telegram report, regenerate the Google Sheet
                           mirror (write-only, never read back)

State (state/paper_portfolio_state.json) and the updated master parquet are
both written locally; the GitHub Actions workflow commits them back to the
repo after this script exits successfully.
"""

import pandas as pd
import numpy as np
import requests
import zipfile
import io
import json
import os
import sys
from datetime import datetime, timedelta
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coiled_alpha_logic import (
    apply_coiled_alpha_logic,
    compute_macro_regime,       # SHARED with data_prep_updated.py -- do not
                                # reimplement the macro gates here again
)

# ==========================================
# CONFIGURATION
# ==========================================
MASTER_RAW_PARQUET = 'NSE_EQ_Master_Raw.parquet'   # append-only raw OHLCV, git-committed
DEPLOYMENT_WINDOW_DAYS = 450   # trailing window recomputed each run (>=200 for SMA200 + buffer)
MASTER_RETENTION_DAYS = 1095   # rolling 3-year retention on the SAVED master file -- keeps the
                                # repo file bounded in size indefinitely. Matches
                                # trim_master_for_github.py's one-time initial trim. Must stay
                                # comfortably larger than DEPLOYMENT_WINDOW_DAYS*1.6 (~720 days).
STATE_PATH = 'state/paper_portfolio_state.json'
LIVE_PARAMS_PATH = 'live_params.json'
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    # CONFIRMED REQUIRED via manual curl testing: without Referer, requests to
    # this endpoint either hang/timeout or return NSE's own custom "file
    # doesn't exist" page (served with HTTP 200, not a proper 404). This is
    # NOT bot-fingerprinting/CAPTCHA -- adding these headers alone was enough.
}

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
GCP_SA_JSON = os.environ.get('GCP_SA_JSON')  # for the Sheets mirror

MAX_GAP_LOSS_PCT = 0.03
ASSUMED_WORST_CASE_GAP_PCT = 0.20
SLIPPAGE_TAX_PCT = 0.15

# Idle yield on uninvested sleeve cash. MUST match wfo_engine_updated.py, or
# live equity drifts from the backtest that validated these parameters for a
# reason that has nothing to do with trading. Until 2026-08-22 the backtest
# credited yield and live credited NONE (finding #29), so live was structurally
# behind by roughly the idle fraction times the rate, every single day.
IDLE_YIELD_PCT = 4.0           # keep equal to wfo_engine_updated.IDLE_YIELD_PCT
TRADING_DAYS_PER_YEAR = 252    # keep equal to wfo_engine_updated.TRADING_DAYS_PER_YEAR
MAX_YIELD_CATCHUP_DAYS = 25    # refuse to credit more than this in one run


# ==========================================
# MODULE 1: DATA UPDATER
# ==========================================
def fetch_todays_bhavcopy(target_date):
    """Fetch a single day's NSE bhavcopy. Same source/format logic as Step 1's
    scraper, kept in sync manually -- reused here (not reimplemented) so live
    data matches backtest data exactly."""
    FORMAT_CHANGE_DATE = datetime(2024, 6, 8)
    try:
        if target_date < FORMAT_CHANGE_DATE:
            year = target_date.strftime('%Y')
            month_caps = target_date.strftime('%b').upper()
            date_str = target_date.strftime('%d%b%Y').upper()
            url = f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{year}/{month_caps}/cm{date_str}bhav.csv.zip"
            is_new_format = False
        else:
            date_str = target_date.strftime('%Y%m%d')
            url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
            is_new_format = True

        response = requests.get(url, headers=HEADERS, timeout=20)
        if response.status_code != 200:
            return None, f"HTTP {response.status_code}"

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            with z.open(z.namelist()[0]) as f:
                df = pd.read_csv(f)
                df.columns = df.columns.str.strip()
                if not is_new_format:
                    if "SERIES" not in df.columns: return None, "missing SERIES column"
                    df = df[df["SERIES"] == "EQ"]
                    df = df[["SYMBOL", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY"]]
                else:
                    if "SctySrs" not in df.columns: return None, "missing SctySrs column"
                    df = df[df["SctySrs"] == "EQ"]
                    df = df[["TckrSymb", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"]]
                df.columns = ["SYMBOL", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]
                # DATE NORMALIZATION FIX: target_date carries whatever time-of-day
                # the script happened to run at (e.g. 14:13:07 UTC from the cron
                # trigger), NOT midnight. Historical data in the master parquet is
                # always midnight-normalized (00:00:00). Without stripping the time
                # component here, this row's DATE would never exact-match against
                # pd.to_datetime(target_date).normalize() later in
                # compute_todays_signals -- the row exists, gets merged fine (merge
                # logic only uses >= comparisons), but silently becomes invisible
                # to the exact-equality "today's rows" filter. Strip it at the
                # earliest possible point instead.
                df["DATE"] = pd.Timestamp(target_date.date())
                return df, None
    except Exception as e:
        return None, str(e)


def find_latest_available_bhavcopy(max_days_back=5):
    """Search backward starting from YESTERDAY (not today) for the most
    recent date NSE has actually published a bhavcopy for.

    CRITICAL FIX: the original version of this pipeline assumed
    datetime.today() was always the right date to fetch -- but NSE does not
    publish a day's bhavcopy during that day's own trading session, and even
    after close there's no guarantee of same-day availability (settlement
    processing delays, minor site issues, etc.) -- there needs to be slack.
    Starting from yesterday and searching backward handles weekends,
    holidays, AND ordinary publishing delays uniformly, without needing a
    hardcoded NSE holiday calendar.

    Returns (date, dataframe). Raises if nothing found within max_days_back
    -- that many consecutive failures is a real problem (outage, URL pattern
    change) worth a loud error, not silent retry-forever.
    """
    candidate = datetime.today() - timedelta(days=1)
    attempts = []
    for _ in range(max_days_back):
        df, err = fetch_todays_bhavcopy(candidate)
        if df is not None:
            print(f"Found latest available bhavcopy: {candidate.date()}")
            return candidate, df
        attempts.append((str(candidate.date()), err))
        candidate -= timedelta(days=1)
    raise RuntimeError(
        f"No bhavcopy found in the last {max_days_back} days -- this is unusual "
        f"enough to be a real problem (outage, filename pattern change), not a "
        f"normal holiday gap. Attempts: {attempts}"
    )


def fetch_nifty_window(days_back=DEPLOYMENT_WINDOW_DAYS):
    """Fetch enough trailing Nifty history for the RS/regime calcs."""
    end = datetime.today()
    start = end - timedelta(days=int(days_back * 1.6))  # buffer for weekends/holidays
    nifty = yf.download('^NSEI', start=start, end=end + timedelta(days=1), progress=False)
    if nifty.empty:
        return None
    if isinstance(nifty.columns, pd.MultiIndex):
        close_col = nifty['Close'].iloc[:, 0]
        high_col = nifty['High'].iloc[:, 0]
        low_col = nifty['Low'].iloc[:, 0]
    else:
        close_col = nifty['Close']
        high_col = nifty['High']
        low_col = nifty['Low']

    # NIFTY_HIGH / NIFTY_LOW are REQUIRED, not optional. compute_macro_regime
    # needs Nifty's own true range for VIX_Spike. Until 2026-08-22 this
    # function returned CLOSE only and the caller set VIX_Spike = False, so
    # live never blocked Sniper entries on a volatility spike while the
    # backtest did. yfinance was already downloading High and Low; they were
    # simply being thrown away.
    macro = pd.DataFrame({
        'DATE': close_col.index,
        'NIFTY_CLOSE': close_col.values,
        'NIFTY_HIGH': high_col.values,
        'NIFTY_LOW': low_col.values,
    })
    macro['DATE'] = pd.to_datetime(macro['DATE']).dt.tz_localize(None).dt.normalize()
    return macro


def update_master_data():
    """Finds and appends the most recently PUBLISHED bhavcopy (not
    necessarily "today" -- see find_latest_available_bhavcopy) to the master
    raw parquet. Returns (actual_date_used, trailing_window_df)."""
    actual_date, new_day_df = find_latest_available_bhavcopy()
    print(f"Fetched {len(new_day_df)} symbols for {actual_date.date()}")

    if os.path.exists(MASTER_RAW_PARQUET):
        master_df = pd.read_parquet(MASTER_RAW_PARQUET)
        master_df['DATE'] = pd.to_datetime(master_df['DATE']).dt.normalize()
    else:
        raise RuntimeError(f"{MASTER_RAW_PARQUET} not found. Initialize it first by copying your "
                            f"validated NSE_EQ_2015_Fast.parquet (post gap-fix) to this filename.")

    new_day_df['DATE'] = pd.to_datetime(new_day_df['DATE']).dt.normalize()
    combined = pd.concat([master_df, new_day_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=['DATE', 'SYMBOL'], keep='last')
    combined = combined.sort_values(['DATE', 'SYMBOL']).reset_index(drop=True)

    # ROLLING WINDOW TRIM: without this, the saved master parquet grows by one
    # day's worth of rows every single run, forever -- exactly the GitHub file
    # size problem that required a manual one-time trim to fix once already.
    # Keep MASTER_RETENTION_DAYS of trailing history (must stay >= what
    # compute_todays_signals actually needs -- see DEPLOYMENT_WINDOW_DAYS
    # above -- MASTER_RETENTION_DAYS should always be set comfortably larger
    # than DEPLOYMENT_WINDOW_DAYS*1.6, not equal to it, so there's no risk of
    # accidentally trimming away data the signal computation still needs).
    retention_cutoff = pd.to_datetime(actual_date) - timedelta(days=MASTER_RETENTION_DAYS)
    combined = combined[combined['DATE'] >= retention_cutoff].copy()

    combined.to_parquet(MASTER_RAW_PARQUET, engine='pyarrow', compression='snappy')
    print(f"Master raw parquet updated: {len(combined):,} total rows "
          f"(rolling {MASTER_RETENTION_DAYS}-day window, oldest date now {combined['DATE'].min().date()})")

    cutoff = pd.to_datetime(actual_date) - timedelta(days=int(DEPLOYMENT_WINDOW_DAYS * 1.6))
    window_df = combined[combined['DATE'] >= cutoff].copy()
    return actual_date, window_df


# ==========================================
# MODULE 2: QUANTITATIVE ENGINE
# ==========================================
def compute_todays_signals(window_df, target_date):
    """Runs the SAME production signal logic used in the backtest. Also
    computes Regime_Label / VIX_Spike / Systemic_Panic / Market_Breadth --
    the latter is already inside apply_coiled_alpha_logic; the macro regime
    fields need the Nifty fetch."""
    macro = fetch_nifty_window()
    if macro is None:
        raise RuntimeError("Could not fetch Nifty data -- cannot compute regime/RS.")

    window_df['DATE'] = pd.to_datetime(window_df['DATE']).dt.normalize()
    if 'TICKER' in window_df.columns and 'SYMBOL' not in window_df.columns:
        window_df = window_df.rename(columns={'TICKER': 'SYMBOL'})

    print("Running Coiled Alpha signal logic...")
    signals_df = apply_coiled_alpha_logic(window_df, nifty_df=macro)

    # ONE shared macro implementation, see coiled_alpha_logic.py. This
    # replaces a hand-copied block that had drifted from the backtest's
    # version: VIX_Spike used to be hardcoded False here.
    #
    # Regime_Label and VIX_Spike come back LAGGED one trading session (the
    # Sniper fills at OPEN, so it may only use the previous close);
    # Systemic_Panic comes back unlagged (MR fills at CLOSE).
    macro = compute_macro_regime(macro)

    signals_df = signals_df.merge(
        macro[['DATE', 'Regime_Label', 'VIX_Spike', 'Systemic_Panic']], on='DATE', how='left'
    )
    signals_df['Regime_Label'] = signals_df['Regime_Label'].ffill().fillna('NEUTRAL')
    signals_df['VIX_Spike'] = signals_df['VIX_Spike'].ffill().fillna(False).astype(bool)
    signals_df['Systemic_Panic'] = signals_df['Systemic_Panic'].ffill().fillna(False).astype(bool)

    # MR sleeve logic (same as apply_mean_reversion_logic in data_prep_updated.py)
    signals_df['MR_Is_Liquid'] = signals_df['Daily_Turnover_Rank'] >= 0.70
    signals_df['Is_Quality'] = signals_df['CLOSE'] >= 100
    signals_df['SMA_200'] = signals_df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(200).mean())
    signals_df['SMA_5'] = signals_df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(5).mean())
    delta = signals_df.groupby('SYMBOL')['CLOSE'].diff()
    up = delta.clip(lower=0); down = -1 * delta.clip(upper=0)
    ema_up = up.groupby(signals_df['SYMBOL']).transform(lambda x: x.ewm(com=1, adjust=False).mean())
    ema_down = down.groupby(signals_df['SYMBOL']).transform(lambda x: x.ewm(com=1, adjust=False).mean())
    signals_df['RSI_2'] = 100 - (100 / (1 + (ema_up / (ema_down + 1e-8))))
    signals_df['SMA_20'] = signals_df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(20).mean())
    signals_df['STD_20'] = signals_df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(20).std())
    signals_df['Lower_BB_2_5'] = signals_df['SMA_20'] - (2.5 * signals_df['STD_20'])
    signals_df['IBS'] = (signals_df['CLOSE'] - signals_df['LOW']) / (signals_df['HIGH'] - signals_df['LOW'] + 1e-8)
    signals_df['MR_Base_Signal'] = (
        signals_df['MR_Is_Liquid'] & signals_df['Is_Quality'] &
        (signals_df['CLOSE'] > signals_df['SMA_200']) & (signals_df['RSI_2'] < 10) &
        (signals_df['CLOSE'] < signals_df['Lower_BB_2_5']) & (signals_df['IBS'] < 0.25)
    )
    mr_signals = signals_df[signals_df['MR_Base_Signal']].copy()
    mr_signals['Daily_Rank'] = mr_signals.groupby('DATE')['IBS'].rank(method='first', ascending=True)
    valid_mask = mr_signals['Daily_Rank'] <= 5
    signals_df['MR_Base_Signal'] = False
    signals_df.loc[mr_signals[valid_mask].index, 'MR_Base_Signal'] = True

    signals_df['Is_Large_Cap'] = signals_df['Daily_Turnover_Rank'] >= 0.90
    invalid_mr = (signals_df['Regime_Label'] == 'BULL') & (~signals_df['Is_Large_Cap'])
    signals_df.loc[invalid_mr, 'MR_Base_Signal'] = False

    todays_date = pd.to_datetime(target_date).normalize()
    todays_rows = signals_df[signals_df['DATE'] == todays_date]
    if todays_rows.empty:
        raise RuntimeError(f"No signal rows found for {todays_date.date()} after indicator computation -- "
                            f"check DEPLOYMENT_WINDOW_DAYS is large enough / today's bhavcopy actually got merged.")
    return todays_rows.to_dict('records')


# ==========================================
# MODULE 3: PORTFOLIO & EXIT/ENTRY EVALUATOR
# ==========================================
def trading_days_since(window_df, last_date_str, target_date):
    """How many NSE trading sessions fall in (last_run_date, target_date].

    Counted from the bhavcopy panel itself rather than from a hardcoded holiday
    calendar, so it stays correct through NSE's irregular holidays without
    anything to maintain. Returns 1 when there is no last_run_date (a fresh or
    just-reset state file), which is the normal single-session case.

    This exists because a missed run must not silently skip yield. GitHub
    Actions outages happen, and the backtest accrues on every trading session
    with no concept of a missed one -- so live has to catch up to stay at
    parity.
    """
    if not last_date_str:
        return 1
    try:
        last = pd.to_datetime(last_date_str).normalize()
        this = pd.to_datetime(target_date).normalize()
    except Exception as e:
        print(f"WARNING: could not parse dates for the yield catch-up ({e}); "
              f"crediting a single session.")
        return 1
    dates = pd.to_datetime(pd.Series(window_df['DATE'].unique())).dt.normalize()
    return int(((dates > last) & (dates <= this)).sum())


def accrue_idle_yield(state, window_df, target_date):
    """Credit idle yield on uninvested sleeve cash, matching the backtest.

    Called from main() BEFORE the allocation rebalance and before exits, which
    is the order run_headless_simulation uses (yield -> rebalance -> exits ->
    entries). Order matters: yield raises cash, cash feeds the rebalance base,
    and the rebalance base sizes the day's entries.

    Compounds over n sessions with (1 + r)**n - 1 rather than n * r, because
    the engine adds each day's yield to cash before the next day's accrual, so
    its cash compounds too. For a single session the two are identical; they
    only differ on a catch-up.
    """
    n_days = trading_days_since(window_df, state.get('last_run_date', ''), target_date)

    if n_days <= 0:
        print("Idle yield: 0 new trading sessions, nothing accrued.")
        return 0.0

    if n_days > MAX_YIELD_CATCHUP_DAYS:
        # Loud, not silent. A number this large means the state file is stale
        # or corrupt, and quietly crediting a year of yield in one run would
        # be a far worse outcome than an obviously wrong-looking report.
        print(f"WARNING: idle yield asked to cover {n_days} trading sessions, "
              f"which is more than MAX_YIELD_CATCHUP_DAYS={MAX_YIELD_CATCHUP_DAYS}. "
              f"Capping. Check state['last_run_date'] -- this usually means the "
              f"pipeline has not run for a long time or the state file is stale.")
        n_days = MAX_YIELD_CATCHUP_DAYS

    factor = (1 + (IDLE_YIELD_PCT / 100) / TRADING_DAYS_PER_YEAR) ** n_days - 1
    bb_yield = max(0.0, state['bb_cash']) * factor
    mr_yield = max(0.0, state['mr_cash']) * factor

    state['bb_cash'] += bb_yield
    state['bb_equity'] += bb_yield
    state['mr_cash'] += mr_yield
    state['mr_equity'] += mr_yield

    print(f"Idle yield: {n_days} session(s) at {IDLE_YIELD_PCT}%/yr -> "
          f"Sniper +{bb_yield:,.2f}, MR +{mr_yield:,.2f}")
    return bb_yield + mr_yield


def is_new_trading_date(target_date):
    """True if target_date is genuinely newer than the last processed session.

    FINDING #33 (2026-08-22). state['last_run_date'] was written on every run
    and never read, so nothing stopped the pipeline re-processing a bhavcopy it
    had already processed. That happens in practice: the schedule is Mon-Fri,
    so every NSE holiday makes find_latest_available_bhavcopy fall back to the
    previous session, and any manual workflow_dispatch or Actions retry does
    the same.

    What a duplicate run did to the state file:
      * every MR position aged an extra session -- evaluate_exits does
        `pos['trading_days'] += 1` unconditionally, so a position hit its time
        stop early. On an mr_time of 5 sessions, one duplicate run is a 20%
        distortion of the holding period, biased toward premature exits.
      * equity_curve_log gained a second row for the same date, quietly
        corrupting any drawdown or CAGR computed from it later.
      * any Sniper slot left unfilled could fill against the SAME bar's prices
        on the second pass.
      * and once idle yield exists in live, it accrues twice.

    FAILS OPEN, deliberately: if the state file cannot be read or its date
    cannot be parsed, this returns True with a loud warning rather than
    blocking. A silent permanent halt is a worse failure mode for a scheduled
    job than one duplicated session, and last_run_date is written by this same
    code in a known format, so a parse failure is close to impossible.

    Override with JANUS_FORCE_RERUN=1 -- intended for replaying a session after
    fixing a bug, and it is on the caller to reset the state file first.
    """
    force = os.environ.get('JANUS_FORCE_RERUN', '') == '1'

    try:
        last_raw = load_state().get('last_run_date', '')
    except Exception as e:
        print(f"WARNING: could not read state for the duplicate-run guard ({e}); "
              f"proceeding without it.")
        return True

    if not last_raw:
        return True   # fresh or freshly reset state file

    try:
        last = pd.to_datetime(last_raw).normalize()
        this = pd.to_datetime(target_date).normalize()
    except Exception as e:
        print(f"WARNING: could not parse last_run_date={last_raw!r} ({e}); "
              f"proceeding without the guard.")
        return True

    if this > last:
        return True

    if force:
        print(f"JANUS_FORCE_RERUN=1: re-processing {this.date()} even though "
              f"last_run_date is {last.date()}. State was NOT reset for you -- "
              f"MR holding periods and the equity curve will double-count.")
        return True

    print(f"\nAlready processed {this.date()} (last_run_date={last.date()}). "
          f"Nothing to do.\n"
          f"This is the EXPECTED path on an NSE holiday: the schedule runs "
          f"Mon-Fri, no new bhavcopy was published, so the newest available one "
          f"is the session already in the state file.\n"
          f"Exiting without touching state. Set JANUS_FORCE_RERUN=1 to override.")
    return False


def load_state():
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state):
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def load_live_params():
    with open(LIVE_PARAMS_PATH) as f:
        data = json.load(f)
    return data['params']


def evaluate_exits(state, today_lookup, today_regime, active_p, target_date):
    events = []
    for sym, pos in list(state['active_bb'].items()):
        if sym not in today_lookup: continue
        row = today_lookup[sym]
        exit_triggered, exit_price, reason = False, 0, None
        if row['OPEN'] <= pos['stop_price']: exit_triggered, exit_price, reason = True, row['OPEN'], 'gap_down_stop'
        elif row['LOW'] <= pos['stop_price']: exit_triggered, exit_price, reason = True, pos['stop_price'], 'stop_hit'
        elif row['OPEN'] >= pos['target_price']: exit_triggered, exit_price, reason = True, row['OPEN'], 'gap_up_target'
        elif row['HIGH'] >= pos['target_price']: exit_triggered, exit_price, reason = True, pos['target_price'], 'target_hit'
        elif row.get('BB_Exhaustion_Today') and row['CLOSE'] > pos['entry_price']: exit_triggered, exit_price, reason = True, row['CLOSE'], 'exhaustion_exit'

        if exit_triggered:
            rev = pos['shares'] * exit_price
            net_rev = rev - ((rev * (SLIPPAGE_TAX_PCT / 100)) + min(rev * 0.0015, 20.0))
            profit = net_rev - pos['net_cost']
            state['bb_cash'] += net_rev
            state['bb_equity'] += profit
            state['closed_trades_log'].append({
                'sleeve': 'Sniper', 'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': str(target_date.date()),
                'entry_price': pos['entry_price'], 'exit_price': exit_price, 'shares': pos['shares'],
                'pnl': profit, 'exit_reason': reason
            })
            events.append(f"CLOSED Sniper {sym}: {reason}, PnL {profit:,.0f}")
            del state['active_bb'][sym]

    for sym, pos in list(state['active_mr'].items()):
        if sym not in today_lookup: continue
        row = today_lookup[sym]
        pos['trading_days'] += 1
        exit_triggered, exit_price, reason = False, 0, None
        if row['CLOSE'] > row.get('SMA_5', float('inf')): exit_triggered, exit_price, reason = True, row['CLOSE'], 'sma5_cross'
        elif pos['trading_days'] >= 4 and row['CLOSE'] < pos['entry_price']: exit_triggered, exit_price, reason = True, row['CLOSE'], 'time_stop_loss'
        elif pos['trading_days'] >= active_p['mr_time']: exit_triggered, exit_price, reason = True, row['CLOSE'], 'time_stop'

        if exit_triggered:
            rev = pos['shares'] * exit_price
            net_rev = rev - ((rev * (SLIPPAGE_TAX_PCT / 100)) + min(rev * 0.0015, 20.0))
            profit = net_rev - pos['net_cost']
            state['mr_cash'] += net_rev
            state['mr_equity'] += profit
            state['closed_trades_log'].append({
                'sleeve': 'MR', 'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': str(target_date.date()),
                'entry_price': pos['entry_price'], 'exit_price': exit_price, 'shares': pos['shares'],
                'pnl': profit, 'exit_reason': reason
            })
            events.append(f"CLOSED MR {sym}: {reason}, PnL {profit:,.0f}")
            del state['active_mr'][sym]

    return events


def rebalance_allocation(state, today_regime, current_breadth):
    """Split capital between the sleeves on regime AND breadth jointly.

    EXTRACTED OUT OF evaluate_entries ON 2026-08-22 so that main() can call it
    in the same position as wfo_engine's run_headless_simulation, which runs it
    BEFORE exits:

        engine : yield -> REBALANCE -> Sniper exits -> MR exits -> MR entries -> Sniper entries
        live   : (no yield) -> exits -> [rebalance was in here] -> entries

    Why the order is not cosmetic: bb_equity is a running sleeve balance, not a
    mark-to-market. An exit adds its realized profit to bb_equity/mr_equity, so
    rebalancing AFTER exits computes target_bb_equity off a different, larger
    base -- which then feeds every position size taken that day, since the
    Sniper entry block sizes off bb_equity three separate ways (risk-based
    shares, the 20% concentration cap, and gap_safe_shares) and is capped by
    bb_cash. Same signals, same params, different share counts.

    The engine is the reference implementation the Phase 1 parameters were
    fitted against, so live conforms to the engine, not the reverse.

    NOTE: the engine also accrues idle yield BEFORE this step, and live still
    has no yield accrual at all (separate open finding). When yield is added to
    live it must go before this call, not after.
    """
    total_equity = state['bb_equity'] + state['mr_equity']
    if today_regime == 'BULL':
        if current_breadth > 0.65: bb_frac, mr_frac = 0.80, 0.20
        elif current_breadth >= 0.50: bb_frac, mr_frac = 0.60, 0.40
        else: bb_frac, mr_frac = 0.35, 0.65
    else:
        bb_frac, mr_frac = 0.20, 0.80
    target_bb_equity, target_mr_equity = total_equity * bb_frac, total_equity * mr_frac
    state['bb_cash'] += (target_bb_equity - state['bb_equity'])
    state['mr_cash'] += (target_mr_equity - state['mr_equity'])
    state['bb_equity'], state['mr_equity'] = target_bb_equity, target_mr_equity
    return bb_frac, mr_frac


def evaluate_entries(state, today_rows, today_lookup, today_regime, current_breadth, active_p, target_date):
    events = []
    # Allocation rebalance deliberately NOT done here any more -- main() calls
    # rebalance_allocation() before evaluate_exits() to match the engine.

    systemic_panic_today = today_rows[0].get('Systemic_Panic', False) if today_rows else False
    if current_breadth < 0.50 and systemic_panic_today and state['mr_cash'] > 0:
        cands = [r for r in today_rows if r.get('MR_Base_Signal') and r['SYMBOL'] not in state['active_mr']]
        if cands:
            max_alloc = state['mr_equity'] * (active_p['mr_pos_size'] / 100)
            alloc = min(max_alloc, state['mr_cash'] / len(cands))
            for row in cands:
                cap_limit = row.get('Turnover_SMA_50', 1e12) * 0.05
                shares = int(min(alloc, cap_limit) / row['CLOSE'])
                if shares > 0 and state['mr_cash'] >= (cost := shares * row['CLOSE']):
                    state['mr_cash'] -= cost
                    state['active_mr'][row['SYMBOL']] = {
                        'entry_date': str(target_date.date()), 'entry_price': row['CLOSE'], 'shares': shares,
                        'net_cost': cost, 'trading_days': 0
                    }
                    events.append(f"OPENED MR {row['SYMBOL']}: {shares} shares @ {row['CLOSE']:.2f}")

    vix_spike_today = today_rows[0].get('VIX_Spike', False) if today_rows else False
    max_bb_pos = 0 if vix_spike_today else (6 if current_breadth > 0.65 else 3 if current_breadth >= 0.50 else 1)
    if max_bb_pos > 0 and state['bb_cash'] > 0 and len(state['active_bb']) < max_bb_pos:
        cands = sorted(
            [r for r in today_rows if r.get('BB_Enter_Today') and r['SYMBOL'] not in state['active_bb']],
            key=lambda x: (-x['RS_Percentile'], x['ATR_Contraction_Ratio'])
        )
        for row in cands:
            if len(state['active_bb']) >= max_bb_pos or state['bb_cash'] <= 0: break
            atr = row.get('Target_ATR')
            if pd.isna(atr) or atr <= 0: continue
            stop = row['OPEN'] - (active_p['bb_stop'] * atr)
            tgt = row['OPEN'] + (active_p['bb_tgt'] * atr)
            risk = row['OPEN'] - stop
            if risk <= 0: continue
            cap_limit = row.get('Turnover_SMA_50', 1e12) * 0.05
            gap_safe_shares = int((state['bb_equity'] * MAX_GAP_LOSS_PCT) / (row['OPEN'] * ASSUMED_WORST_CASE_GAP_PCT))
            shares = min(
                int((state['bb_equity'] * (active_p['bb_risk'] / 100)) / risk),
                int((state['bb_equity'] * 0.20) / row['OPEN']),
                int(cap_limit / row['OPEN']),
                gap_safe_shares
            )
            if shares > 0 and state['bb_cash'] >= (cost := shares * row['OPEN']):
                state['bb_cash'] -= cost
                state['active_bb'][row['SYMBOL']] = {
                    'entry_date': str(target_date.date()), 'entry_price': row['OPEN'], 'shares': shares,
                    'net_cost': cost, 'stop_price': stop, 'target_price': tgt,
                    'regime_at_entry': today_regime, 'breadth_at_entry': current_breadth
                }
                events.append(f"OPENED Sniper {row['SYMBOL']}: {shares} shares @ {row['OPEN']:.2f}, "
                              f"stop {stop:.2f}, target {tgt:.2f}")

    return events


# ==========================================
# MODULE 4: REPORTING
# ==========================================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured, skipping. Message would have been:\n", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print(f"Telegram send failed: {e}")


def _sheet_cell(v):
    """Coerce one value into something gspread can actually serialise.

    EVERY cell must pass through this. Two distinct things break the mirror,
    both found by test_sheets_payload.py on 2026-08-22:

      NaN / Infinity -- JSON has neither, so gspread raises mid-write. That
        fails DIRTY: some tabs have already been overwritten, so the sheet is
        left half-updated and the traceback is about serialisation rather than
        about the position that produced the NaN.

      numpy scalars -- np.float64 happens to subclass float, so an
        isinstance(v, float) check catches it, but np.int64 does NOT subclass
        int and sails straight through to `TypeError: Object of type int64 is
        not JSON serializable`. Share counts and prices arrive as numpy types
        whenever they came from a DataFrame row rather than from the JSON state
        file, so this is the normal path, not an exotic one.

    Hence .item() on anything numpy-shaped BEFORE the float checks, rather
    than trusting isinstance against Python's builtins.
    """
    if v is None or v == '':
        return ''
    if hasattr(v, 'item') and not isinstance(v, (str, bytes)):
        try:
            v = v.item()          # np.int64/np.float64/np.bool_ -> Python scalar
        except (ValueError, AttributeError):
            return str(v)         # 0-d arrays and friends: stringify, never crash
    if isinstance(v, float):
        if v != v or v in (float('inf'), float('-inf')):   # NaN / +-inf
            return ''
        return round(v, 2)
    if isinstance(v, (int, bool, str)):
        return v
    return str(v)                 # Timestamps, Decimals, anything unexpected


def _num(v, default=0.0):
    """A numeric value safe to do ARITHMETIC with -- distinct from _sheet_cell,
    which produces a value safe to DISPLAY.

    The idiom this replaces, `x = d.get('k') or 0`, is wrong for exactly the
    reason the VIX_Spike lag was wrong: bool(float('nan')) is True, so `nan or
    0` evaluates to nan rather than 0. The NaN then propagates through
    Market_Value, Unrealized_PnL, and -- worst of all -- the Cum_PnL
    accumulator, where one bad trade turns every later row into NaN.
    """
    if v is None or v == '':
        return default
    if hasattr(v, 'item') and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float('inf'), float('-inf')):
        return default
    return v if isinstance(v, int) else f


def _sessions_held(state, entry_date):
    """Trading sessions a position has been held, derived from
    equity_curve_log (the pipeline appends exactly one row per processed
    session, so counting rows counts sessions).

    Counts sessions STRICTLY AFTER entry_date. That choice makes this equal to
    the MR sleeve's own `trading_days` counter -- the number its time stop
    actually fires on -- instead of being off by one against it, and it gives
    Sniper positions the same meaning even though they carry no counter of
    their own. That missing counter is why Days_Held was blank for every
    Sniper row in the sheet before 2026-08-22.
    """
    log = state.get('equity_curve_log') or []
    if not log or not entry_date:
        return ''
    entry = str(entry_date)[:10]
    return len({str(e.get('date', ''))[:10] for e in log
                if str(e.get('date', ''))[:10] > entry})


def build_sheet_payloads(state, today_lookup=None, context=None):
    """state -> the exact row lists written to each tab.

    Split out from update_sheet_mirror as a pure function so it can be tested
    without gspread installed, without credentials and without network: the
    formatting is where the bugs live, not in the API call.
    """
    today_lookup = today_lookup or {}
    context = context or {}

    # ---------------------------- Open_Positions ----------------------
    open_rows = [['Sleeve', 'Symbol', 'Entry_Date', 'Sessions_Held', 'Shares',
                  'Entry_Price', 'Last_Close', 'Stop_Price', 'Target_Price',
                  'Pct_To_Stop', 'Pct_To_Target', 'Cost', 'Market_Value',
                  'Unrealized_PnL', 'Unrealized_Pct']]

    def _position_row(sleeve, sym, pos):
        # _num, not `or 0`: bool(float('nan')) is True in Python, so
        # `pos.get('shares') or 0` HANDS BACK THE NaN instead of replacing it,
        # and a NaN share count then propagates into Market_Value, Unrealized
        # and the JSON write. Same trap as the VIX_Spike lag.
        shares = _num(pos.get('shares'))
        entry_px = pos.get('entry_price')
        cost = pos.get('net_cost')
        if cost in (None, ''):
            cost = shares * entry_px if (shares and entry_px) else None

        last = (today_lookup.get(sym) or {}).get('CLOSE')
        stop = pos.get('stop_price', '')      # MR carries neither
        target = pos.get('target_price', '')

        mv = shares * last if (last and shares) else None
        unreal = mv - cost if (mv is not None and cost) else None
        unreal_pct = unreal / cost * 100 if (unreal is not None and cost) else None
        pct_stop = (last - stop) / last * 100 if (last and stop not in (None, '')) else None
        pct_target = (target - last) / last * 100 if (last and target not in (None, '')) else None

        return [sleeve, sym, _sheet_cell(pos.get('entry_date', '')),
                _sessions_held(state, pos.get('entry_date', '')),
                _sheet_cell(shares), _sheet_cell(entry_px), _sheet_cell(last),
                _sheet_cell(stop), _sheet_cell(target),
                _sheet_cell(pct_stop), _sheet_cell(pct_target),
                _sheet_cell(cost), _sheet_cell(mv),
                _sheet_cell(unreal), _sheet_cell(unreal_pct)]

    for sym, pos in (state.get('active_bb') or {}).items():
        open_rows.append(_position_row('Sniper', sym, pos))
    for sym, pos in (state.get('active_mr') or {}).items():
        open_rows.append(_position_row('MR', sym, pos))

    # ---------------------------- Trade_Log ---------------------------
    # state['closed_trades_log'] has been populated since day one and was
    # never surfaced anywhere -- the whole trade history existed only inside
    # the JSON state file.
    trades = list(state.get('closed_trades_log') or [])
    trades.sort(key=lambda t: (str(t.get('exit_date', '')), str(t.get('symbol', ''))))

    log_rows = [['Exit_Date', 'Sleeve', 'Symbol', 'Entry_Date', 'Shares',
                 'Entry_Price', 'Exit_Price', 'PnL', 'Return_Pct',
                 'Exit_Reason', 'Cum_PnL']]
    body, running = [], 0.0
    for t in trades:
        # _num throughout. A NaN pnl reaching `running` would not just blank one
        # cell -- it would make Cum_PnL NaN for that row and EVERY row after it,
        # because the accumulator itself becomes NaN. Realized PnL, Win Rate and
        # Profit Factor below read the same field.
        pnl = _num(t.get('pnl'))
        running += pnl
        shares = _num(t.get('shares'))
        entry_px = _num(t.get('entry_price'))
        basis = shares * entry_px
        body.append([_sheet_cell(t.get('exit_date', '')), t.get('sleeve', ''),
                     t.get('symbol', ''), _sheet_cell(t.get('entry_date', '')),
                     _sheet_cell(shares),
                     _sheet_cell(entry_px), _sheet_cell(t.get('exit_price')),
                     _sheet_cell(pnl),
                     _sheet_cell(pnl / basis * 100 if basis else None),
                     t.get('exit_reason', ''), _sheet_cell(running)])
    # Newest first so the useful end of the log is visible without scrolling.
    # Cum_PnL was accumulated chronologically, so each row still shows the
    # running total AS OF that trade.
    log_rows.extend(reversed(body))

    # ---------------------------- Equity_Summary -----------------------
    # _num on every pnl read: a NaN would make `> 0` False and `<= 0` False, so
    # the trade would vanish from BOTH gross_profit and gross_loss while still
    # counting in len(trades) -- a silently wrong win rate and profit factor.
    wins = [t for t in trades if _num(t.get('pnl')) > 0]
    gross_profit = sum(_num(t.get('pnl')) for t in wins)
    gross_loss = -sum(_num(t.get('pnl')) for t in trades if _num(t.get('pnl')) <= 0)

    # Open risk: what walking every Sniper stop from here would cost. MR has no
    # stop, so it contributes nothing and this understates total exposure --
    # read it as "Sniper risk to stops", which is what it is called below.
    open_risk = 0.0
    for sym, pos in (state.get('active_bb') or {}).items():
        last = _num((today_lookup.get(sym) or {}).get('CLOSE'))
        stop = _num(pos.get('stop_price'))
        if last and stop:
            open_risk += max(0.0, (last - stop) * _num(pos.get('shares')))

    summary_rows = [
        ['Metric', 'Value'],
        ['Last Updated', context.get('date', state.get('last_run_date', ''))],
        ['Regime', context.get('regime', '')],
        ['Market Breadth', _sheet_cell(context.get('breadth'))],
        ['Vol Spike (Nifty ATR proxy)', str(context.get('vix_spike', ''))],
        ['', ''],
        ['Total Equity', _sheet_cell((state.get('bb_equity') or 0)
                                     + (state.get('mr_equity') or 0))],
        ['Sniper Equity', _sheet_cell(state.get('bb_equity'))],
        ['MR Equity', _sheet_cell(state.get('mr_equity'))],
        ['Sniper Cash', _sheet_cell(state.get('bb_cash'))],
        ['MR Cash', _sheet_cell(state.get('mr_cash'))],
        ['', ''],
        ['Open Positions', len(state.get('active_bb') or {})
                           + len(state.get('active_mr') or {})],
        ['Sniper Risk to Stops', _sheet_cell(open_risk)],
        ['', ''],
        ['Closed Trades', len(trades)],
        ['Realized PnL', _sheet_cell(gross_profit - gross_loss)],
        ['Win Rate %', _sheet_cell(len(wins) / len(trades) * 100 if trades else None)],
        ['Profit Factor', _sheet_cell(gross_profit / gross_loss) if gross_loss > 0
                          else 'n/a (no losing trades yet)'],
    ]

    return {'Open_Positions': open_rows,
            'Trade_Log': log_rows,
            'Equity_Summary': summary_rows}


def update_sheet_mirror(state, today_lookup=None, context=None):
    """Write-only Google Sheets dashboard. Never read back -- state JSON is
    the source of truth. If GCP_SA_JSON isn't configured, silently skip
    (Sheets is a nice-to-have visibility layer, not a dependency).

    Every tab is rewritten in full on every run rather than appended to. That
    keeps the never-read-back invariant absolute: an append needs to know how
    many rows are already there, which means reading the sheet, which is
    exactly the coupling this design rejects. At roughly 100 trades a year the
    full rewrite stays trivially small.
    """
    if not GCP_SA_JSON:
        print("GCP_SA_JSON not configured, skipping Sheets mirror.")
        return

    # Built before the try block on purpose: a formatting bug should surface as
    # a real traceback, not get swallowed by the network-error handler below.
    payloads = build_sheet_payloads(state, today_lookup, context)

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_dict = json.loads(GCP_SA_JSON)
        scopes = ['https://www.googleapis.com/auth/spreadsheets',
                  'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open('Janus Portfolio')

        for tab, rows in payloads.items():
            n_rows = max(len(rows) + 20, 50)
            n_cols = max(len(rows[0]), 2)
            try:
                ws = sh.worksheet(tab)
                # Grow the grid BEFORE writing. add_worksheet's row count is a
                # hard grid limit, not a hint, and ws.clear() does not resize;
                # the old code created these tabs at rows=100, so the write
                # would have started failing once the trade log outgrew that.
                ws.resize(rows=n_rows, cols=n_cols)
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(tab, rows=n_rows, cols=n_cols)
            ws.clear()
            ws.update(rows)
            print(f"  Sheets: {tab} <- {len(rows) - 1} data row(s)")

        print("Sheet mirror updated.")
    except Exception as e:
        print(f"Sheet mirror update FAILED (non-fatal, continuing): {e}")


# ==========================================
# MAIN
# ==========================================
def main():
    print(f"{'='*60}\nLive pipeline run started at {datetime.today().date()}\n{'='*60}")

    # target_date is now DISCOVERED, not assumed -- see find_latest_available_bhavcopy.
    # NSE does not publish "today's" bhavcopy during/immediately after today's own
    # session; the correct date to process is whatever the most recently
    # PUBLISHED trading day actually is, which is usually yesterday but can be
    # further back around weekends/holidays/publishing delays.
    target_date, window_df = update_master_data()
    print(f"Processing data for actual trading date: {target_date.date()}")

    # --- DUPLICATE-RUN GUARD (finding #33) ---
    # Placed as early as target_date is known, so a holiday run also
    # skips the expensive signal computation. update_master_data above
    # is safe to have already run: it dedupes on (DATE, SYMBOL).
    if not is_new_trading_date(target_date):
        return

    today_rows = compute_todays_signals(window_df, target_date)
    today_lookup = {r['SYMBOL']: r for r in today_rows}
    today_regime = today_rows[0].get('Regime_Label', 'NEUTRAL') if today_rows else 'NEUTRAL'
    current_breadth = today_rows[0].get('Market_Breadth', 0) if today_rows else 0

    live_params = load_live_params()
    active_p = live_params['bull'] if today_regime == 'BULL' else live_params['bear']

    state = load_state()

    # Yield first, matching the engine order (yield -> rebalance ->
    # exits -> entries). This is a no-op unless --run-guard is also
    # applied: without the duplicate-run guard, a second run on the
    # same bhavcopy would accrue a second time.
    accrue_idle_yield(state, window_df, target_date)

    # ORDER MATTERS -- must match wfo_engine.run_headless_simulation:
    #   rebalance -> exits -> entries.
    # See rebalance_allocation's docstring for why.
    rebalance_allocation(state, today_regime, current_breadth)
    exit_events = evaluate_exits(state, today_lookup, today_regime, active_p, target_date)
    entry_events = evaluate_entries(state, today_rows, today_lookup, today_regime, current_breadth, active_p, target_date)

    total_equity = state['bb_equity'] + state['mr_equity']
    state['equity_curve_log'].append({'date': str(target_date.date()), 'total_equity': total_equity})
    state['last_run_date'] = str(target_date.date())
    save_state(state)

    report_lines = [
        f"*Janus Daily Report — {target_date.strftime('%Y-%m-%d')}*",
        f"Regime: {today_regime} | Breadth: {current_breadth:.3f}",
        f"Total Equity: {total_equity:,.0f} (Sniper: {state['bb_equity']:,.0f} | MR: {state['mr_equity']:,.0f})",
        f"Open positions: {len(state['active_bb'])} Sniper, {len(state['active_mr'])} MR",
        ""
    ]
    if exit_events:
        report_lines.append("*Exits:*")
        report_lines.extend(exit_events)
    if entry_events:
        report_lines.append("*Entries:*")
        report_lines.extend(entry_events)
    if not exit_events and not entry_events:
        report_lines.append("No trades today.")

    report = "\n".join(report_lines)
    print(report)
    send_telegram(report)
    update_sheet_mirror(state, today_lookup, {
        'date': str(target_date.date()),
        'regime': today_regime,
        'breadth': current_breadth,
        'vix_spike': today_rows[0].get('VIX_Spike', False) if today_rows else False,
    })

    print("\nPipeline run complete.")


if __name__ == "__main__":
    main()
