"""
test_window_gap_decomposition.py
================================
Changelog item 15 states:

    "per-window averages meaningfully overstate true performance (confirmed:
     arithmetic mean 15.69% vs. true compounded 11.72% on one early run, a
     ~4pp gap driven by volatility drag / Jensen's inequality)"

Finding #28 (CAGR annualization units) puts that explanation in doubt, because
the two numbers being compared do NOT use the same annualization convention:

  Average OOS CAGR (15.69%)  <- mean of results_df['OOS_CAGR'], and OOS_CAGR
                                comes from calculate_fitness() at line 461,
                                which annualizes with 365.25/days where `days`
                                counts TRADING days  => INFLATED by ^1.4494
  Chained CAGR     (11.72%)  <- section 6, uses chained_days/252  => CORRECT

So the gap mixes a real effect (volatility drag, which is genuine and always
has the sign item 15 claims) with an artifact (the units bug). This script asks
how much of the ~4pp each can account for.

WHAT THIS IS AND IS NOT
    This is an ANALYTIC CONSISTENCY CHECK on the two published numbers, plus a
    Monte Carlo of the drag term. It is NOT a measurement of dell's actual run
    -- that needs the per-window OOS_CAGR column from the stored WFO CSV, which
    is not available in this sandbox. The script prints exactly what to read
    from that CSV to settle it definitively.
"""

import numpy as np

TRADING_DAYS = 252
CAL = 365.25
EXP = CAL / TRADING_DAYS          # 1.4494 -- the buggy exponent
REPORTED_AVG = 0.1569             # "arithmetic mean 15.69%"
REPORTED_CHAINED = 0.1172         # "true compounded 11.72%"
N_WINDOWS = 14

print("=" * 78)
print("Setup")
print("=" * 78)
print(f"  Buggy exponent 365.25/252                     : {EXP:.4f}")
print(f"  OOS window length (TEST_YEARS)                : 1 year  -> full-strength inflation")
print(f"  A one-year window's honest CAGR ~= its total return, so per-window")
print(f"  OOS_CAGR ~= (1 + r_i)^{EXP:.4f} - 1  where r_i is window i's true return.")

# ---------------------------------------------------------------------------
# 1. The convexity floor.
#    f(r) = (1+r)^EXP - 1 is increasing and CONVEX on r > -1:
#        f''(r) = EXP*(EXP-1)*(1+r)^(EXP-2) > 0   since EXP > 1
#    Jensen  : mean(f(r_i))  >=  f(mean(r_i))
#    AM-GM   : mean(r_i)     >=  geometric mean(r_i)
#    f incr. : f(mean(r_i))  >=  f(geo)
#    Therefore the buggy average has a hard FLOOR of f(geo), attained only when
#    every window return is identical (zero dispersion).
# ---------------------------------------------------------------------------
floor = (1 + REPORTED_CHAINED) ** EXP - 1

print("\n" + "=" * 78)
print("Test 1 -- convexity floor: what MUST the buggy average be?")
print("=" * 78)
print(f"  If the true window returns compound to {REPORTED_CHAINED*100:.2f}%/yr, then the buggy")
print(f"  formula must report an average of AT LEAST:")
print(f"      f(geo) = (1 + {REPORTED_CHAINED:.4f})^{EXP:.4f} - 1 = {floor*100:.2f}%")
print(f"  and dispersion can only push it HIGHER (Jensen, f is convex).")
print(f"\n  Published average : {REPORTED_AVG*100:.2f}%")
print(f"  Required floor    : {floor*100:.2f}%")

if REPORTED_AVG < floor:
    print(f"\n  => The published average is {(floor - REPORTED_AVG)*100:.2f}pp BELOW the floor.")
    print("     These two numbers are MUTUALLY INCONSISTENT: no set of one-year")
    print("     window returns can compound to 11.72%/yr and also produce a")
    print("     buggy-formula average of 15.69%.")
    print("\n     PROBABLE PROVENANCE ERROR, visible in item 15's own text: 11.72%")
    print("     appears TWICE there -- first as the SYNTHETIC smooth-curve unit")
    print("     test's analytical expectation ('matched analytical expectation")
    print("     exactly: 11.72% CAGR, -43.6% DD'), then again as 'true compounded")
    print("     11.72% on one early run'. If the comparison paired a real run's")
    print("     average against the synthetic test's CAGR, it is not a drag")
    print("     measurement at all -- a smooth synthetic curve has near-zero")
    print("     window-to-window dispersion by construction, and drag IS that")
    print("     dispersion. Zero dispersion => zero drag, definitionally.")
else:
    print(f"\n  => Consistent with the floor; dispersion accounts for "
          f"{(REPORTED_AVG - floor)*100:.2f}pp.")

# Verify the convexity claim numerically instead of trusting the algebra.
rng = np.random.default_rng(11)
viol = 0
for _ in range(20000):
    r = rng.uniform(-0.45, 0.75, N_WINDOWS)
    lhs = np.mean((1 + r) ** EXP - 1)
    rhs = (1 + r.mean()) ** EXP - 1
    if lhs < rhs - 1e-12:
        viol += 1
print(f"\n  Numeric check of Jensen on 20,000 random 14-window sets: "
      f"{viol} violations of mean(f(r)) >= f(mean(r)).")
assert viol == 0, "convexity argument does not hold numerically -- do not trust Test 1"

# ---------------------------------------------------------------------------
# 2. Decomposition at a fixed, realistic dispersion.
#    Hold the geometric mean at 11.72% and vary annual dispersion. Report the
#    drag term and the units term separately.
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Test 2 -- decomposing the gap: drag vs units, by window-return dispersion")
print("=" * 78)
print("  Windows constructed so their GEOMETRIC mean is exactly 11.72% (i.e. they")
print("  chain to the published honest number), then measured both ways.\n")
print(f"  {'sd of':>6} {'honest':>9} {'drag':>8} {'buggy':>9} {'units':>8} {'total':>8}")
print(f"  {'window':>6} {'arith':>9} {'term':>8} {'arith':>9} {'term':>8} {'gap':>8}")
print(f"  {'ret':>6} {'mean':>9} {'(pp)':>8} {'mean':>9} {'(pp)':>8} {'(pp)':>8}")
print("  " + "-" * 54)

rows = []
for sd in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
    # log-returns centred so the geometric mean is exactly the target
    z = rng.standard_normal(200000 * 0 + N_WINDOWS * 40000).reshape(-1, N_WINDOWS)
    logr = z * np.log1p(sd)
    logr = logr - logr.mean(axis=1, keepdims=True) + np.log1p(REPORTED_CHAINED)
    r = np.expm1(logr)
    honest_arith = r.mean(axis=1).mean()
    buggy_arith = (((1 + r) ** EXP) - 1).mean(axis=1).mean()
    drag = honest_arith - REPORTED_CHAINED
    units = buggy_arith - honest_arith
    rows.append((sd, honest_arith, drag, buggy_arith, units))
    print(f"  {sd*100:5.0f}% {honest_arith*100:8.2f}% {drag*100:+7.2f} "
          f"{buggy_arith*100:8.2f}% {units*100:+7.2f} "
          f"{(buggy_arith - REPORTED_CHAINED)*100:+7.2f}")

print("\n  Read the table like this: the 'total gap' column is what item 15 would")
print("  have printed at that dispersion. The published gap was +3.97pp.")
print("  At EVERY dispersion the units term alone exceeds the entire published")
print("  gap -- which is the same conclusion Test 1 reached by algebra.")

# Which dispersion reproduces the published +3.97pp total gap?
tot = np.array([r[3] - REPORTED_CHAINED for r in rows])
print(f"\n  Smallest total gap achievable in this family (sd=5%): "
      f"{tot.min()*100:+.2f}pp, still above the published +3.97pp.")

# ---------------------------------------------------------------------------
# 3. What the honest comparison would have looked like.
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("Test 3 -- deflating the published average back to honest units")
print("=" * 78)
deflated_point = (1 + REPORTED_AVG) ** (1 / EXP) - 1
print(f"  Naive deflation of the average (ignores Jensen, so it is a LOWER bound")
print(f"  on the honest arithmetic mean):")
print(f"      (1 + {REPORTED_AVG:.4f})^(1/{EXP:.4f}) - 1 = {deflated_point*100:.2f}%")
print(f"  Published chained (honest)                      : {REPORTED_CHAINED*100:.2f}%")
print(f"\n  {deflated_point*100:.2f}% < {REPORTED_CHAINED*100:.2f}%: the deflated per-window average lands BELOW")
print("  the chained figure. Since an arithmetic mean can never be below the")
print("  geometric mean of the same numbers, this is the same inconsistency as")
print("  Test 1, seen from the other direction.")

print("\n" + "=" * 78)
print("CONCLUSION")
print("=" * 78)
print("""  1. CONFIRMED by reading the code (wfo_engine_updated.py:461 vs :539):
     'Average OOS CAGR' is inflated by the units bug; 'Chained CAGR' is not.
     Item 15 compares two numbers on different annualization conventions.

  2. CONFIRMED by algebra + Monte Carlo: the units bug alone would open a gap
     of AT LEAST +5.71pp between those two lines. The published gap is
     +3.97pp -- SMALLER than the artifact that must be present. So the
     15.69%/11.72% pair cannot both come from one coherent run of this code.
     Item 15's own text shows the likely reason: 11.72% is quoted there twice,
     once as the SYNTHETIC unit test's expectation and once as a real run's
     compounded CAGR. Either way the pair is not safe to cite as a measurement
     of volatility drag, and a smooth synthetic curve has no drag to measure.

  3. UNAFFECTED: item 15's actual conclusion -- that the chained curve is the
     correct headline metric -- stands on its own independent reasoning
     (per-window capital resets cannot show a multi-year losing streak
     compounding across window boundaries). Volatility drag is also real and
     always has the sign item 15 claims (arithmetic >= geometric, always).
     What is wrong is only the QUANTIFICATION: '~4pp driven by volatility
     drag' is not established, and the true drag term is unmeasured.

  4. ALSO UNAFFECTED: the 14.17% / -29.96% Phase 1 headline. Those come from
     the chained block, which uses the correct formula. Finding #28 changes the
     per-window columns and can change parameter SELECTION -- it does not
     restate the headline. (The look-ahead fix, finding #26, is what will
     restate the headline.)

  TO SETTLE THIS DEFINITIVELY (needs dell's stored WFO CSV, ~2 minutes):
     import pandas as pd
     d = pd.read_csv('WFO_Dual_Brain_Optimization_v3_dd_fix.csv')
     honest = ((1 + d['OOS_CAGR']/100) ** (252/365.25) - 1) * 100
     print(d['OOS_CAGR'].mean(), '->', honest.mean())
     The second number is the real honest per-window average. Compare THAT to
     the chained CAGR from the same run; the difference is the actual drag.""")
print("=" * 78)
