"""
test_fix_verification.py
------------------------
Verifies the section-5b patch in coiled_alpha_logic.py, using the PATCHED
module itself (no test-side helper doing the lagging). Companion to
test_lookahead.py, which proved the bug existed.

  Test 1 : blast radius -- exactly four columns differ between
           lag_sniper_decision_inputs=False and =True. Nothing else moves.
  Test 2 : the lag is a true one-bar-per-SYMBOL lag of the raw signal.
  Test 3 : no phantom signals on any symbol's first bar (the bool(nan) trap).
  Test 4 : run the REAL run_headless_simulation both ways and show fills move
           from the signal bar to the bar after it, with stops sized off the
           signal bar's ATR.
  Test 5 : the MR sleeve and the Sniper exit are untouched.
"""

import re
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, '.')
from coiled_alpha_logic import apply_coiled_alpha_logic

RNG = np.random.default_rng(7)
LAGGED = ['BB_Enter_Today', 'Target_ATR', 'RS_Percentile', 'ATR_Contraction_Ratio']

PARAMS = {
    'start_cap': 600000, 'slip_tax': 0.15, 'idle_yield': 6.0,
    'bull': {'bb_tgt': 4.0, 'bb_stop': 2.0, 'bb_risk': 2.0, 'mr_time': 5, 'mr_pos_size': 10.0},
    'bear': {'bb_tgt': 3.0, 'bb_stop': 2.0, 'bb_risk': 2.0, 'mr_time': 5, 'mr_pos_size': 10.0},
}


def load_real_engine():
    # See engine_harness.py: constants are read from the engine rather than
    # hand-listed here, so a new module-level constant cannot break this.
    from engine_harness import load_engine
    return load_engine(probe=True)


def first_opens(probe):
    out = {}
    for d, snap in probe:
        for sym, pos in snap.items():
            if sym not in out:
                out[sym] = (d, pos)
    return out


def make_panel(n_days=260, n_syms=24):
    dates = pd.bdate_range('2024-01-01', periods=n_days)
    rows = []
    for s in range(n_syms):
        sym, px = f'SYM{s:02d}', 100.0 + s * 7
        contract_from = int(n_days * 0.66)
        for i, d in enumerate(dates):
            base_vol = 0.012 + (s % 6) * 0.004
            vol = base_vol * (0.45 if (i >= contract_from and s % 3 == 0) else 1.0)
            ret = (0.0004 + (s % 7) * 0.0004) + RNG.normal(0, vol)
            prev = px
            px = max(1.0, px * (1 + ret))
            o = prev * (1 + RNG.normal(0, vol * 0.35))
            h = max(o, px) * (1 + abs(RNG.normal(0, vol * 0.35)))
            l = min(o, px) * (1 - abs(RNG.normal(0, vol * 0.35)))
            rows.append({'DATE': d, 'SYMBOL': sym, 'OPEN': o, 'HIGH': h, 'LOW': l,
                         'CLOSE': px,
                         'VOLUME': (300_000 + s * 120_000) * (1 + abs(RNG.normal(0, 0.15)))})
    return pd.DataFrame(rows), dates


def enrich(d):
    d = d.copy()
    d['Market_Breadth'] = 0.80
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


raw, dates = make_panel()
nifty = (raw.groupby('DATE', as_index=False)['CLOSE'].mean()
         .rename(columns={'CLOSE': 'NIFTY_CLOSE'}))

KEY = ['SYMBOL', 'DATE']
old = apply_coiled_alpha_logic(raw, nifty_df=nifty, lag_sniper_decision_inputs=False)
new = apply_coiled_alpha_logic(raw, nifty_df=nifty)          # default True
old = old.sort_values(KEY).reset_index(drop=True)
new = new.sort_values(KEY).reset_index(drop=True)

print("=" * 74)
print("SETUP")
print("=" * 74)
print(f"  Panel {raw['SYMBOL'].nunique()} symbols x {len(dates)} bars")
print(f"  Raw signal rows (unlagged) : {int(new['BB_Enter_Signal_Raw'].sum())}")
print(f"  Lagged signal rows         : {int(new['BB_Enter_Today'].sum())}\n")


# ======================================================================
print("=" * 74)
print("TEST 1 -- blast radius: which columns does the patch actually move?")
print("=" * 74)
assert list(old.columns) == [c for c in new.columns], "column sets differ"
differing = []
for c in new.columns:
    a, b = old[c], new[c]
    same = a.equals(b) or (a.isna() == b.isna()).all() and (a.fillna(0) == b.fillna(0)).all() \
        if a.dtype.kind in 'fc' else a.equals(b)
    if not same:
        differing.append(c)
print(f"  Columns that differ: {sorted(differing)}")
assert sorted(differing) == sorted(LAGGED), \
    f"expected exactly {sorted(LAGGED)}, got {sorted(differing)}"
print(f"  => CONFIRMED: exactly the 4 Sniper entry inputs move. All {len(new.columns) - 4}")
print("     other columns -- including MR_Base_Signal, BB_Exhaustion_Today,")
print("     Market_Breadth, Turnover_SMA_50, the Sniper_Pass_* diagnostics --")
print("     are bit-identical.\n")


# ======================================================================
print("=" * 74)
print("TEST 2 -- is it a true one-bar-per-SYMBOL lag?")
print("=" * 74)
expect = old.groupby('SYMBOL')['BB_Enter_Today'].shift(1, fill_value=False).astype(bool)
assert new['BB_Enter_Today'].equals(expect), "lagged signal != raw signal shifted by 1"
assert new['BB_Enter_Signal_Raw'].astype(bool).equals(old['BB_Enter_Today'].astype(bool)), \
    "BB_Enter_Signal_Raw is not the unlagged signal"
for c in ['Target_ATR', 'RS_Percentile', 'ATR_Contraction_Ratio']:
    exp = old.groupby('SYMBOL')[c].shift(1)
    assert np.allclose(new[c].fillna(-999), exp.fillna(-999)), f"{c} not lagged by exactly 1 bar"
    print(f"  {c:<24}: lagged 1 bar per SYMBOL  OK")
print(f"  {'BB_Enter_Today':<24}: lagged 1 bar per SYMBOL  OK")
print("  BB_Enter_Signal_Raw preserves the unlagged signal for diagnostics  OK")
print("  => CONFIRMED: bar t now carries decision inputs as of close(t-1).\n")


# ======================================================================
print("=" * 74)
print("TEST 3 -- no phantom signal on any symbol's first bar")
print("=" * 74)
firsts = new.sort_values(KEY).groupby('SYMBOL').head(1)
print(f"  bool(float('nan')) is {bool(float('nan'))} -- a bare shift() would make each")
print(f"  symbol's first bar read as a VALID signal.")
print(f"  dtype of BB_Enter_Today   : {new['BB_Enter_Today'].dtype}")
print(f"  NaNs in BB_Enter_Today    : {int(new['BB_Enter_Today'].isna().sum())}")
print(f"  First bars reading truthy : {sum(1 for v in firsts['BB_Enter_Today'] if v)} of {len(firsts)}")
assert new['BB_Enter_Today'].dtype == bool
assert new['BB_Enter_Today'].isna().sum() == 0
assert sum(1 for v in firsts['BB_Enter_Today'] if v) == 0
print("  => CONFIRMED: fill_value=False means the NaN never exists.\n")


# ======================================================================
print("=" * 74)
print("TEST 4 -- what the REAL engine now fills at")
print("=" * 74)
run_sim, ns = load_real_engine()
sig_raw_idx = old.set_index(KEY)
raw_idx = raw.set_index(KEY)
bars_by_sym = {s: list(g['DATE']) for s, g in raw.sort_values('DATE').groupby('SYMBOL')}

results = {}
for label, frame in (('PRE-FIX  (lag=False)', old), ('POST-FIX (lag=True)', new)):
    daily, cal = to_daily(enrich(frame))
    ns['_PROBE'].clear()
    run_sim(PARAMS, daily, cal)
    results[label] = first_opens(ns['_PROBE'])

for label, opens in results.items():
    print(f"  {label}: {len(opens)} positions -> {sorted(opens)}")

# pre-fix: fill bar IS the signal bar
for sym, (d, pos) in results['PRE-FIX  (lag=False)'].items():
    k = (sym, pd.Timestamp(d))
    assert bool(sig_raw_idx.loc[k, 'BB_Enter_Today']), f"{sym} pre-fix fill bar had no signal"
    assert abs(pos['entry_price'] - float(raw_idx.loc[k, 'OPEN'])) < 1e-9

# post-fix: fill bar is the bar AFTER the signal bar
checked = 0
for sym, (d, pos) in results['POST-FIX (lag=True)'].items():
    fill = pd.Timestamp(d)
    bars = bars_by_sym[sym]
    i = bars.index(fill)
    assert i > 0, f"{sym} filled on its first bar"
    prev = bars[i - 1]
    assert bool(sig_raw_idx.loc[(sym, prev), 'BB_Enter_Today']), \
        f"{sym} filled {fill.date()} but prior bar {prev.date()} carried no signal"
    assert abs(pos['entry_price'] - float(raw_idx.loc[(sym, fill), 'OPEN'])) < 1e-9, \
        f"{sym} entry price is not the fill bar's OPEN"
    implied_atr = (pos['entry_price'] - pos['stop_price']) / PARAMS['bull']['bb_stop']
    atr_sig = float(sig_raw_idx.loc[(sym, prev), 'Target_ATR'])
    atr_fill = float(sig_raw_idx.loc[(sym, fill), 'Target_ATR'])
    assert abs(implied_atr - atr_sig) < 1e-6, "stop not sized off the signal bar's ATR"
    if abs(atr_sig - atr_fill) > 1e-9:
        checked += 1
print(f"  Pre-fix : every fill lands ON a signal bar, at that bar's OPEN")
print(f"  Post-fix: every fill lands on the bar AFTER the signal bar, at that")
print(f"            bar's OPEN, with the stop sized off the SIGNAL bar's ATR")
print(f"            ({checked} of {len(results['POST-FIX (lag=True)'])} positions had a materially")
print(f"            different ATR on the two bars, so this is a real distinction)")
print("  => CONFIRMED: no engine edits were needed; the shared module fixed both.\n")


# ======================================================================
print("=" * 74)
print("TEST 5 -- MR sleeve and Sniper exit deliberately untouched")
print("=" * 74)
for c in ['MR_Base_Signal', 'BB_Exhaustion_Today'] if 'MR_Base_Signal' in new.columns \
         else ['BB_Exhaustion_Today']:
    assert old[c].equals(new[c]), f"{c} changed -- it should not have"
    print(f"  {c:<22}: identical pre/post  OK")
print("  => MR fires on close(t) and fills at CLOSE(t) -- a market-on-close")
print("     convention that is internally consistent and implementable, so it is")
print("     correctly left alone. Lagging it would put the sleeve a full day late")
print("     on a 1-3 day bounce.\n")

print("=" * 74)
print("ALL ASSERTIONS PASSED -- patch verified")
print("=" * 74)
