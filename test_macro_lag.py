"""
test_macro_lag.py
-----------------
Behavioural tests for finding #32: the market-wide macro gates were read from
bar t's own close while the Sniper sleeve filled at bar t's OPEN.

The claim under test is not "a shift(1) appeared in the file". It is that:

  1. Regime_Label and VIX_Spike on bar t now carry close(t-1) values, because
     they gate a decision that executes at OPEN(t).
  2. Systemic_Panic on bar t still carries close(t) values, because it gates
     only the MR sleeve, which fills at CLOSE(t).
  3. The panic THRESHOLD is chosen from the same-bar regime, not the lagged
     one -- MR's gate must be internally same-bar throughout.
  4. Market_Breadth is lagged by trading DATE, not per SYMBOL. This one is
     subtle and is the reason a groupby('SYMBOL').shift(1) would have been
     wrong: a stock that did not trade yesterday would receive an OLDER date's
     breadth than its neighbours, so two stocks on the same bar would be
     gated on different days' market conditions.
  5. VIX_Spike survives lagging as a real bool with no NaN. bool(float('nan'))
     is True in Python, so a NaN on row 0 would read as a genuine volatility
     spike and zero out the Sniper's slots on the first bar of the panel.
  6. Missing Nifty High/Low raises loudly instead of quietly defaulting
     VIX_Spike to False -- that exact shortcut is what made live diverge from
     the backtest.

RUN (against a tree with apply_fixes_v2.py --macro-lag applied)
    python test_macro_lag.py
    python test_macro_lag.py --dir /path/to/janus-alpha
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument('--dir', default='.')
args = ap.parse_args()
sys.path.insert(0, os.path.abspath(args.dir))
os.chdir(os.path.abspath(args.dir))

from coiled_alpha_logic import apply_coiled_alpha_logic, compute_macro_regime

RNG = np.random.default_rng(7)
failures = []


def check(cond, label, detail=''):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(f"{label}  {detail}")


def make_nifty(n=520):
    """A Nifty series that deliberately crosses its 200-SMA and has a
    volatility burst, so BULL/BEAR and VIX_Spike both actually toggle. A test
    where the gate never changes value proves nothing about lagging.

    n is generous because the 200-SMA needs 200 bars of warmup before
    Regime_Label means anything: while NIFTY_SMA_200 is NaN, `close > NaN` is
    False and np.where yields 'BEAR' for every one of those rows. Those rows
    are excluded from the fixture's BULL/BEAR count below -- counting them
    would make the fixture look balanced when it is really 199 rows of
    warmup artifact."""
    dates = pd.bdate_range('2024-01-01', periods=n)
    px, rows = 20000.0, []
    for i in range(n):
        # long rise (clears the 200-SMA), sharp high-vol drawdown (BEAR +
        # VIX_Spike), then recovery back through the average
        if i < 330:
            mu, sd = 0.0012, 0.006
        elif i < 420:
            mu, sd = -0.0040, 0.024      # burst: drives ATR_10 above baseline
        else:
            mu, sd = 0.0022, 0.007
        prev = px
        px = max(1.0, px * (1 + mu + RNG.normal(0, sd)))
        h = max(prev, px) * (1 + abs(RNG.normal(0, sd * 0.8)))
        l = min(prev, px) * (1 - abs(RNG.normal(0, sd * 0.8)))
        rows.append({'DATE': dates[i], 'NIFTY_CLOSE': px,
                     'NIFTY_HIGH': h, 'NIFTY_LOW': l})
    return pd.DataFrame(rows)


print("=" * 70)
print("1. compute_macro_regime: what is lagged and what is not")
print("=" * 70)

nifty = make_nifty()
m = compute_macro_regime(nifty)

# The gates must actually vary, or the lag assertions are vacuous.
# Count only post-warmup rows -- see make_nifty's docstring.
warm = m['NIFTY_SMA_200'].notna()
n_bull = int((m.loc[warm, 'Regime_Label_Today'] == 'BULL').sum())
n_bear = int((m.loc[warm, 'Regime_Label_Today'] == 'BEAR').sum())
n_spike = int(m['VIX_Spike_Today'].sum())
check(n_bull > 20 and n_bear > 20,
      "test fixture exercises both BULL and BEAR after 200-SMA warmup",
      f"(bull={n_bull} bear={n_bear})")
check(n_spike > 5, "test fixture produces real VIX_Spike days", f"(spikes={n_spike})")
check(int(m['Systemic_Panic'].sum()) > 5,
      "test fixture produces real panic days", f"(panics={int(m['Systemic_Panic'].sum())})")

# --- 1a. Regime_Label is exactly the previous session's value -------------
shifted = m['Regime_Label_Today'].shift(1)
# compare only where the unlagged label is defined (200-SMA warmup aside, np.where
# yields 'BEAR' for NaN comparisons, so every row is populated)
same = (m['Regime_Label'].iloc[1:].values == shifted.iloc[1:].values)
check(same.all(), "Regime_Label[t] == Regime_Label_Today[t-1]",
      f"({(~same).sum()} rows disagree)")
check(pd.isna(m['Regime_Label'].iloc[0]),
      "Regime_Label[0] is NaN (no prior session to inherit from)")

# --- 1b. VIX_Spike likewise, but bool-safe -------------------------------
vs = m['VIX_Spike'].values
vst = m['VIX_Spike_Today'].values
check((vs[1:] == vst[:-1]).all(), "VIX_Spike[t] == VIX_Spike_Today[t-1]")
check(vs[0] == False, "VIX_Spike[0] is False, not NaN")
check(m['VIX_Spike'].dtype == bool, "VIX_Spike dtype is bool", f"(got {m['VIX_Spike'].dtype})")
check(not m['VIX_Spike'].isna().any(), "VIX_Spike has no NaN")

# The NaN trap, made concrete: this is what a bare shift(1) would have done.
naive = m['VIX_Spike_Today'].shift(1)
check(bool(naive.iloc[0]) is True and vs[0] == False,
      "a bare shift(1) WOULD have read as a spike on row 0; fill_value=False prevents it",
      f"(bool(NaN)={bool(naive.iloc[0])})")

# --- 1c. Systemic_Panic is NOT lagged ------------------------------------
prev_close = m['NIFTY_CLOSE'].shift(1)
ret_same_bar = (m['NIFTY_CLOSE'] - prev_close) / prev_close
thr_same_bar = np.where(m['Regime_Label_Today'] == 'BULL', -0.0050, -0.0150)
expect_panic = (ret_same_bar < thr_same_bar)
check((m['Systemic_Panic'].values == expect_panic.values).all(),
      "Systemic_Panic[t] uses close(t) and the SAME-BAR regime threshold")

# Prove the threshold source is observable: recomputing with the LAGGED label
# must give a different answer on at least one row, otherwise assertion 1c
# cannot distinguish the two implementations.
thr_lagged = np.where(m['Regime_Label'] == 'BULL', -0.0050, -0.0150)
n_thr_diff = int((thr_same_bar != thr_lagged).sum())
would_differ = int(((ret_same_bar < thr_same_bar) != (ret_same_bar < thr_lagged)).sum())
check(n_thr_diff > 0,
      "same-bar vs lagged threshold genuinely differ somewhere (test is not vacuous)",
      f"({n_thr_diff} rows)")
print(f"        note: threshold choice flips Systemic_Panic on {would_differ} row(s)")

# --- 1d. the A/B escape hatch still reproduces the old behaviour ----------
old = compute_macro_regime(nifty, lag_macro_gates=False)
check((old['Regime_Label'].values == old['Regime_Label_Today'].values).all()
      and (old['VIX_Spike'].values == old['VIX_Spike_Today'].values).all(),
      "lag_macro_gates=False reproduces the pre-fix contaminated gates (for A/B)")

# --- 1e. it fails loudly rather than defaulting --------------------------
try:
    compute_macro_regime(nifty.drop(columns=['NIFTY_HIGH']))
    check(False, "missing NIFTY_HIGH raises ValueError", "(it returned instead)")
except ValueError as e:
    check('Do NOT work around this' in str(e),
          "missing NIFTY_HIGH raises ValueError naming the forbidden workaround")
except Exception as e:
    check(False, "missing NIFTY_HIGH raises ValueError", f"(raised {type(e).__name__})")

try:
    compute_macro_regime(None)
    check(False, "nifty_df=None raises ValueError", "(it returned instead)")
except ValueError:
    check(True, "nifty_df=None raises ValueError instead of assuming a regime")

# Order-of-columns / sorting robustness: shuffled input must give the same answer.
shuf = compute_macro_regime(nifty.sample(frac=1.0, random_state=3))
check((shuf['Regime_Label'].fillna('~').values == m['Regime_Label'].fillna('~').values).all()
      and (shuf['VIX_Spike'].values == m['VIX_Spike'].values).all(),
      "unsorted input is sorted internally -> identical gates")


print()
print("=" * 70)
print("2. Market_Breadth is lagged by DATE, not by SYMBOL")
print("=" * 70)

# Build a small panel, then delete one symbol's row on a single date so that
# symbol "did not trade" that day. This is the case that separates a per-DATE
# lag from a per-SYMBOL lag.
n_days, n_syms = 260, 12
dates = pd.bdate_range('2024-01-01', periods=n_days)
rows = []
for s in range(n_syms):
    sym, px = f'SYM{s:02d}', 100.0 + s * 5
    for i, d in enumerate(dates):
        vol = 0.010 + (s % 5) * 0.003
        prev = px
        px = max(1.0, px * (1 + 0.0005 + RNG.normal(0, vol)))
        o = prev * (1 + RNG.normal(0, vol * 0.3))
        rows.append({'DATE': d, 'SYMBOL': sym, 'OPEN': o,
                     'HIGH': max(o, px) * 1.004, 'LOW': min(o, px) * 0.996,
                     'CLOSE': px, 'VOLUME': 400_000 + s * 90_000})
full_panel = pd.DataFrame(rows)

nifty_for_panel = (full_panel.groupby('DATE', as_index=False)['CLOSE'].mean()
                   .rename(columns={'CLOSE': 'NIFTY_CLOSE'}))

# Choose the gap date FROM THE DATA rather than guessing. For the per-SYMBOL
# comparison below to be meaningful, breadth must actually differ between the
# gap date d and the date before it -- otherwise the wrong implementation
# returns a numerically identical value by coincidence and the test looks
# like it passed a check it never really made. (This happened on the first
# run: breadth was 0.5 on both dates.)
probe = apply_coiled_alpha_logic(full_panel.copy(), nifty_df=nifty_for_panel)
b_today = probe.groupby('DATE')['Market_Breadth_Today'].first().sort_index()
GAP_SYM = 'SYM03'
GAP_DATE = None
for i in range(210, len(dates) - 2):
    if abs(b_today.iloc[i] - b_today.iloc[i - 1]) > 1e-9:
        GAP_DATE = dates[i]
        gap_i = i
        break
check(GAP_DATE is not None,
      "found a gap date where breadth differs from the prior date",
      "(fixture is degenerate -- breadth never moves)")
if GAP_DATE is None:
    print("cannot continue section 2")
    sys.exit(1)
print(f"        gap: {GAP_SYM} removed on {GAP_DATE.date()}  "
      f"breadth[d-1]={b_today.iloc[gap_i-1]:.4f}  breadth[d]={b_today.iloc[gap_i]:.4f}")

panel = full_panel[~((full_panel['SYMBOL'] == GAP_SYM)
                     & (full_panel['DATE'] == GAP_DATE))].copy()
sig = apply_coiled_alpha_logic(panel, nifty_df=nifty_for_panel)

check('Market_Breadth_Today' in sig.columns,
      "Market_Breadth_Today (unlagged diagnostic) exists")

# 2a. one breadth value per date -- it is a market-wide scalar
per_date_nunique = sig.groupby('DATE')['Market_Breadth'].nunique()
check(per_date_nunique.max() <= 1,
      "every symbol on a given DATE sees the SAME breadth",
      f"(max distinct per date = {per_date_nunique.max()})")

# 2b. that value is the previous DATE's unlagged breadth
today_by_date = sig.groupby('DATE')['Market_Breadth_Today'].first().sort_index()
lagged_by_date = sig.groupby('DATE')['Market_Breadth'].first().sort_index()
expect = today_by_date.shift(1)
cmp_idx = expect.dropna().index
check(np.allclose(lagged_by_date.loc[cmp_idx].values, expect.loc[cmp_idx].values),
      "Market_Breadth[date] == Market_Breadth_Today[previous trading date]")
check(lagged_by_date.iloc[0] == 0.0,
      "first date's breadth is 0.0, not NaN (fillna(0.0) -> gate closed, fail-safe)",
      f"(got {lagged_by_date.iloc[0]})")
check(not sig['Market_Breadth'].isna().any(), "Market_Breadth has no NaN")

# 2c. THE POINT: the gap symbol, on the day after its missing day, sees the
# same breadth as everyone else -- what a per-SYMBOL shift would get wrong.
next_date = dates[gap_i + 1]
day_rows = sig[sig['DATE'] == next_date]
gap_row = day_rows[day_rows['SYMBOL'] == GAP_SYM]
others = day_rows[day_rows['SYMBOL'] != GAP_SYM]
check(len(gap_row) == 1 and len(others) > 0, "gap symbol is present on the following date")
if len(gap_row) == 1 and len(others) > 0:
    gap_val = float(gap_row['Market_Breadth'].iloc[0])
    other_val = float(others['Market_Breadth'].iloc[0])
    check(abs(gap_val - other_val) < 1e-12,
          f"{GAP_SYM} (did not trade {GAP_DATE.date()}) sees the same breadth as its peers",
          f"(gap={gap_val:.6f} peers={other_val:.6f})")

    # And show what the wrong implementation would have produced, so the
    # assertion above is demonstrably non-trivial.
    per_sym = sig.sort_values(['SYMBOL', 'DATE']).copy()
    per_sym['WRONG'] = per_sym.groupby('SYMBOL')['Market_Breadth_Today'].shift(1)
    w = per_sym[(per_sym['DATE'] == next_date)]
    wg = float(w[w['SYMBOL'] == GAP_SYM]['WRONG'].iloc[0])
    wo = float(w[w['SYMBOL'] != GAP_SYM]['WRONG'].iloc[0])
    check(abs(wg - wo) > 1e-12,
          "a per-SYMBOL shift WOULD have given it a stale, different breadth",
          f"(would be gap={wg:.6f} vs peers={wo:.6f})")

# 2d. the unlagged diagnostic is untouched, so A/B measurement stays possible
check(sig['Market_Breadth_Today'].nunique() > 1,
      "Market_Breadth_Today still varies (usable for impact measurement)")


print()
print("=" * 70)
if failures:
    print(f"FAILED ({len(failures)})")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("PASSED: macro gates are lagged where the Sniper reads them, same-bar")
print("where only MR reads them, and breadth is lagged per DATE.")
