"""
measure_lookahead_bias.py
=========================
Quantifies finding #26 (Sniper look-ahead) on the REAL panel, cheaply, BEFORE
committing to a full WFO re-run.

WHY THIS RUNS FIRST
    A full WFO re-run is 14 windows x 1,000 candidates x 2 sims ~= 28,000
    simulations. Stage 1 below takes seconds and Stage 2 takes minutes, and
    together they tell you the sign and the rough magnitude of the correction.
    If Stage 2 says the Sniper sleeve loses e.g. 6 CAGR points, you know what
    you are walking into before you spend the compute.

YOU DO NOT NEED TO RE-RUN data_prep FOR THIS
    Verified by inspection: data_prep_updated.py never writes to
    BB_Enter_Today / Target_ATR / RS_Percentile / ATR_Contraction_Ratio after
    it calls apply_coiled_alpha_logic -- it only lists them in
    columns_to_keep. So lagging those four columns post-hoc on the existing
    V9 parquet is exactly equivalent to regenerating it with the patched
    module. Saves the raw download + yfinance fetch.
    (Re-run data_prep with the patched coiled_alpha_logic.py eventually, so
    the stored parquet is correct on disk. Just not needed to measure.)

USAGE (Colab)
    !python measure_lookahead_bias.py --data /content/drive/MyDrive/NSE_15Y_Deployment_Ready_V9.parquet
    add --stage2 to also run the two full-period Sniper simulations
    add --engine /path/to/wfo_engine_updated.py if it is not alongside this file
"""

import argparse
import re
import sys
import numpy as np
import pandas as pd

LAGGED = ['BB_Enter_Today', 'Target_ATR', 'RS_Percentile', 'ATR_Contraction_Ratio']

ap = argparse.ArgumentParser()
ap.add_argument('--data', default='NSE_15Y_Deployment_Ready_V9.parquet')
ap.add_argument('--engine', default='wfo_engine_updated.py')
ap.add_argument('--stage2', action='store_true',
                help='also run two full-period Sniper sims (minutes, not seconds)')
args = ap.parse_args()

print("Loading panel...")
df = pd.read_parquet(args.data)
df['DATE'] = pd.to_datetime(df['DATE'])
df = df.sort_values(['SYMBOL', 'DATE']).reset_index(drop=True)
print(f"  {len(df):,} rows, {df['SYMBOL'].nunique():,} symbols, "
      f"{df['DATE'].min().date()} -> {df['DATE'].max().date()}")

missing = [c for c in LAGGED if c not in df.columns]
if missing:
    sys.exit(f"ERROR: parquet is missing {missing}. Is this the V9 deployment file?")

# Guard: if the parquet was already regenerated with the patched module, the
# lag is already baked in and applying it again would double-lag.
raw_flag = 'BB_Enter_Signal_Raw' in df.columns
if raw_flag:
    print("\n  NOTE: BB_Enter_Signal_Raw is present, so this parquet was built with the")
    print("  PATCHED module and BB_Enter_Today is already lagged. Using the raw column")
    print("  as the 'contaminated' baseline.")
    df['_signal_raw'] = df['BB_Enter_Signal_Raw'].fillna(False).astype(bool)
else:
    df['_signal_raw'] = df['BB_Enter_Today'].fillna(False).astype(bool)

# =====================================================================
# STAGE 1 -- entry-price bias on every historical Sniper signal (seconds)
# =====================================================================
print("\n" + "=" * 74)
print("STAGE 1 -- entry-price bias on real signal rows")
print("=" * 74)

df['OPEN_next'] = df.groupby('SYMBOL')['OPEN'].shift(-1)
sig = df[df['_signal_raw'] & df['OPEN_next'].notna()].copy()

# The contaminated backtest filled at OPEN(t) using CLOSE(t) information.
# The obtainable fill, acting on the same signal, is OPEN(t+1).
sig['head_start_pct'] = (sig['OPEN_next'] / sig['OPEN'] - 1) * 100

n = len(sig)
print(f"  Sniper signal rows (with a following bar) : {n:,}")
print(f"  Mean   OPEN(t+1) vs OPEN(t)               : {sig['head_start_pct'].mean():+.3f}%")
print(f"  Median OPEN(t+1) vs OPEN(t)               : {sig['head_start_pct'].median():+.3f}%")
print(f"  Std dev                                   :  {sig['head_start_pct'].std():.3f}%")
print(f"  Share where the honest fill is WORSE      : {(sig['head_start_pct'] > 0).mean()*100:.1f}%")
print(f"  90th pct / 10th pct                       : {sig['head_start_pct'].quantile(0.9):+.2f}% / "
      f"{sig['head_start_pct'].quantile(0.1):+.2f}%")
print("\n  Positive mean => the contaminated entry was systematically CHEAPER than")
print("  the price you could actually have paid, i.e. the bias FLATTERS the")
print("  backtest. Because these signals select for strong relative strength and")
print("  volatility compression -- names primed to gap -- a positive mean is the")
print("  expected direction, not a coincidence.")

print("\n  By calendar year:")
sig['YEAR'] = sig['DATE'].dt.year
by_year = sig.groupby('YEAR')['head_start_pct'].agg(['count', 'mean', 'median'])
print(by_year.to_string(float_format=lambda v: f"{v:+.3f}"))

# Also: how often does the stop/target distance change materially, since
# Target_ATR was ALSO read from the signal bar.
df['ATR_next'] = df.groupby('SYMBOL')['Target_ATR'].shift(-1)
a = df[df['_signal_raw'] & df['ATR_next'].notna() & (df['Target_ATR'] > 0)]
atr_delta = ((a['ATR_next'] / a['Target_ATR'] - 1) * 100)
print(f"\n  Secondary effect -- Target_ATR sized the stop AND the position:")
print(f"    Mean |change| in ATR from signal bar to fill bar : {atr_delta.abs().mean():.2f}%")
print(f"    So stop distance and share count were also set from a bar the")
print(f"    strategy could not yet have seen.")

# =====================================================================
# STAGE 1b -- macro-gate look-ahead (finding #32), in units of CAPACITY
# =====================================================================
# Finding #26 above is about the entry PRICE. Finding #32 is a different animal:
# Market_Breadth, Regime_Label and VIX_Spike are market-wide scalars read on bar
# t to authorise Sniper fills at OPEN(t). They gate two things in the engine:
#
#     max_bb_pos = 0 if VIX_Spike else (6 if breadth > 0.65 else
#                                       3 if breadth >= 0.50 else 1)
#     bb_frac    = 0.80 / 0.60 / 0.35 by the same breadth tiers when BULL,
#                  0.20 flat when BEAR
#
# Only TIER changes matter. A breadth move of 0.71 -> 0.69 changes nothing; a
# move of 0.66 -> 0.64 halves the slot count from 6 to 3. So counting how much
# the raw numbers move is the wrong measurement -- what follows counts how often
# the SLOT COUNT and the CAPITAL SPLIT actually differ, which is the thing that
# changes trades.
#
# WHY THIS IS WORTH A SEPARATE STAGE: it is nearly free (per-DATE arithmetic on
# a few thousand rows) and it tells you whether finding #32 is a rounding error
# or a second effect comparable to finding #26, BEFORE you spend ~28,000
# simulations. If capacity barely moves, the macro lag is a correctness fix with
# little numerical consequence and the re-run's delta is almost all finding #26.
#
# LAGGED BY DATE, NOT BY SYMBOL. These are one value per trading day. A
# groupby('SYMBOL').shift(1) would hand a stock that did not trade yesterday an
# OLDER day's breadth than its neighbours got, silently, on exactly the illiquid
# names where it matters most.
print("\n" + "=" * 74)
print("STAGE 1b -- macro-gate look-ahead, measured as capacity change")
print("=" * 74)

MACRO_COLS = ['Market_Breadth', 'Regime_Label', 'VIX_Spike']


def slots(breadth, vix):
    """Sniper slot cap. Mirrors wfo_engine_updated.py lines 233 and 246.
    NaN breadth falls through both comparisons to 1, which is what the engine
    does too -- deliberately kept identical rather than 'improved' here."""
    if vix:
        return 0
    return 6 if breadth > 0.65 else 3 if breadth >= 0.50 else 1


def bb_frac(breadth, regime):
    """Sniper capital share. Mirrors wfo_engine_updated.py lines 150-156."""
    if regime != 'BULL':
        return 0.20
    return 0.80 if breadth > 0.65 else 0.60 if breadth >= 0.50 else 0.35


def stage_1b(df):
    # Where the UNLAGGED value lives, whichever build we were handed. A parquet
    # from the patched module carries the lagged value in `col` and the raw one
    # in `col_Today`; a pre-patch parquet has the raw value in `col` itself.
    # Same idea as the BB_Enter_Signal_Raw check above, so this script gives the
    # same answer before and after data_prep is re-run with the patched module.
    src_col = {c: (f'{c}_Today' if f'{c}_Today' in df.columns else c)
               for c in MACRO_COLS}
    absent = [c for c, s in src_col.items() if s not in df.columns]
    if absent:
        print(f"  SKIPPED: parquet has no {absent}. Nothing to measure here.")
        return
    if any(s.endswith('_Today') for s in src_col.values()):
        already = [src_col[c] for c in MACRO_COLS if src_col[c].endswith('_Today')]
        print("  NOTE: *_Today columns present, so this parquet is already")
        print(f"  macro-lagged. Using {already} as the 'contaminated' baseline.")

    # One row per DATE. These are market-wide scalars, so take the FIRST row of
    # each date rather than a mean -- a mean would silently paper over any date
    # where the panel disagrees with itself, which is a data bug worth seeing.
    md = (df.sort_values('DATE')
             .groupby('DATE', as_index=False)
             .agg(**{c: (src_col[c], 'first') for c in MACRO_COLS}))

    nunique = df.groupby('DATE')[[src_col[c] for c in MACRO_COLS]].nunique().max()
    print("  Sanity: max distinct values per DATE -- "
          + ", ".join(f"{c}={int(nunique[src_col[c]])}" for c in MACRO_COLS))
    if any(int(nunique[src_col[c]]) > 1 for c in MACRO_COLS):
        print("  WARNING: a macro column varies WITHIN a date. These are supposed")
        print("  to be market-wide scalars, so that is a data bug worth chasing")
        print("  before trusting anything below.")

    md['VIX_Spike'] = md['VIX_Spike'].fillna(False).astype(bool)
    # str, not categorical: shift(1) on a categorical yields NaN, and filling it
    # with a value outside the category set raises. Comparisons are unaffected.
    md['Regime_Label'] = md['Regime_Label'].astype(str)

    # The honest values: yesterday's, by trading DATE. fill_value=False on the
    # bool so row 0 cannot become a truthy NaN -- bool(float('nan')) is True,
    # the trap behind three separate fixes in this codebase.
    md['breadth_lag'] = md['Market_Breadth'].shift(1)
    md['regime_lag'] = md['Regime_Label'].shift(1)
    md['vix_lag'] = md['VIX_Spike'].shift(1, fill_value=False).astype(bool)
    # Row 0 has no yesterday. Fail SAFE, matching section 7b of the patched
    # module: breadth 0.0 (lowest tier, 1 slot) and regime BEAR (least capital).
    md['breadth_lag'] = md['breadth_lag'].fillna(0.0)
    md['regime_lag'] = md['regime_lag'].fillna('BEAR')

    md['slots_conta'] = [slots(b, v) for b, v in
                          zip(md['Market_Breadth'], md['VIX_Spike'])]
    md['slots_honest'] = [slots(b, v) for b, v in
                           zip(md['breadth_lag'], md['vix_lag'])]
    md['frac_conta'] = [bb_frac(b, r) for b, r in
                         zip(md['Market_Breadth'], md['Regime_Label'])]
    md['frac_honest'] = [bb_frac(b, r) for b, r in
                          zip(md['breadth_lag'], md['regime_lag'])]

    n_dates = len(md)
    if n_dates < 3:
        print(f"  SKIPPED: only {n_dates} trading date(s) in the panel.")
        return

    # Base rates FIRST. A gate that never fires cannot contribute to finding #32,
    # and "0 changes" reads like "no problem here" when it can equally mean "this
    # gate is inert on this panel". Those need to be distinguishable.
    n_vix = int(md['VIX_Spike'].sum())
    regimes = md['Regime_Label'].value_counts().to_dict()
    print(f"\n  Base rates: VIX_Spike fires on {n_vix:,} of {n_dates:,} dates"
          f" ({n_vix / n_dates * 100:.1f}%);  regimes {regimes}")
    if n_vix == 0:
        print("  -> VIX_Spike never fires, so the max_bb_pos=0 kill-switch is INERT")
        print("     on this panel and contributes nothing to finding #32.")
    if len(regimes) < 2:
        print("  -> single regime throughout, so the bb_frac regime branch is INERT.")

    # Row 0 has no yesterday, so its lag is the fail-safe seed, not a look-ahead
    # difference. Counting it inflates every number below -- on the synthetic
    # fixture it made a 100%-BULL panel report "Regime_Label changed: 1", which
    # invites exactly the wrong conclusion. Compare from row 1 onward.
    cmp = md.iloc[1:]
    n_cmp = len(cmp)

    def tier(s):
        return np.where(s > 0.65, 'high', np.where(s >= 0.50, 'mid', 'low'))

    breadth_tier_chg = int((tier(cmp['Market_Breadth'])
                            != tier(cmp['breadth_lag'])).sum())
    regime_chg = int((cmp['Regime_Label'] != cmp['regime_lag']).sum())
    vix_chg = int((cmp['VIX_Spike'] != cmp['vix_lag']).sum())
    slot_chg = int((cmp['slots_conta'] != cmp['slots_honest']).sum())
    frac_chg = int((cmp['frac_conta'] != cmp['frac_honest']).sum())
    pct = lambda k: f"{k / n_cmp * 100:.1f}%"
    # Returned as well as printed, so test_macro_gate_measure.py can assert on
    # the numbers instead of scraping stdout. A verdict that can only be checked
    # by parsing prose is a verdict nobody checks.
    out = dict(n_dates=n_dates, n_cmp=n_cmp, n_vix=n_vix, regimes=regimes,
               breadth_tier_chg=breadth_tier_chg, regime_chg=regime_chg,
               vix_chg=vix_chg, slot_chg=slot_chg, frac_chg=frac_chg,
               verdict=None)

    print(f"\n  Comparable dates (excludes row 0)          : {n_cmp:,}")
    print(f"  Breadth TIER changed when lagged           : {breadth_tier_chg:>6,}"
          f"  ({pct(breadth_tier_chg)})")
    print(f"  Regime_Label changed when lagged           : {regime_chg:>6,}"
          f"  ({pct(regime_chg)})")
    print(f"  VIX_Spike changed when lagged              : {vix_chg:>6,}"
          f"  ({pct(vix_chg)})")
    print(f"  --> Sniper SLOT COUNT differed             : {slot_chg:>6,}"
          f"  ({pct(slot_chg)})")
    print(f"  --> Sniper CAPITAL SHARE differed          : {frac_chg:>6,}"
          f"  ({pct(frac_chg)})")

    print("\n  Slot-count crosstab (rows contaminated, cols honest):")
    xt = pd.crosstab(cmp['slots_conta'], cmp['slots_honest'])
    print("    " + xt.to_string().replace("\n", "\n    "))

    ms_c, ms_h = cmp['slots_conta'].mean(), cmp['slots_honest'].mean()
    mf_c, mf_h = cmp['frac_conta'].mean(), cmp['frac_honest'].mean()
    out.update(mean_slots_conta=float(ms_c), mean_slots_honest=float(ms_h),
               mean_frac_conta=float(mf_c), mean_frac_honest=float(mf_h))
    print(f"\n  Mean slots   : {ms_c:.3f} contaminated vs {ms_h:.3f} honest"
          + (f"   ({(ms_h / ms_c - 1) * 100:+.1f}%)" if ms_c else ""))
    print(f"  Mean bb_frac : {mf_c:.3f} contaminated vs {mf_h:.3f} honest"
          + (f"   ({(mf_h / mf_c - 1) * 100:+.1f}%)" if mf_c else ""))
    print("  NOTE: the MEANS barely move by construction -- lagging shifts capacity")
    print("  in time, it does not add or remove any on average. The bias lives in")
    print("  the TIMING (which days got the capacity), which is what follows.")

    # -----------------------------------------------------------------
    # DIRECTION. The counts above say how OFTEN capacity differed. They do not
    # say whether the difference HELPED. This does: on dates where the
    # contaminated version had more slots than the honest one, what did the
    # market actually do that day? Sniper fills at OPEN, so CLOSE/OPEN - 1 is
    # the return the extra slots would have captured. Cross-sectional mean over
    # the whole universe is a crude market proxy, not the strategy's return --
    # the point is the SIGN, not the magnitude.
    # -----------------------------------------------------------------
    day_ret = (df.assign(_r=df['CLOSE'] / df['OPEN'] - 1)
                 .groupby('DATE')['_r'].mean() * 100)
    # reset_index: day_ret carries DATE as its INDEX, and merge(on='DATE') needs
    # it as a column on both sides or it raises KeyError.
    cmp = cmp.merge(day_ret.rename('day_ret_pct').reset_index(), on='DATE', how='left')

    more = cmp[cmp['slots_conta'] > cmp['slots_honest']]
    fewer = cmp[cmp['slots_conta'] < cmp['slots_honest']]
    same = cmp[cmp['slots_conta'] == cmp['slots_honest']]
    print("\n  Same-day mean return (CLOSE/OPEN - 1, cross-sectional), by capacity gap:")
    for label, grp in (('contaminated had MORE slots ', more),
                       ('contaminated had FEWER slots', fewer),
                       ('identical                   ', same)):
        tail = (f", mean {grp['day_ret_pct'].mean():+.3f}%"
                f"  sd {grp['day_ret_pct'].std():.3f}") if len(grp) else ""
        print(f"    {label} : {len(grp):>6,} dates{tail}")

    if len(more) > 1 and len(fewer) > 1:
        m1, m2 = more['day_ret_pct'].mean(), fewer['day_ret_pct'].mean()
        v1, v2 = more['day_ret_pct'].var(ddof=1), fewer['day_ret_pct'].var(ddof=1)
        n1, n2 = len(more), len(fewer)
        spread = m1 - m2
        se = float(np.sqrt(v1 / n1 + v2 / n2))
        t = spread / se if se > 0 else float('nan')
        out.update(spread=float(spread), se=se, t=float(t),
                   n_more=n1, n_fewer=n2, mean_more=float(m1), mean_fewer=float(m2))
        print(f"\n  Spread (MORE minus FEWER) : {spread:+.3f}%   "
              f"se {se:.3f}   t {t:+.2f}")
        # Welch's t, no scipy in this environment. |t| ~ 2 is the usual 95% eyeball
        # threshold. It OVERSTATES confidence here: daily cross-sectional returns
        # are fat-tailed and serially correlated, so treat it as a noise floor, not
        # a p-value. The point is to stop a +0.03% spread from being reported as a
        # finding, which is what the first version of this stage did.
        if abs(t) < 2:
            out['verdict'] = 'noise'
            print("  |t| < 2 => this spread is INDISTINGUISHABLE FROM NOISE. Do not")
            print("  report a direction. Finding #32 is still a correctness bug and")
            print("  still worth fixing, but on this panel there is no evidence it")
            print("  systematically flattered the backtest.")
        elif spread > 0:
            out['verdict'] = 'flattering'
            print("  Positive and outside the noise floor => the contaminated run was")
            print("  granted extra Sniper capacity disproportionately on days that")
            print("  turned out UP, and had it withdrawn on days that turned out down.")
            print("  That is the flattering direction: a SECOND bias on top of the")
            print("  entry-price one, and the re-run should give back more than")
            print("  finding #26 alone accounts for.")
        else:
            out['verdict'] = 'penalising'
            print("  Negative and outside the noise floor => the stale gates were")
            print("  actively HURTING the backtest, so fixing finding #32 should")
            print("  IMPROVE the re-run. Say so plainly if that is what happens.")
    else:
        out['verdict'] = 'insufficient'
        print("\n  Not enough dates on both sides to compute a direction spread.")

    print("\n  WHAT THIS STAGE CANNOT TELL YOU: the CAGR effect. That depends on which")
    print("  trades the extra slots actually took, and on compounding. Stage 2 below")
    print("  measures finding #26 end-to-end; the macro effect only shows up in the")
    print("  full re-run, because the stored parquet's gates are what they are.")
    print("  Read these percentages as the SIZE OF THE EXPOSURE, not as a result.")
    return out


stage_1b(df)


# =====================================================================
# STAGE 2 -- two full-period simulations, fixed params, no optimization
# =====================================================================
if not args.stage2:
    print("\n" + "=" * 74)
    print("Stage 2 skipped. Re-run with --stage2 for the CAGR/drawdown delta.")
    print("=" * 74)
    sys.exit(0)

print("\n" + "=" * 74)
print("STAGE 2 -- one contaminated vs one honest simulation, identical params")
print("=" * 74)
print("  NOT an optimization. Same fixed params both ways, so the ONLY difference")
print("  is decision timing. This isolates the bias; it does not re-tune anything.")

# Constants come from the engine itself via engine_harness (ast.literal_eval on
# its module-level assignments), not from a hand-written dict. The old dict
# listed only MAX_GAP_LOSS_PCT and ASSUMED_WORST_CASE_GAP_PCT, so this script
# died with `NameError: TRADING_DAYS_PER_YEAR` the moment the idle-yield fix
# landed -- i.e. exactly when you would first want to run it.
from engine_harness import load_engine
run_sim, ns = load_engine(engine_file=args.engine)

# Mid-range params. Deliberately not a WFO winner -- a winner was SELECTED under
# the contaminated regime, so reusing it would bias the comparison toward the
# contaminated run.
PARAMS = {
    'start_cap': 600000, 'slip_tax': 0.15, 'idle_yield': 6.0,
    'bull': {'bb_tgt': 4.0, 'bb_stop': 2.0, 'bb_risk': 2.0, 'mr_time': 5, 'mr_pos_size': 10.0},
    'bear': {'bb_tgt': 3.0, 'bb_stop': 2.0, 'bb_risk': 1.5, 'mr_time': 5, 'mr_pos_size': 8.0},
}


def lag_four(frame):
    d = frame.sort_values(['SYMBOL', 'DATE']).reset_index(drop=True)
    g = d.groupby('SYMBOL')
    d['BB_Enter_Today'] = g['BB_Enter_Today'].shift(1, fill_value=False).astype(bool)
    for c in ['Target_ATR', 'RS_Percentile', 'ATR_Contraction_Ratio']:
        d[c] = g[c].shift(1)
    assert d['BB_Enter_Today'].dtype == bool and not d['BB_Enter_Today'].isna().any()
    return d


def metrics(curve, cal):
    # NOTE: annualizes on ELAPSED CALENDAR TIME deliberately. Do NOT reuse
    # wfo_engine's calculate_fitness() here -- it computes
    # (final/initial)^(365.25/days) where `days` counts TRADING days, which
    # inflates CAGR by the exponent 365.25/252 = 1.4494 (a true 14.17% prints
    # as 21.18%). See test_cagr_units.py. The engine's chained-CAGR block is
    # correct; only calculate_fitness is affected. Using the correct formula
    # here keeps the contaminated-vs-honest delta clean of that separate bug.
    eq = pd.Series(curve, dtype=float)
    if len(eq) < 2 or eq.iloc[0] <= 0:
        return dict(cagr=float('nan'), maxdd=float('nan'), final=float('nan'))
    years = (pd.Timestamp(cal[-1]) - pd.Timestamp(cal[0])).days / 365.25
    cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else float('nan')
    dd = ((eq - eq.cummax()) / eq.cummax()).min() * 100
    return dict(cagr=cagr, maxdd=dd, final=eq.iloc[-1])


def build_daily(frame):
    d = frame.copy()
    d['DATE'] = pd.to_datetime(d['DATE']).dt.date
    daily = {}
    for r in d.to_dict('records'):
        daily.setdefault(r['DATE'], []).append(r)
    return daily, sorted(daily.keys())


base = df.drop(columns=[c for c in ['OPEN_next', 'ATR_next', '_signal_raw', 'YEAR']
                        if c in df.columns])
if raw_flag:
    # restore the contaminated column so the baseline really is the old behaviour
    base = base.copy()
    base['BB_Enter_Today'] = base['BB_Enter_Signal_Raw'].fillna(False).astype(bool)

out = {}
for label, frame in (('CONTAMINATED (fill on signal bar)', base),
                     ('HONEST (fill next bar)', lag_four(base))):
    print(f"\n  Running: {label} ...")
    daily, cal = build_daily(frame)
    curve = run_sim(PARAMS, daily, cal)
    if isinstance(curve, tuple):
        curve = curve[0]
    out[label] = metrics(curve, cal)
    print(f"    CAGR {out[label]['cagr']:+.2f}%   MaxDD {out[label]['maxdd']:.2f}%   "
          f"Final {out[label]['final']:,.0f}")

print("\n" + "=" * 74)
print("RESULT")
print("=" * 74)
c, h = out['CONTAMINATED (fill on signal bar)'], out['HONEST (fill next bar)']
print(f"  CAGR  : {c['cagr']:+.2f}%  ->  {h['cagr']:+.2f}%   "
      f"(delta {h['cagr'] - c['cagr']:+.2f} pts)")
print(f"  MaxDD : {c['maxdd']:.2f}%  ->  {h['maxdd']:.2f}%   "
      f"(delta {h['maxdd'] - c['maxdd']:+.2f} pts)")
print("\n  Read the CAGR delta as the size of the correction on ONE fixed parameter")
print("  set over the full period. It is an indication, not the new headline: the")
print("  real WFO re-selects parameters under honest timing and chains OOS windows,")
print("  and the chained number is the one that counts.")
print("=" * 74)
