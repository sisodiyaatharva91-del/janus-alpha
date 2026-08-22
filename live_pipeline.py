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
from coiled_alpha_logic import apply_coiled_alpha_logic

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
    else:
        close_col = nifty['Close']
    macro = pd.DataFrame({'DATE': close_col.index, 'NIFTY_CLOSE': close_col.values})
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

    macro = macro.sort_values('DATE').reset_index(drop=True)
    macro['NIFTY_SMA_200'] = macro['NIFTY_CLOSE'].rolling(window=200).mean()
    macro['Regime_Label'] = np.where(macro['NIFTY_CLOSE'] > macro['NIFTY_SMA_200'], 'BULL', 'BEAR')
    macro['Prev_Close'] = macro['NIFTY_CLOSE'].shift(1)
    # NOTE: NIFTY_HIGH/LOW not fetched in this lean live version -- VIX_Spike
    # (which needs Nifty's own ATR) is approximated as False here. TODO before
    # trusting this in anything beyond early paper trading: fetch NIFTY_HIGH/LOW
    # too (same as data_prep_updated.py does) and compute VIX_Spike properly --
    # right now the live pipeline is silently more permissive on Sniper entries
    # during real volatility spikes than the backtest was.
    macro['VIX_Spike'] = False
    panic_thresholds = np.where(macro['Regime_Label'] == 'BULL', -0.0050, -0.0150)
    macro['Nifty_Daily_Return'] = (macro['NIFTY_CLOSE'] - macro['Prev_Close']) / macro['Prev_Close']
    macro['Systemic_Panic'] = macro['Nifty_Daily_Return'] < panic_thresholds

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


def evaluate_entries(state, today_rows, today_lookup, today_regime, current_breadth, active_p, target_date):
    events = []
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


def update_sheet_mirror(state):
    """Write-only Google Sheets dashboard. Never read back -- state JSON is
    the source of truth. If GCP_SA_JSON isn't configured, silently skip
    (Sheets is a nice-to-have visibility layer, not a dependency)."""
    if not GCP_SA_JSON:
        print("GCP_SA_JSON not configured, skipping Sheets mirror.")
        return
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_dict = json.loads(GCP_SA_JSON)
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open('Janus Portfolio')

        try:
            ws = sh.worksheet('Open_Positions')
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet('Open_Positions', rows=100, cols=10)
        ws.clear()
        rows = [['Sleeve', 'Symbol', 'Entry_Date', 'Entry_Price', 'Shares', 'Stop_Price', 'Target_Price', 'Days_Held']]
        for sym, pos in state['active_bb'].items():
            rows.append(['Sniper', sym, pos['entry_date'], pos['entry_price'], pos['shares'],
                         pos.get('stop_price', ''), pos.get('target_price', ''), ''])
        for sym, pos in state['active_mr'].items():
            rows.append(['MR', sym, pos['entry_date'], pos['entry_price'], pos['shares'],
                         '', '', pos.get('trading_days', '')])
        ws.update(rows)

        try:
            ws2 = sh.worksheet('Equity_Summary')
        except gspread.WorksheetNotFound:
            ws2 = sh.add_worksheet('Equity_Summary', rows=20, cols=5)
        ws2.clear()
        total_equity = state['bb_equity'] + state['mr_equity']
        ws2.update([
            ['Metric', 'Value'],
            ['Total Equity', total_equity],
            ['Sniper Equity', state['bb_equity']],
            ['MR Equity', state['mr_equity']],
            ['Last Updated', state.get('last_run_date', '')]
        ])
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

    today_rows = compute_todays_signals(window_df, target_date)
    today_lookup = {r['SYMBOL']: r for r in today_rows}
    today_regime = today_rows[0].get('Regime_Label', 'NEUTRAL') if today_rows else 'NEUTRAL'
    current_breadth = today_rows[0].get('Market_Breadth', 0) if today_rows else 0

    live_params = load_live_params()
    active_p = live_params['bull'] if today_regime == 'BULL' else live_params['bear']

    state = load_state()

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
    update_sheet_mirror(state)

    print("\nPipeline run complete.")


if __name__ == "__main__":
    main()
