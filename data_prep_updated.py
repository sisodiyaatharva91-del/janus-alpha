import pandas as pd
import numpy as np
import yfinance as yf

# If running fresh in a Colab session:
# !pip install yfinance -q

from coiled_alpha_logic import (
    apply_coiled_alpha_logic,   # the new Sniper entry logic
    compute_macro_regime,       # the SHARED macro gates -- live_pipeline.py calls
                                # the same function, so the two cannot drift
)

# ==========================================
# 1. THE SIGNAL GENERATORS
# ==========================================
# apply_blue_box_logic has been REMOVED. Its two responsibilities are now
# split cleanly:
#   - Entry/exit signal generation (BB_Enter_Today, BB_Exhaustion_Today,
#     Target_ATR) + base turnover metrics + Market_Breadth
#     -> apply_coiled_alpha_logic (imported above)
#   - Mean reversion sleeve -> apply_mean_reversion_logic (unchanged, below)

def apply_mean_reversion_logic(df):
    if 'Turnover' not in df.columns:
        df['Turnover'] = df['CLOSE'] * df['VOLUME']

    df['MR_Is_Liquid'] = df['Daily_Turnover_Rank'] >= 0.70
    df['Is_Quality'] = df['CLOSE'] >= 100
    df['SMA_200'] = df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(200).mean())
    df['SMA_5'] = df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(5).mean())

    delta = df.groupby('SYMBOL')['CLOSE'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.groupby(df['SYMBOL']).transform(lambda x: x.ewm(com=1, adjust=False).mean())
    ema_down = down.groupby(df['SYMBOL']).transform(lambda x: x.ewm(com=1, adjust=False).mean())
    df['RSI_2'] = 100 - (100 / (1 + (ema_up / (ema_down + 1e-8))))

    df['SMA_20'] = df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(20).mean())
    df['STD_20'] = df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(20).std())
    df['Lower_BB_2_5'] = df['SMA_20'] - (2.5 * df['STD_20'])
    df['IBS'] = (df['CLOSE'] - df['LOW']) / (df['HIGH'] - df['LOW'] + 1e-8)

    df['MR_Base_Signal'] = (
        (df['MR_Is_Liquid'] == True) & (df['Is_Quality'] == True) &
        (df['CLOSE'] > df['SMA_200']) & (df['RSI_2'] < 10) &
        (df['CLOSE'] < df['Lower_BB_2_5']) & (df['IBS'] < 0.25)
    )

    signals = df[df['MR_Base_Signal']].copy()
    signals['Daily_Rank'] = signals.groupby('DATE')['IBS'].rank(method='first', ascending=True)
    valid_signals_mask = signals['Daily_Rank'] <= 5
    df['MR_Base_Signal'] = False
    df.loc[signals[valid_signals_mask].index, 'MR_Base_Signal'] = True
    return df

# ==========================================
# 2. LOAD RAW DATA
# ==========================================
print("Loading heavy raw data...")
df = pd.read_parquet('NSE_EQ_2015_Fast.parquet')

col_map = {str(c).lower(): str(c).upper() for c in df.columns}
df = df.rename(columns=col_map)
if 'TICKER' in df.columns and 'SYMBOL' not in df.columns:
    df = df.rename(columns={'TICKER': 'SYMBOL'})
df['DATE'] = pd.to_datetime(df['DATE']).dt.tz_localize(None)

# ==========================================
# 3. FETCH NIFTY MACRO DATA — MOVED EARLIER
# ==========================================
# CRITICAL ORDERING CHANGE vs. the old script: apply_coiled_alpha_logic
# needs NIFTY_CLOSE to compute True Relative Strength (60-day stock return
# vs. 60-day Nifty return), so the Nifty fetch has to happen BEFORE the
# entry-logic call, not after. In the old script this fetch used to sit
# near the very end, since the old blue-box entry logic never referenced
# Nifty data at all.
print("Fetching Nifty 50 data to calculate Macro Regimes, Volatility & Relative Strength...")
df['DATE'] = pd.to_datetime(df['DATE']).dt.normalize()
fetch_start = df['DATE'].min() - pd.Timedelta(days=300)
fetch_end = df['DATE'].max() + pd.Timedelta(days=5)

nifty = yf.download('^NSEI', start=fetch_start, end=fetch_end, progress=False)

macro = None
if not nifty.empty:
    if isinstance(nifty.columns, pd.MultiIndex):
        close_col = nifty['Close'].iloc[:, 0]
        high_col = nifty['High'].iloc[:, 0]
        low_col = nifty['Low'].iloc[:, 0]
    else:
        close_col = nifty['Close']
        high_col = nifty['High']
        low_col = nifty['Low']

    macro = pd.DataFrame({
        'DATE': close_col.index,
        'NIFTY_CLOSE': close_col.values,
        'NIFTY_HIGH': high_col.values,
        'NIFTY_LOW': low_col.values
    })

    macro['DATE'] = pd.to_datetime(macro['DATE']).dt.tz_localize(None).dt.normalize()
    # The macro gates now come from the ONE shared implementation in
    # coiled_alpha_logic.py, so the backtest and the live pipeline cannot
    # diverge (they had: live hardcoded VIX_Spike = False).
    #
    # Regime_Label and VIX_Spike come back LAGGED one trading session because
    # the Sniper fills at OPEN(t) and may therefore only use close(t-1).
    # Systemic_Panic comes back UNLAGGED because MR fills at CLOSE(t).
    # See compute_macro_regime's docstring for the full argument.
    macro = compute_macro_regime(macro)

else:
    print("Warning: Could not fetch Nifty data. Coiled Alpha RS calc and macro regimes will be unavailable.")

# ==========================================
# 4. CALCULATE CORE SIGNALS
# ==========================================
if macro is not None:
    print("Calculating Coiled Alpha Sniper Logic (True Relative Strength + Volatility Contraction)...")
    df = apply_coiled_alpha_logic(df, nifty_df=macro)
else:
    raise RuntimeError(
        "Cannot proceed without Nifty data -- apply_coiled_alpha_logic requires "
        "NIFTY_CLOSE for the Relative Strength calculation. Check the yfinance fetch above."
    )

print("Calculating Mean Reversion Logic...")
df = apply_mean_reversion_logic(df)

# ==========================================
# 5. FILTER DOWN TO DEPLOYMENT COLUMNS
# ==========================================
print("Filtering down to deployment columns...")
columns_to_keep = [
    'DATE', 'SYMBOL', 'OPEN', 'HIGH', 'LOW', 'CLOSE',
    'Daily_Turnover_Rank', 'Turnover_SMA_50', 'Market_Breadth', 'Target_ATR',
    'BB_Enter_Today', 'BB_Exhaustion_Today',
    'MR_Base_Signal', 'SMA_5',
    'RS_Percentile', 'ATR_Contraction_Ratio'  # needed for candidate sort order in wfo_engine.py
]
lean_df = df[columns_to_keep].copy()

# ==========================================
# 6. MERGE MACRO REGIME LABELS + CIRCUIT BREAKERS
# ==========================================
# macro was already fetched and fully processed in step 3 above, so this
# is now just the merge onto the lean panel -- no second fetch needed.
print("Merging dynamic macro regimes and circuit breakers...")
lean_df = lean_df.merge(macro[['DATE', 'Regime_Label', 'VIX_Spike', 'Systemic_Panic']], on='DATE', how='left')

lean_df['Regime_Label'] = lean_df['Regime_Label'].ffill().fillna('NEUTRAL')
lean_df['VIX_Spike'] = lean_df['VIX_Spike'].ffill().fillna(False).astype(bool)
lean_df['Systemic_Panic'] = lean_df['Systemic_Panic'].ffill().fillna(False).astype(bool)

# --- THE MR QUARANTINE FIX ---
# If the broader market is in a Bull regime, MR can ONLY buy top 10% highly liquid large-caps
lean_df['Is_Large_Cap'] = lean_df['Daily_Turnover_Rank'] >= 0.90
invalid_mr_trade = (lean_df['Regime_Label'] == 'BULL') & (~lean_df['Is_Large_Cap'])
lean_df.loc[invalid_mr_trade, 'MR_Base_Signal'] = False

# ==========================================
# 7. SANITY CHECK & SAVE
# ==========================================
print("\nSaving deployment file...")
lean_df.to_parquet('NSE_15Y_Deployment_Ready_V9.parquet', engine='pyarrow', compression='snappy')
print("Done! File ready for the Walk-Forward Optimizer.")

# --- COLAB NOTE ---
# Colab's local filesystem is EPHEMERAL -- if the runtime disconnects or
# resets (idle timeout, session limit, crash), everything written to
# /content, including NSE_EQ_2015_Fast.parquet and this V9 output file,
# is lost. Given Step 1's ~16-year multi-threaded download is expensive to
# re-run, strongly consider mounting Google Drive and saving both files
# there instead of (or in addition to) local disk:
#
#   from google.colab import drive
#   drive.mount('/content/drive')
#   lean_df.to_parquet('/content/drive/MyDrive/NSE_15Y_Deployment_Ready_V9.parquet',
#                       engine='pyarrow', compression='snappy')
