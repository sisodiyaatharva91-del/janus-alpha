"""
test_cagr_units_selection.py
----------------------------
Follow-up to test_cagr_units.py Test 3, which was inconclusive: both synthetic
candidates saturated the sortino cap under BOTH formulas, so it could not show
whether the units bug changes optimizer SELECTION.

This builds candidates with controlled downside deviation, so the cap engages
for one candidate and not the other.

Two questions, kept separate:
  Q1 (existence) : can the bug flip the selected candidate at all?
  Q2 (exposure)  : over realistic downside-deviation levels, how wide is the
                   band of true CAGR where the buggy formula saturates the cap
                   and the correct one does not? That band is where selection
                   is at risk.

Q1 being true does NOT prove it happened in dell's 14 windows -- only that the
mechanism is live. Q2 says how plausible that is.
"""

import numpy as np
import pandas as pd

TD = 252
CAP = 3.0
W = dict(sortino=0.35, pf=0.20, wr=0.15, trades=0.30)


def make_curve(true_cagr, years, sigma, seed):
    """Curve whose endpoint gives exactly true_cagr, with daily noise of scale
    sigma. Noise is de-trended so the endpoint is unaffected."""
    n = int(TD * years)
    rng = np.random.default_rng(seed)
    z = rng.normal(0, sigma, n)
    z -= z.mean()
    log_path = np.cumsum(z)
    log_path -= np.linspace(0, log_path[-1], n)        # pin both ends
    drift = np.linspace(0, np.log((1 + true_cagr) ** years), n)
    return list(100.0 * np.exp(drift + log_path))


def downside_std(eq):
    r = pd.Series(eq).pct_change().dropna()
    return r[r < 0].std() * np.sqrt(TD)


def tune_sigma(true_cagr, years, target_dstd, seed):
    """Bisect on noise scale until downside deviation hits target_dstd."""
    lo, hi = 1e-6, 0.20
    for _ in range(60):
        mid = (lo + hi) / 2
        d = downside_std(make_curve(true_cagr, years, mid, seed))
        if d < target_dstd:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def fitness(eq, w, l, gp, gl, divisor):
    eq_s = pd.Series(eq)
    days = len(eq)
    cagr = ((eq_s.iloc[-1] / eq_s.iloc[0]) ** (divisor / days) - 1) * 100
    dd = ((eq_s - eq_s.cummax()) / eq_s.cummax()).min() * 100
    dstd = downside_std(eq)
    sortino = (cagr / 100) / dstd if dstd > 0 else 0
    tt = w + l
    wr = (w / tt) * 100 if tt else 0
    pf = gp / gl if gl > 0 else 0
    score = (min(sortino / CAP, 1.0) * W['sortino'] + min(pf / 2.5, 1.0) * W['pf']
             + (wr / 100) * W['wr'] + min(tt / 100.0, 1.0) * W['trades'])
    if tt < 30:
        score -= 2.0
    if dd < -20:
        score -= 3.0
    elif dd < -15:
        score -= 1.0
    return dict(score=score, cagr=cagr, sortino=sortino, dstd=dstd,
                capped=sortino / CAP >= 1.0, dd=dd)


print("=" * 78)
print("Q1 -- EXISTENCE: can the units bug flip the selected candidate?")
print("=" * 78)

# A: strong true CAGR, moderate downside dev -> capped under buggy, NOT under fixed.
# B: lower true CAGR but very smooth -> capped under BOTH. B also has better
#    profit factor and win rate, which is what it wins on once the sortino term
#    stops separating them.
A_cagr, A_dstd = 0.30, 0.12
B_cagr, B_dstd = 0.20, 0.05
eqA = make_curve(A_cagr, 1, tune_sigma(A_cagr, 1, A_dstd, 11), 11)
eqB = make_curve(B_cagr, 1, tune_sigma(B_cagr, 1, B_dstd, 22), 22)

# A's edge on the non-sortino terms is set deliberately, and the window is
# narrow and knowable in advance rather than fumbled for:
#   - dropping below the cap costs A (1.0 - 2.4967/3) * 0.35 = 0.0583 fitness
#   - so A must lead B by MORE than 0.0256 (its buggy-formula deficit) and LESS
#     than 0.0583 for the two formulas to disagree
# A leads on profit factor (1.90 vs 1.70) and trade count (100 vs 95); B leads
# on win rate. All four values are ordinary for this strategy.
A = dict(eq=eqA, w=53, l=47, gp=285.0, gl=150.0)   # PF 1.90, WR 53.0%, 100 trades
B = dict(eq=eqB, w=56, l=39, gp=250.0, gl=147.0)   # PF 1.70, WR 58.9%,  95 trades

print(f"  {'cand':<5} {'true CAGR':>10} {'dstd':>7} | "
      f"{'BUGGY cagr':>11} {'sortino':>8} {'cap?':>5} {'fitness':>8} | "
      f"{'FIXED cagr':>11} {'sortino':>8} {'cap?':>5} {'fitness':>8}")
print("  " + "-" * 106)
res = {}
for name, kw, tc in (('A', A, A_cagr), ('B', B, B_cagr)):
    b = fitness(divisor=365.25, **kw)
    f = fitness(divisor=252.0, **kw)
    res[name] = (b, f)
    print(f"  {name:<5} {tc*100:9.2f}% {b['dstd']:7.3f} | "
          f"{b['cagr']:10.2f}% {b['sortino']:8.2f} {str(b['capped']):>5} {b['score']:8.4f} | "
          f"{f['cagr']:10.2f}% {f['sortino']:8.2f} {str(f['capped']):>5} {f['score']:8.4f}")

buggy_pick = max(res, key=lambda k: res[k][0]['score'])
fixed_pick = max(res, key=lambda k: res[k][1]['score'])
print(f"\n  Optimizer selects -- BUGGY: {buggy_pick}    FIXED: {fixed_pick}")

if buggy_pick != fixed_pick:
    print(f"\n  => CONFIRMED (existence): selection flips from {buggy_pick} to {fixed_pick}.")
    print("     Mechanism: under the buggy formula both candidates saturate the")
    print("     sortino cap, so the risk-adjusted term contributes an identical 0.35")
    print("     to both and selection falls through to profit factor / win rate /")
    print("     trade count. Under the correct formula A drops below the cap, the")
    print(f"     sortino term separates them again, and the winner changes.")
    print("     The bug is therefore NOT cosmetic -- it can change which parameter")
    print("     set the WFO carries into the OOS test.")
else:
    print("\n  => Could not produce a flip on this pair. Reported as-is.")

print("\n  Caveat, stated plainly: this is an EXISTENCE proof on constructed inputs.")
print("  It does not show that selection actually changed in any of the 14 real")
print("  windows. Only a re-run can show that. Q2 below bounds how likely it is.\n")


print("=" * 78)
print("Q2 -- EXPOSURE: how wide is the at-risk band?")
print("=" * 78)
print("  The cap engages at sortino = 3.0, i.e. cagr = 300 * downside_dev (in %).")
print("  A candidate is MISCLASSIFIED when the buggy cagr clears that bar but the")
print("  correct cagr does not. Solving for true CAGR:\n")
print(f"  {'downside dev':>13} | {'cap needs cagr':>15} | "
      f"{'true CAGR misread as capped':>29}")
print("  " + "-" * 64)
for dstd in (0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25):
    need = CAP * dstd                       # required cagr as a fraction
    lo = (1 + need) ** (252 / 365.25) - 1    # buggy reports `need` when true is this
    print(f"  {dstd*100:12.1f}% | {need*100:14.1f}% | "
          f"{lo*100:12.1f}%  ->  {need*100:.1f}%")
print("\n  Read the right column as: any candidate whose TRUE CAGR falls in that")
print("  range is treated by the optimizer as though it had maxed out the")
print("  risk-adjusted term, when it had not. For downside deviation in the 10-15%")
print("  band -- ordinary for this kind of equity strategy -- the at-risk window is")
print("  roughly 19-30% to 30-45% true CAGR, which is squarely where 1-to-3-year")
print("  fit-window candidates land. So the mechanism is not exotic.")
print("=" * 78)
