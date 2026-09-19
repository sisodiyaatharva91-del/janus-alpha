"""
test_cagr_units.py
------------------
Finding #28: calculate_fitness() in wfo_engine_updated.py annualizes with
365.25/days while `days` counts TRADING days. The same file's chained-CAGR
block (line 521) correctly uses days/252. Both cannot be right.

  Test 1 : magnitude -- what the engine reports for a curve of known CAGR.
  Test 2 : is the distortion a constant exponent, i.e. rank-preserving on
           CAGR alone?
  Test 3 : does it change which candidate the OPTIMIZER selects? (the part
           that actually matters -- the WFO picks on fitness, not on CAGR)
  Test 4 : is the headline chained CAGR affected? (separate code path)
  Test 5 : how much of the documented per-window-vs-chained gap does this
           explain on its own?
"""

import re
import numpy as np
import pandas as pd

src = open('wfo_engine_updated.py').read()
m = re.search(r'^def calculate_fitness.*?(?=\n# =+\n)', src, re.S | re.M)
ns = {'pd': pd, 'np': np, 'W_SORTINO': 0.35, 'W_PF': 0.20,
      'W_WINRATE': 0.15, 'W_TRADES': 0.30}
exec(m.group(0), ns)
calculate_fitness = ns['calculate_fitness']

TRADING_DAYS_PER_YEAR = 252

# This file was written to DEMONSTRATE the bug against the unpatched engine, so
# its assertions predicted the inflated number. Once apply_fixes.py --fix5 is
# applied the engine is correct and those same assertions fail -- which looks
# like a regression and is actually the fix working. So detect which engine we
# are looking at and assert the matching closed form, and keep both branches:
# post-fix it is a regression test, pre-fix it still reproduces the finding.
ENGINE_IS_FIXED = 'UNITS FIX 2026-08-22' in src
print(f"engine: {'PATCHED (fix5 applied)' if ENGINE_IS_FIXED else 'UNPATCHED (bug present)'}\n")


def curve_with_true_cagr(true_cagr, n_years, seed=0, vol=0.0):
    """Equity curve over n_years of trading days whose ENDPOINT gives exactly
    true_cagr. Optional daily noise leaves the endpoint untouched."""
    n = int(TRADING_DAYS_PER_YEAR * n_years)
    total = (1 + true_cagr) ** n_years
    base = np.linspace(0, 1, n)
    eq = 100.0 * total ** base
    if vol > 0:
        rng = np.random.default_rng(seed)
        noise = rng.normal(0, vol, n)
        noise -= noise.mean()
        eq = eq * np.exp(np.cumsum(noise) - np.linspace(0, np.cumsum(noise)[-1], n))
    eq[0], eq[-1] = 100.0, 100.0 * total
    return list(eq)


print("=" * 74)
print("TEST 1 -- magnitude: reported vs true CAGR")
print("=" * 74)
print(f"  {'true CAGR':>10} | {'engine reports':>14} | {'inflation':>10}")
print("  " + "-" * 40)
for tc in (0.05, 0.10, 0.1417, 0.20, 0.30):
    for yrs in (1,):
        eq = curve_with_true_cagr(tc, yrs)
        _, rep, _, _, _ = calculate_fitness(eq, 60, 40, 200.0, 100.0)
        print(f"  {tc*100:9.2f}% | {rep:13.2f}% | {rep/(tc*100):9.3f}x")
eq = curve_with_true_cagr(0.1417, 1)
_, rep, _, _, _ = calculate_fitness(eq, 60, 40, 200.0, 100.0)
if ENGINE_IS_FIXED:
    expected = 14.17
    assert abs(rep - expected) < 0.05, f"{rep} vs expected {expected}"
    print(f"\n  Closed form: reported = (1 + true)^(252/252) - 1 = true")
    print(f"  Verified: true 14.17% -> reported {rep:.2f}% (expected {expected:.2f}%)")
    print("  => FIXED: a curve of known 14.17% true CAGR now reports 14.17%. The")
    print("     inflation factor is 1.000x at every magnitude in the table above,")
    print("     which is the whole point -- per-window CAGR now agrees with the")
    print("     chained-CAGR block that was right all along.\n")
else:
    expected = ((1.1417) ** (365.25 / 252) - 1) * 100
    assert abs(rep - expected) < 0.05, f"{rep} vs predicted {expected}"
    print(f"\n  Closed form: reported = (1 + true)^(365.25/252) - 1 = (1+true)^{365.25/252:.4f} - 1")
    print(f"  Verified: true 14.17% -> reported {rep:.2f}% (predicted {expected:.2f}%)")
    print("  => CONFIRMED: `days` counts TRADING days, so 365.25/days annualizes as")
    print("     though a 252-day year were 365.25 days long. Every Fit / Validation /")
    print("     OOS per-window CAGR printed and written to the results CSV is inflated")
    print("     by that exponent.\n")


print("=" * 74)
print("TEST 2 -- is it rank-preserving on CAGR alone?")
print("=" * 74)
for yrs in (1, 2, 3):
    eq = curve_with_true_cagr(0.15, yrs)
    _, rep, _, _, _ = calculate_fitness(eq, 60, 40, 200.0, 100.0)
    implied = 15.0 if ENGINE_IS_FIXED else (1.15 ** (365.25 / 252) - 1) * 100
    label = 'expected' if ENGINE_IS_FIXED else 'exponent-only prediction'
    print(f"  {yrs}-year window, true 15.00% -> reported {rep:6.2f}% "
          f"({label} {implied:.2f}%)")
    assert abs(rep - implied) < 0.05, f"{yrs}y: {rep} vs {implied}"
if ENGINE_IS_FIXED:
    print("  => Window length no longer changes the answer AND the answer is now the")
    print("     true CAGR at every window length. Post-fix this is the regression")
    print("     test: any reappearance of a calendar-day divisor shows up here.\n")
else:
    print("  => The inflation factor is a CONSTANT exponent (365.25/252), independent")
    print("     of window length. So ranking candidates by CAGR alone is preserved,")
    print("     and the bug cannot be dismissed OR excused on that basis -- see Test 3.\n")


print("=" * 74)
print("TEST 3 -- does it change which candidate the optimizer PICKS?")
print("=" * 74)
print("  fitness uses sortino = (cagr/100) / downside_std, then")
print("  norm_sortino = min(sortino / 3.0, 1.0). Inflating cagr pushes candidates")
print("  INTO that cap, where they stop being distinguishable.\n")


def fitness_with(cagr_divisor, eq, w, l, gp, gl):
    """Recompute fitness with a corrected annualization, everything else identical."""
    eq_s = pd.Series(eq)
    pct = eq_s.pct_change().dropna()
    days = len(eq)
    cagr = ((eq_s.iloc[-1] / eq_s.iloc[0]) ** (cagr_divisor / days) - 1) * 100
    dd = ((eq_s - eq_s.cummax()) / eq_s.cummax()).min() * 100
    dstd = pct[pct < 0].std() * np.sqrt(252)
    sortino = (cagr / 100) / dstd if dstd > 0 else 0
    tt = w + l
    wr = (w / tt) * 100 if tt else 0
    pf = gp / gl if gl > 0 else 0
    score = (min(sortino / 3.0, 1.0) * 0.35 + min(pf / 2.5, 1.0) * 0.20
             + (wr / 100) * 0.15 + min(tt / 100.0, 1.0) * 0.30)
    if tt < 30:
        score -= 2.0
    if dd < -20:
        score -= 3.0
    elif dd < -15:
        score -= 1.0
    return score, cagr, sortino


# Candidate A: higher true return, smoother.  Candidate B: lower return, but
# better profit factor and win rate. Both are plausible WFO candidates.
A = dict(eq=curve_with_true_cagr(0.34, 1, seed=1, vol=0.004), w=52, l=48,
         gp=260.0, gl=180.0)
B = dict(eq=curve_with_true_cagr(0.26, 1, seed=2, vol=0.004), w=70, l=30,
         gp=300.0, gl=120.0)

rows = []
for name, kw in (('A', A), ('B', B)):
    buggy, c_b, s_b = fitness_with(365.25, **kw)
    fixed, c_f, s_f = fitness_with(252.0, **kw)
    rows.append((name, c_b, s_b, buggy, c_f, s_f, fixed))

print(f"  {'cand':<5} {'CAGR(buggy)':>12} {'sortino':>9} {'fitness':>9}   "
      f"{'CAGR(fixed)':>12} {'sortino':>9} {'fitness':>9}")
for n, cb, sb, fb, cf, sf, ff in rows:
    print(f"  {n:<5} {cb:11.2f}% {sb:9.2f} {fb:9.4f}   {cf:11.2f}% {sf:9.2f} {ff:9.4f}")

buggy_winner = max(rows, key=lambda r: r[3])[0]
fixed_winner = max(rows, key=lambda r: r[6])[0]
capped_buggy = [n for n, cb, sb, fb, cf, sf, ff in rows if sb / 3.0 >= 1.0]
capped_fixed = [n for n, cb, sb, fb, cf, sf, ff in rows if sf / 3.0 >= 1.0]
print(f"\n  Sortino term saturated at the 1.0 cap -- buggy: {capped_buggy or 'none'}"
      f" | fixed: {capped_fixed or 'none'}")
print(f"  Optimizer picks  -- buggy: {buggy_winner}   fixed: {fixed_winner}")
if buggy_winner != fixed_winner:
    print("  => CONFIRMED: the units bug changes the SELECTED parameter set, not just")
    print("     the reported number. Inflated CAGR saturates the sortino cap, the")
    print("     risk-adjusted term stops discriminating, and selection defaults to")
    print("     profit factor / win rate / trade count.")
else:
    print("  => On THIS pair the winner did not change; the saturation effect is real")
    print("     but did not flip the ordering here. Treat as a reporting bug with")
    print("     selection risk, not a proven selection change.")
print()


print("=" * 74)
print("TEST 4 -- is the HEADLINE chained CAGR affected?")
print("=" * 74)
# Reproduce the chained block's own arithmetic (lines 519-523).
true_cagr, yrs = 0.1417, 14
daily = (1 + true_cagr) ** (1 / TRADING_DAYS_PER_YEAR) - 1
chained_oos_returns = [daily] * (TRADING_DAYS_PER_YEAR * yrs)
chained_equity = pd.Series([1.0] + list(pd.Series([1 + r for r in chained_oos_returns]).cumprod()))
chained_years = len(chained_oos_returns) / 252
chained_cagr = ((chained_equity.iloc[-1]) ** (1 / chained_years) - 1) * 100
print(f"  Fed a curve of exactly {true_cagr*100:.2f}% true CAGR over {yrs} years,")
print(f"  the chained block reports: {chained_cagr:.2f}%")
assert abs(chained_cagr - true_cagr * 100) < 0.01, "chained CAGR is also wrong"
print("  => The chained block uses days/252 and is CORRECT. The ~14.17% headline")
print("     in the changelog is NOT inflated by this bug. Only the per-window")
print("     Fit / Validation / OOS numbers are.\n")


print("=" * 74)
print("TEST 5 -- how much of the per-window-vs-chained gap does this explain?")
print("=" * 74)
print("  The changelog attributes the gap between average per-window OOS CAGR and")
print("  the chained CAGR to volatility drag / Jensen's inequality. But a per-window")
print("  average is ALSO inflated by the exponent bug, so the two explanations")
print("  overlap and the drag term was likely overstated.\n")
print(f"  {'chained (true)':>16} | {'same value as the engine would':>32}")
print(f"  {'':>16} | {'PRINT it per-window':>32}")
print("  " + "-" * 52)
for tc in (0.10, 0.1417, 0.18):
    infl = ((1 + tc) ** (365.25 / 252) - 1) * 100
    print(f"  {tc*100:15.2f}% | {infl:31.2f}%")
print("\n  So if the per-window average OOS CAGR printed ~21% while chained was")
print("  14.17%, the exponent alone accounts for essentially the whole gap")
print(f"  ((1.1417)^1.4494 - 1 = {((1.1417)**(365.25/252)-1)*100:.2f}%), leaving little")
print("  for volatility drag. ACTION: read Average/Median OOS CAGR off the stored")
print("  WFO CSV and compare against the table above before keeping the drag")
print("  explanation in the changelog. This test does not have those numbers.")
print("=" * 74)
