"""
test_macro_gate_measure.py
--------------------------
Tests Stage 1b of measure_lookahead_bias.py -- the finding #32 measurement.

WHY THIS TEST EXISTS
    Stage 1b is not a pass/fail check, it is a MEASUREMENT, and it ends by
    printing a verdict in prose: "flattering", "penalising" or "noise". dell is
    going to read that verdict off a 15-year panel and decide how much compute
    to spend on the re-run. So the verdict has to be right, and there are two
    ways it can be wrong that no amount of "it ran without crashing" would
    catch:

      1. THE SIGN CONVENTION. `spread = mean(MORE) - mean(FEWER)` is trivially
         easy to write backwards, and backwards it would report a bias that
         HURT the backtest as one that FLATTERED it. Nothing about the output
         looks wrong when the sign is flipped -- it is a plausible number with
         a confident sentence attached.

      2. THE NOISE FLOOR. The first version of this stage printed "Positive =>
         the backtest was flattered" for a +0.030% spread with t = +0.57, i.e.
         pure noise. dell's standing instruction is to say "this doesn't clear
         the bar" rather than round a result up, and a verdict function that
         calls noise a finding does the opposite.

    So this test builds three panels where the RIGHT ANSWER IS KNOWN BY
    CONSTRUCTION and checks the verdict against it.

      Panel A  breadth rises on up days (what real breadth does -- it is a
               count of stocks above their MA). Contaminated reads today's
               breadth, so it gets extra slots exactly on up days.
               EXPECT: verdict 'flattering', spread > 0, t > 2.
      Panel B  breadth is an independent random walk, uncorrelated with
               returns.  EXPECT: verdict 'noise'.
      Panel C  breadth rises on DOWN days (sign deliberately inverted).
               EXPECT: verdict 'penalising', spread < 0. This is the case that
               catches a flipped comparison: A and C differ only in the sign of
               the breadth/return relationship, so a backwards `spread` maps
               both to the same verdict and the test fails.

    Panel C is the one that matters. A and B alone would pass with the sign
    reversed.

  Test 1 : row 0 is excluded from the change counts.
  Test 2 : an inert gate is reported as inert, not as "0 changes".
  Test 3 : tier counting ignores sub-threshold moves and catches boundary ones.
  Test 4 : the three panels get the three verdicts (the sign check).

RUN
    python test_macro_gate_measure.py
"""

import io
import sys
from contextlib import redirect_stdout

import numpy as np
import pandas as pd

sys.path.insert(0, '.')
from engine_harness import load_functions

MEASURE_FILE = 'measure_lookahead_bias.py'

fns, _ = load_functions(['slots', 'bb_frac', 'stage_1b'], engine_file=MEASURE_FILE)
slots, bb_frac, stage_1b = fns['slots'], fns['bb_frac'], fns['stage_1b']

failures = []


def check(cond, msg):
    print(f"  {'OK  ' if cond else 'FAIL'} {msg}")
    if not cond:
        failures.append(msg)


def quiet(df):
    """Run stage_1b and keep its return value, suppressing the printout."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = stage_1b(df)
    return res, buf.getvalue()


def panel(breadth_by_date, day_ret_by_date, regime='BULL', vix=None, n_syms=8):
    """A minimal panel: one OPEN/CLOSE pair per symbol per date, engineered so
    the cross-sectional mean of CLOSE/OPEN-1 equals day_ret_by_date exactly.
    Stage 1b only reads DATE, SYMBOL, OPEN, CLOSE and the three macro columns,
    so nothing else needs to be real."""
    dates = pd.bdate_range('2015-01-01', periods=len(breadth_by_date))
    rows = []
    for i, d in enumerate(dates):
        for s in range(n_syms):
            o = 100.0 + s
            rows.append({
                'DATE': d, 'SYMBOL': f'S{s}', 'OPEN': o,
                'CLOSE': o * (1 + day_ret_by_date[i]),
                'Market_Breadth': breadth_by_date[i],
                'Regime_Label': regime if isinstance(regime, str) else regime[i],
                'VIX_Spike': False if vix is None else bool(vix[i]),
            })
    return pd.DataFrame(rows)


# ======================================================================
print("=" * 74)
print("TEST 1 -- row 0 is excluded from the change counts")
print("=" * 74)
print("  Row 0 has no yesterday, so stage_1b seeds its lag with the fail-safe")
print("  (breadth 0.0, regime BEAR). Counting that seed as a 'change' made a")
print("  100%-BULL fixture report 'Regime_Label changed: 1', which invites")
print("  exactly the wrong conclusion. Found 2026-08-22.\n")

n = 60
flat = panel([0.80] * n, [0.001] * n, regime='BULL')
res, txt = quiet(flat)
check(res['n_cmp'] == res['n_dates'] - 1,
      f"n_cmp {res['n_cmp']} == n_dates {res['n_dates']} - 1")
check(res['regime_chg'] == 0,
      f"constant-BULL panel reports regime_chg == 0 (got {res['regime_chg']})")
check(res['breadth_tier_chg'] == 0,
      f"constant-breadth panel reports breadth_tier_chg == 0 "
      f"(got {res['breadth_tier_chg']})")
check(res['slot_chg'] == 0 and res['frac_chg'] == 0,
      f"and therefore no capacity change at all "
      f"(slots {res['slot_chg']}, frac {res['frac_chg']})")
print()


# ======================================================================
print("=" * 74)
print("TEST 2 -- an inert gate is reported as inert, not as '0 changes'")
print("=" * 74)
print("  '0 changes' reads like 'this gate is fine'. It can equally mean 'this")
print("  gate never fires on this panel', which is a different statement and")
print("  changes what the re-run is expected to show.\n")

res, txt = quiet(flat)
check(res['n_vix'] == 0, f"n_vix == 0 on a no-spike panel (got {res['n_vix']})")
check('INERT' in txt and 'kill-switch' in txt,
      "printout says the max_bb_pos=0 kill-switch is INERT")
check('single regime throughout' in txt,
      "printout flags the single-regime panel's bb_frac branch as inert")

vixy = panel([0.80] * n, [0.001] * n, regime='BULL',
             vix=[i % 10 == 0 for i in range(n)])
res2, txt2 = quiet(vixy)
check(res2['n_vix'] == 6, f"a panel with spikes counts them (got {res2['n_vix']})")
check('kill-switch is INERT' not in txt2,
      "and does NOT claim the kill-switch is inert")
check(res2['vix_chg'] > 0 and res2['slot_chg'] > 0,
      f"VIX changes drive slot changes (vix_chg {res2['vix_chg']}, "
      f"slot_chg {res2['slot_chg']})")
print()


# ======================================================================
print("=" * 74)
print("TEST 3 -- tier counting, not raw-value counting")
print("=" * 74)
print("  The gates are step functions at 0.65 and 0.50. A breadth move of")
print("  0.80 -> 0.70 changes no decision and must not be counted; 0.66 -> 0.64")
print("  halves the slot cap from 6 to 3 and must be.\n")

# alternates 0.80 / 0.70: both in the >0.65 tier, so zero behavioural change
sub = panel([0.80 if i % 2 else 0.70 for i in range(n)], [0.001] * n)
res3, _ = quiet(sub)
check(res3['breadth_tier_chg'] == 0,
      f"0.70<->0.80 (same tier) counts 0 tier changes (got {res3['breadth_tier_chg']})")
check(res3['slot_chg'] == 0,
      f"and 0 slot changes (got {res3['slot_chg']})")

# alternates 0.66 / 0.64: straddles the 0.65 boundary every single day
strad = panel([0.66 if i % 2 else 0.64 for i in range(n)], [0.001] * n)
res4, _ = quiet(strad)
check(res4['breadth_tier_chg'] == n - 1,
      f"0.64<->0.66 (straddles 0.65) counts all {n - 1} (got "
      f"{res4['breadth_tier_chg']})")
check(res4['slot_chg'] == n - 1,
      f"and all {n - 1} slot changes (got {res4['slot_chg']})")
# and the slot values are the ones the engine would compute
check(slots(0.66, False) == 6 and slots(0.64, False) == 3 and slots(0.40, False) == 1
      and slots(0.90, True) == 0,
      "slots() mirrors the engine: 0.66->6, 0.64->3, 0.40->1, VIX->0")
check(bb_frac(0.66, 'BULL') == 0.80 and bb_frac(0.55, 'BULL') == 0.60
      and bb_frac(0.40, 'BULL') == 0.35 and bb_frac(0.90, 'BEAR') == 0.20,
      "bb_frac() mirrors the engine: .80/.60/.35 by tier in BULL, .20 in BEAR")
print()


# ======================================================================
print("=" * 74)
print("TEST 4 -- the verdict, on three panels whose answer is known")
print("=" * 74)
print("  Panel C is the load-bearing one: it is Panel A with the breadth/return")
print("  relationship inverted, so a `spread` computed backwards would give A")
print("  and C the SAME verdict and this test would fail.\n")

RNG = np.random.default_rng(7)
N = 1200
rets = RNG.normal(0.0005, 0.010, N)

# Panel A: breadth tracks the day's return, as real breadth does. The
# contaminated read therefore hands out extra slots exactly on up days.
bA = np.where(rets > 0, 0.80, 0.40)
# Panel B: breadth independent of returns.
bB = RNG.choice([0.80, 0.55, 0.40], size=N)
# Panel C: breadth INVERTED -- high on down days.
bC = np.where(rets > 0, 0.40, 0.80)

EXPECT = [
    ('A  breadth follows returns  ', bA, 'flattering', +1),
    ('B  breadth independent      ', bB, 'noise', 0),
    ('C  breadth inverted         ', bC, 'penalising', -1),
]
for label, b, want, want_sign in EXPECT:
    res, _ = quiet(panel(list(b), list(rets)))
    got = res['verdict']
    sp, t = res.get('spread', float('nan')), res.get('t', float('nan'))
    ok = got == want
    if want_sign > 0:
        ok = ok and sp > 0 and t > 2
    elif want_sign < 0:
        ok = ok and sp < 0 and t < -2
    else:
        ok = ok and abs(t) < 2
    check(ok, f"{label} verdict={got:<12} spread={sp:+.4f}%  t={t:+6.2f}  "
              f"(wanted {want})")

print()
print("  Interpretation of the numbers above, for the record: A and C are")
print("  mirror images and their t-statistics come out near-symmetric, which is")
print("  what you want from a sign convention that is actually consistent. B")
print("  sits inside the noise floor despite 1,200 dates, which is the point --")
print("  a large sample does not manufacture a direction that is not there.")
print()


# ======================================================================
print("=" * 74)
if failures:
    print(f"FAILED -- {len(failures)} check(s):")
    for f in failures:
        print("  - " + f)
    print("=" * 74)
    sys.exit(1)
print("ALL STAGE 1b CHECKS PASSED")
print("  Row 0 excluded, inert gates named as inert, tier counting is")
print("  behavioural, and the direction verdict has the right sign on a panel")
print("  built to have the opposite one.")
print("=" * 74)
