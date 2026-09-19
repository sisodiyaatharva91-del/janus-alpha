"""
test_lookahead.py
-----------------
Proves finding #26 (Sniper entries fill at OPEN of the same bar the signal was
computed from) and validates the fix, on synthetic data.

Method -- deliberately NOT "read the code and assert what I think it does":

  Test A : perturb ONLY CLOSE(t) for one symbol; show BB_Enter_Today at bar t
           flips. Proves the signal at bar t is a function of bar t's own close.
  Test B : run the REAL run_headless_simulation (extracted from
           wfo_engine_updated.py by source parsing, not hand-copied) and show
           that for EVERY position it opens, entry_price == OPEN of the very
           bar that carried the signal.
  A + B  == information from close(t) produced a fill at open(t). That is the
           look-ahead, proven by construction rather than asserted.
  Test C : after the lag, every fill lands on the bar AFTER the signal bar, and
           stops are sized off the signal bar's ATR rather than the fill bar's.
  Test D : a bare shift() leaves NaN on each symbol's first bar and bool(nan)
           is True in Python -- show the naive fix injects phantom signals and
           the patched one does not.
  Test E : direction and size of the entry-price bias across all signal rows.
"""

import re
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, '.')
from coiled_alpha_logic import apply_coiled_alpha_logic

RNG = np.random.default_rng(7)

SNIPER_DECISION_COLS = ['BB_Enter_Today', 'Target_ATR', 'RS_Percentile', 'ATR_Contraction_Ratio']

PARAMS = {
    'start_cap': 600000, 'slip_tax': 0.15, 'idle_yield': 6.0,
    'bull': {'bb_tgt': 4.0, 'bb_stop': 2.0, 'bb_risk': 2.0, 'mr_time': 5, 'mr_pos_size': 10.0},
    'bear': {'bb_tgt': 3.0, 'bb_stop': 2.0, 'bb_risk': 2.0, 'mr_time': 5, 'mr_pos_size': 10.0},
}


# ----------------------------------------------------------------------
# Extract the REAL run_headless_simulation from wfo_engine_updated.py.
# That module runs the whole WFO at import time (module-level parquet read), so
# it cannot be imported. Pulling the function text out and exec'ing it means we
# test the actual production function, not a copy that might quietly differ.
# A probe line is appended so we can see the positions it builds.
# ----------------------------------------------------------------------
def load_real_engine():
    # Namespace comes from engine_harness, which reads every module-level
    # constant out of wfo_engine_updated.py with ast.literal_eval. This used to
    # be a hand-written dict listing pd/np/MAX_GAP_LOSS_PCT/
    # ASSUMED_WORST_CASE_GAP_PCT, which broke the moment the idle-yield fix made
    # the engine reference TRADING_DAYS_PER_YEAR (NameError, 2026-08-22). It also
    # restated the engine's own constant VALUES, so the harness was free to
    # disagree with the thing it was testing.
    from engine_harness import load_engine, engine_line_count
    fn, ns = load_engine(probe=True)
    return fn, ns, engine_line_count()


def first_opens(probe):
    """date -> first appearance of each symbol in active_bb, with its position dict."""
    out = {}
    for d, snap in probe:
        for sym, pos in snap.items():
            if sym not in out:
                out[sym] = (d, pos)
    return out


# ----------------------------------------------------------------------
# Synthetic panel: 24 symbols x 260 bars, mild upward drift, dispersed
# volatility and turnover so the cross-sectional RS / liquidity percentiles are
# meaningful. No symbol is hand-tuned to fire -- we assert on whatever the
# entry logic naturally selects, which is a stronger test than one rigged name.
# ----------------------------------------------------------------------
def make_panel(n_days=260, n_syms=24, perturb=None):
    dates = pd.bdate_range('2024-01-01', periods=n_days)
    rows = []
    for s in range(n_syms):
        sym = f'SYM{s:02d}'
        px = 100.0 + s * 7
        # Vol contracts in the back third for some names -> some will pass the coil test
        contract_from = int(n_days * 0.66)
        for i, d in enumerate(dates):
            base_vol = 0.012 + (s % 6) * 0.004
            vol = base_vol * (0.45 if (i >= contract_from and s % 3 == 0) else 1.0)
            drift = 0.0004 + (s % 7) * 0.0004
            ret = drift + RNG.normal(0, vol)
            prev = px
            px = max(1.0, px * (1 + ret))
            o = prev * (1 + RNG.normal(0, vol * 0.35))
            c = px
            h = max(o, c) * (1 + abs(RNG.normal(0, vol * 0.35)))
            l = min(o, c) * (1 - abs(RNG.normal(0, vol * 0.35)))
            v = (300_000 + s * 120_000) * (1 + abs(RNG.normal(0, 0.15)))
            rows.append({'DATE': d, 'SYMBOL': sym, 'OPEN': o, 'HIGH': h,
                         'LOW': l, 'CLOSE': c, 'VOLUME': v})
    df = pd.DataFrame(rows)

    if perturb is not None:
        sym, date, mult = perturb
        idx = df.index[(df['SYMBOL'] == sym) & (df['DATE'] == date)]
        i = idx[0]
        prev_c = df[(df['SYMBOL'] == sym) & (df['DATE'] < date)]['CLOSE'].iloc[-1]
        df.at[i, 'CLOSE'] = prev_c * mult
        df.at[i, 'HIGH'] = max(df.at[i, 'HIGH'], prev_c * mult * 1.003)
        df.at[i, 'LOW'] = min(df.at[i, 'LOW'], prev_c * mult * 0.997)
    return df, dates


def signals_for(raw):
    nifty = (raw.groupby('DATE', as_index=False)['CLOSE'].mean()
             .rename(columns={'CLOSE': 'NIFTY_CLOSE'}))
    return apply_coiled_alpha_logic(raw, nifty_df=nifty)


def enrich(sig_df, force_breadth=0.80):
    """Add the non-Sniper columns the engine expects. Market_Breadth is pinned so
    slot count is deterministic and the test isolates entry TIMING only."""
    d = sig_df.copy()
    d['Market_Breadth'] = force_breadth
    d['Regime_Label'] = 'BULL'
    d['Systemic_Panic'] = False
    d['VIX_Spike'] = False
    d['MR_Base_Signal'] = False
    d['SMA_5'] = d.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(5).mean())
    return d


def to_daily(d):
    d = d.copy()
    d['DATE'] = pd.to_datetime(d['DATE']).dt.date
    daily = {}
    for r in d.to_dict('records'):
        daily.setdefault(r['DATE'], []).append(r)
    return daily, sorted(d['DATE'].unique())


def lag_sniper_inputs(df, naive=False):
    """The proposed fix: lag exactly the four columns the Sniper entry block
    reads, per SYMBOL, so bar t carries decision inputs as of close(t-1) while
    OPEN(t) remains the fill price."""
    d = df.sort_values(['SYMBOL', 'DATE']).copy()
    for c in SNIPER_DECISION_COLS:
        d[c] = d.groupby('SYMBOL')[c].shift(1)
    if not naive:
        d['BB_Enter_Today'] = d['BB_Enter_Today'].fillna(False).astype(bool)
    return d


# ======================================================================
print("=" * 74)
print("SETUP")
print("=" * 74)
raw, dates = make_panel()
sig = signals_for(raw)
n_sig = int(sig['BB_Enter_Today'].sum())
print(f"  Panel: {raw['SYMBOL'].nunique()} symbols x {len(dates)} bars = {len(raw):,} rows")
print(f"  Sniper signal rows produced: {n_sig}")
assert n_sig > 20, "synthetic panel produced too few signals to test meaningfully"

run_sim, ns, n_lines = load_real_engine()
print(f"  run_headless_simulation extracted verbatim from wfo_engine_updated.py "
      f"({n_lines} lines)\n")


# ======================================================================
print("=" * 74)
print("TEST A -- does the signal at bar t depend on bar t's OWN close?")
print("=" * 74)
# Pick a real signal row to perturb.
cand = sig[sig['BB_Enter_Today']].iloc[len(sig[sig['BB_Enter_Today']]) // 2]
psym, pdate = cand['SYMBOL'], cand['DATE']
print(f"  Perturbing CLOSE for {psym} on {pdate.date()} only (nothing else changes).")
print(f"  BB_Enter_Today there, original close : True")
raw_p, _ = make_panel(perturb=(psym, pdate, 0.90))
sig_p = signals_for(raw_p)
flipped = bool(sig_p[(sig_p['SYMBOL'] == psym) & (sig_p['DATE'] == pdate)]['BB_Enter_Today'].iloc[0])
print(f"  BB_Enter_Today there, close x0.90   : {flipped}")
assert flipped is False, "perturbing close(t) did not change the signal at t"
print("  => CONFIRMED: the signal on bar t is a function of bar t's own CLOSE.\n")


# ======================================================================
print("=" * 74)
print("TEST B -- what price does the engine actually fill at? (PRE-FIX)")
print("=" * 74)
pre = enrich(sig)
daily_pre, cal_pre = to_daily(pre)
ns['_PROBE'].clear()
run_sim(PARAMS, daily_pre, cal_pre)
opens_pre = first_opens(ns['_PROBE'])
print(f"  Positions opened: {len(opens_pre)} -> {sorted(opens_pre)[:8]}"
      f"{' ...' if len(opens_pre) > 8 else ''}")

sig_idx = sig.set_index(['SYMBOL', 'DATE'])
raw_idx = raw.set_index(['SYMBOL', 'DATE'])
checked = 0
for sym, (d, pos) in opens_pre.items():
    key = (sym, pd.Timestamp(d))
    signal_on_fill_bar = bool(sig_idx.loc[key, 'BB_Enter_Today'])
    open_on_fill_bar = float(raw_idx.loc[key, 'OPEN'])
    assert signal_on_fill_bar, f"{sym} filled on {d} but that bar carried no signal"
    assert abs(pos['entry_price'] - open_on_fill_bar) < 1e-9, \
        f"{sym}: entry {pos['entry_price']} != OPEN {open_on_fill_bar} on {d}"
    checked += 1
print(f"  Verified for all {checked} positions:")
print("    - the fill bar is itself a signal bar (BB_Enter_Today True), AND")
print("    - entry_price == that same bar's OPEN")
print("  => CONFIRMED: filled at OPEN of the SAME bar whose CLOSE produced the")
print("     signal. Combined with Test A, that is look-ahead: the fill precedes")
print("     the information that justified it.\n")


# ======================================================================
print("=" * 74)
print("TEST C -- after the fix, is the fill the NEXT bar's open? (POST-FIX)")
print("=" * 74)
sig_fixed = lag_sniper_inputs(sig)
post = enrich(sig_fixed)
daily_post, cal_post = to_daily(post)
ns['_PROBE'].clear()
run_sim(PARAMS, daily_post, cal_post)
opens_post = first_opens(ns['_PROBE'])
print(f"  Positions opened: {len(opens_post)} -> {sorted(opens_post)[:8]}"
      f"{' ...' if len(opens_post) > 8 else ''}")

bars_by_sym = {s: list(g['DATE']) for s, g in raw.sort_values('DATE').groupby('SYMBOL')}
checked = 0
for sym, (d, pos) in opens_post.items():
    fill_ts = pd.Timestamp(d)
    bars = bars_by_sym[sym]
    i = bars.index(fill_ts)
    assert i > 0, f"{sym} filled on its first bar -- impossible post-fix"
    prev_ts = bars[i - 1]
    # the PREVIOUS bar must be the one that carried the original signal
    assert bool(sig_idx.loc[(sym, prev_ts), 'BB_Enter_Today']), \
        f"{sym} filled on {d} but the prior bar {prev_ts.date()} had no signal"
    # fill price must be the fill bar's own OPEN
    open_on_fill = float(raw_idx.loc[(sym, fill_ts), 'OPEN'])
    assert abs(pos['entry_price'] - open_on_fill) < 1e-9, \
        f"{sym}: entry {pos['entry_price']} != OPEN {open_on_fill}"
    # stop must be sized off the SIGNAL bar's ATR, not the fill bar's
    atr_signal_bar = float(sig_idx.loc[(sym, prev_ts), 'Target_ATR'])
    implied_atr = (pos['entry_price'] - pos['stop_price']) / PARAMS['bull']['bb_stop']
    assert abs(implied_atr - atr_signal_bar) < 1e-6, \
        f"{sym}: stop sized off ATR {implied_atr:.4f}, signal-bar ATR was {atr_signal_bar:.4f}"
    checked += 1
print(f"  Verified for all {checked} positions:")
print("    - the bar BEFORE the fill is the signal bar, AND")
print("    - entry_price == the fill bar's OPEN, AND")
print("    - stop/target sized off the SIGNAL bar's ATR, not the fill bar's")
print("  => CONFIRMED: fills moved one bar forward; every decision input now")
print("     predates the fill price.\n")


# ======================================================================
print("=" * 74)
print("TEST D -- the NaN-is-truthy trap in a bare shift()")
print("=" * 74)
naive = lag_sniper_inputs(sig, naive=True)
first_bars = naive.groupby('SYMBOL').head(1)
n_nan = int(first_bars['BB_Enter_Today'].isna().sum())
phantom = sum(1 for v in first_bars['BB_Enter_Today'] if v)  # truthiness, as the engine tests it
patched_first = lag_sniper_inputs(sig, naive=False).groupby('SYMBOL').head(1)
phantom_patched = sum(1 for v in patched_first['BB_Enter_Today'] if v)
print(f"  bool(float('nan')) in Python              : {bool(float('nan'))}")
print(f"  First bar per symbol left NaN by shift()  : {n_nan} of {len(first_bars)}")
print(f"  Rows the engine would read as SIGNALS     : {phantom}")
print(f"  Same rows after .fillna(False)            : {phantom_patched}")
assert n_nan > 0 and phantom == n_nan, "expected bare shift() to inject phantom signals"
assert phantom_patched == 0, "patched version still leaks phantom signals"
print("  => CONFIRMED: the fix MUST fillna(False). A bare shift() would inject one")
print("     phantom entry signal per symbol on its first bar -- on the real panel")
print("     that is one per listed symbol, silently.\n")


# ======================================================================
print("=" * 74)
print("TEST E -- direction and size of the entry-price bias")
print("=" * 74)
nxt = raw[['DATE', 'SYMBOL', 'OPEN']].sort_values(['SYMBOL', 'DATE']).copy()
nxt['OPEN_next'] = nxt.groupby('SYMBOL')['OPEN'].shift(-1)
m = sig[sig['BB_Enter_Today']][['DATE', 'SYMBOL']].merge(nxt, on=['DATE', 'SYMBOL'], how='left').dropna()
m['bias_pct'] = (m['OPEN_next'] / m['OPEN'] - 1) * 100
print(f"  Sniper signal rows with a following bar : {len(m)}")
print(f"  Mean   OPEN(t+1) vs OPEN(t)             : {m['bias_pct'].mean():+.3f}%")
print(f"  Median OPEN(t+1) vs OPEN(t)             : {m['bias_pct'].median():+.3f}%")
print(f"  Share where the real fill is worse      : {(m['bias_pct'] > 0).mean() * 100:.1f}%")
print("  (positive => the contaminated fill was CHEAPER than the obtainable one,")
print("   i.e. the bias flatters the strategy. This is SYNTHETIC data with no real")
print("   momentum structure, so treat the SIGN as the finding here and measure the")
print("   magnitude on the real panel with measure_lookahead_bias.py.)\n")

print("=" * 74)
print("ALL ASSERTIONS PASSED")
print("=" * 74)
