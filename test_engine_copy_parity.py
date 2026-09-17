"""
test_engine_copy_parity.py
--------------------------
Finding #34. generate_live_params.py keeps its OWN copy of
run_headless_simulation and calculate_fitness, under a docstring that used to
claim they were "kept in sync manually". They were not: the engine received the
idle-yield and CAGR units fixes and this copy did not, so the parameters written
to live_params.json -- the ones actually traded -- were being SELECTED under
different arithmetic than the WFO validated.

WHY THIS TEST IS BEHAVIOURAL AND NOT TEXTUAL
    The obvious guard is to diff the two function bodies. That fails badly: the
    copies differ in line-splitting (`a, b = x, y` vs two statements), in
    comments, and in a total_pnl accumulator the engine computes and never
    returns. A textual or AST diff flags all of that, so it would cry wolf and
    get muted -- which is how the drift survived in the first place.

    So instead: RUN both copies on the same panel with the same params and
    require bit-identical output. That is the property anyone actually cares
    about, it is robust to cosmetic edits by construction, and it cannot be
    satisfied by a copy that merely looks similar.

  Test 1 : the shared module-level constants are equal in both files.
  Test 2 : both run_headless_simulation copies return bit-identical 7-tuples
           on a 40-symbol x 900-bar panel spanning both regimes.
  Test 3 : both calculate_fitness copies return bit-identical 5-tuples across
           a spread of equity curves, including the degenerate ones.
  Test 4 : the test has teeth -- re-running Test 3 against the ORIGINAL buggy
           exponent proves it would have caught finding #34.

If you ever extract a genuine shared module, delete this test along with the
duplicate: it exists only to police the duplication.
"""

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, '.')

from engine_harness import load_engine, load_function
import generate_live_params as glp

RNG = np.random.default_rng(11)

PARAMS = {
    'start_cap': 600000, 'slip_tax': 0.15, 'idle_yield': 4.0,
    'bull': {'bb_tgt': 4.0, 'bb_stop': 2.0, 'bb_risk': 2.0, 'mr_time': 5, 'mr_pos_size': 10.0},
    'bear': {'bb_tgt': 3.0, 'bb_stop': 2.0, 'bb_risk': 1.5, 'mr_time': 5, 'mr_pos_size': 8.0},
}

failures = []


def check(cond, msg):
    if cond:
        print(f"  OK   {msg}")
    else:
        print(f"  FAIL {msg}")
        failures.append(msg)


# ======================================================================
print("=" * 74)
print("TEST 1 -- shared constants agree between the two files")
print("=" * 74)
_, eng_ns = load_engine()
SHARED = ['TRADING_DAYS_PER_YEAR', 'IDLE_YIELD_PCT', 'MAX_GAP_LOSS_PCT',
          'ASSUMED_WORST_CASE_GAP_PCT', 'SLIPPAGE_TAX_PCT', 'START_CAPITAL',
          'W_SORTINO', 'W_PF', 'W_WINRATE', 'W_TRADES']
for c in SHARED:
    a = eng_ns.get(c, '<missing in engine>')
    b = getattr(glp, c, '<missing in generate_live_params>')
    check(a == b, f"{c:<28} engine={a!r} live_params={b!r}")
print()


# ======================================================================
print("=" * 74)
print("TEST 2 -- both run_headless_simulation copies, same panel, same params")
print("=" * 74)


def make_panel(n_days=900, n_syms=40):
    """Deliberately spans BULL and BEAR and fires a VIX_Spike, so the branches
    that differ between the copies (allocation tiers, slot caps, gap sizing)
    all get exercised rather than just the happy path."""
    dates = pd.bdate_range('2021-01-01', periods=n_days)
    rows = []
    for s in range(n_syms):
        sym, px = f'SYM{s:03d}', 100.0 + s * 11
        for i, d in enumerate(dates):
            base = 0.012 + (s % 6) * 0.004
            vol = base * (0.5 if (i % 180) > 140 and s % 3 == 0 else 1.0)
            ret = (0.0003 + (s % 7) * 0.00035) + RNG.normal(0, vol)
            prev = px
            px = max(1.0, px * (1 + ret))
            o = prev * (1 + RNG.normal(0, vol * 0.4))
            rows.append({
                'DATE': d.date(), 'SYMBOL': sym, 'OPEN': o,
                'HIGH': max(o, px) * (1 + abs(RNG.normal(0, vol * 0.4))),
                'LOW': min(o, px) * (1 - abs(RNG.normal(0, vol * 0.4))),
                'CLOSE': px,
                'Turnover_SMA_50': (300_000 + s * 90_000) * px,
                # cycle the allocation tiers: >0.65, 0.50-0.65, <0.50
                'Market_Breadth': [0.80, 0.55, 0.35][(i // 90) % 3],
                'Regime_Label': 'BULL' if (i // 150) % 2 == 0 else 'BEAR',
                'VIX_Spike': (i % 220 == 0),
                'Systemic_Panic': False,
                'Target_ATR': max(0.01, px * 0.02 * (1 + RNG.normal(0, 0.2))),
                'RS_Percentile': RNG.uniform(0, 100),
                'ATR_Contraction_Ratio': RNG.uniform(0.3, 1.2),
                'BB_Enter_Today': bool(RNG.random() < 0.02),
                'BB_Exhaustion_Today': bool(RNG.random() < 0.02),
                'MR_Base_Signal': bool(RNG.random() < 0.02),
            })
    d = pd.DataFrame(rows)
    d['SMA_5'] = d.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.rolling(5).mean())
    d = d.dropna(subset=['SMA_5'])
    daily = {}
    for r in d.to_dict('records'):
        daily.setdefault(r['DATE'], []).append(r)
    return daily, sorted(daily.keys())


daily, cal = make_panel()
n_rows = sum(len(v) for v in daily.values())
print(f"  Panel: {n_rows:,} rows over {len(cal):,} sessions")

eng_sim, _ = load_engine()
out_eng = eng_sim(PARAMS, daily, cal)
out_glp = glp.run_headless_simulation(PARAMS, daily, cal)

LABELS = ['equity_curve', 'wins', 'losses', 'gross_profits', 'gross_losses',
          'bb_trades', 'mr_trades']
check(len(out_eng) == len(out_glp) == 7, f"both return 7-tuples "
      f"(engine {len(out_eng)}, live_params {len(out_glp)})")

for i, lab in enumerate(LABELS):
    a, b = out_eng[i], out_glp[i]
    if lab == 'equity_curve':
        same = len(a) == len(b) and np.allclose(a, b, rtol=0, atol=0)
        check(same, f"{lab:<14} identical ({len(a)} points, "
                    f"final {a[-1]:,.4f} vs {b[-1]:,.4f})")
        if not same and len(a) == len(b):
            d = np.abs(np.array(a) - np.array(b))
            print(f"       first divergence at index {int(np.argmax(d > 0))}, "
                  f"max abs diff {d.max():.6f}")
    else:
        check(a == b, f"{lab:<14} identical ({a!r} vs {b!r})")
print(f"\n  Trades simulated: {out_eng[1] + out_eng[2]} closed "
      f"({out_eng[5]} Sniper, {out_eng[6]} MR)")
check(out_eng[1] + out_eng[2] > 30,
      "panel produced enough closed trades for this to be a real comparison")
print()


# ======================================================================
print("=" * 74)
print("TEST 3 -- both calculate_fitness copies, same curves")
print("=" * 74)
eng_fit, _ = load_function('calculate_fitness')


def curve(true_cagr, n_years, vol=0.0, seed=0):
    n = int(252 * n_years)
    eq = 100.0 * ((1 + true_cagr) ** n_years) ** np.linspace(0, 1, n)
    if vol:
        r = np.random.default_rng(seed)
        w = r.normal(0, vol, n)
        w -= w.mean()
        eq = eq * np.exp(np.cumsum(w) - np.linspace(0, np.cumsum(w)[-1], n))
        eq[0], eq[-1] = 100.0, 100.0 * (1 + true_cagr) ** n_years
    return list(eq)


CASES = [
    ('flat 1y',            curve(0.00, 1),                  60, 40, 200.0, 100.0),
    ('14.17% 1y',          curve(0.1417, 1),                60, 40, 200.0, 100.0),
    ('30% 3y noisy',       curve(0.30, 3, vol=0.004, seed=1), 90, 60, 400.0, 150.0),
    ('-20% 2y',            curve(-0.20, 2),                 20, 80, 50.0, 300.0),
    ('few trades',         curve(0.10, 1),                   5, 3, 20.0, 10.0),
    ('no losses',          curve(0.10, 1),                  40, 0, 200.0, 0.0),
    ('too short (<20)',    [100.0] * 10,                     5, 5, 10.0, 10.0),
    ('empty',              [],                               0, 0, 0.0, 0.0),
    # The two cases below are calibrated so that the TRUE sortino sits just
    # under the norm_sortino = min(s/3.0, 1.0) cap while the INFLATED sortino
    # clears it. That is the band where the units bug stops being a reporting
    # error and starts changing the fitness SCORE -- and therefore which
    # parameter set the random search returns. Outside this band the bug is
    # invisible to fitness: below it both values scale together, above it both
    # saturate at 1.0 and cancel. Verified empirically 2026-08-22:
    #   vol 0.006 -> sortino 2.854 true vs 4.273 inflated
    #   vol 0.008 -> sortino 2.134 true vs 3.195 inflated
    ('near cap (vol .006)', curve(0.15, 2, vol=0.006, seed=5), 70, 50, 300.0, 140.0),
    ('near cap (vol .008)', curve(0.15, 2, vol=0.008, seed=5), 70, 50, 300.0, 140.0),
]
FIT_LABELS = ['fitness', 'cagr', 'dd', 'sortino', 'pf']
for name, eq, w, l, gp, gl in CASES:
    a = eng_fit(eq, w, l, gp, gl)
    b = glp.calculate_fitness(eq, w, l, gp, gl)
    same = all(
        (x != x and y != y) or x == y or (isinstance(x, float) and abs(x - y) < 1e-12)
        for x, y in zip(a, b))
    check(same and len(a) == len(b), f"{name:<18} "
          + "  ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                      for k, v in zip(FIT_LABELS, a)))
    if not same:
        for k, x, y in zip(FIT_LABELS, a, b):
            if not ((x != x and y != y) or x == y):
                print(f"       {k}: engine={x!r}  live_params={y!r}")
print()


# ======================================================================
print("=" * 74)
print("TEST 4 -- does this test have teeth? (re-introduce the bug)")
print("=" * 74)
print("  Re-running the Test 3 cases with the ORIGINAL buggy exponent in place of")
print("  the live_params copy, to confirm the comparison above would have caught")
print("  finding #34 rather than passing vacuously.\n")


def buggy_fitness(eq_curve, wins, losses, gross_profits, gross_losses):
    """calculate_fitness exactly as generate_live_params.py had it before the
    --live-params patch: annualizing TRADING days on a 365.25-day year."""
    if not eq_curve or len(eq_curve) < 20:
        return -float('inf'), 0, 0, 0, 0
    eq = pd.Series(eq_curve)
    pct = eq.pct_change().dropna()
    days = len(eq_curve)
    cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (365.25 / days) - 1) * 100
    dd = ((eq - eq.cummax()) / eq.cummax()).min() * 100
    dstd = pct[pct < 0].std() * np.sqrt(252)
    sortino = (cagr / 100) / dstd if dstd > 0 else 0
    tt = wins + losses
    wr = (wins / tt) * 100 if tt > 0 else 0
    pf = gross_profits / gross_losses if gross_losses > 0 else 0
    score = (min(sortino / 3.0, 1.0) * glp.W_SORTINO + min(pf / 2.5, 1.0) * glp.W_PF
             + (wr / 100) * glp.W_WINRATE + min(tt / 100.0, 1.0) * glp.W_TRADES)
    if tt < 30:
        score -= 2.0
    if dd < -20:
        score -= 3.0
    elif dd < -15:
        score -= 1.0
    return score, cagr, dd, sortino, pf


caught = 0
fitness_diverged = 0
for name, eq, w, l, gp, gl in CASES:
    a = eng_fit(eq, w, l, gp, gl)
    bad = buggy_fitness(eq, w, l, gp, gl)
    differs = any(not ((x != x and y != y) or x == y or
                       (isinstance(x, float) and abs(x - y) < 1e-12))
                  for x, y in zip(a, bad))
    fit_differs = abs(a[0] - bad[0]) > 1e-9 if a[0] == a[0] and bad[0] == bad[0] else False
    if differs:
        caught += 1
        if fit_differs:
            fitness_diverged += 1
        mark = '  <-- FITNESS differs' if fit_differs else ''
        print(f"  caught {name:<20} cagr {bad[1]:8.2f}% (buggy) vs {a[1]:8.2f}% (engine)"
              f"   fitness {bad[0]:+.4f} vs {a[0]:+.4f}{mark}")
check(caught >= 4, f"the buggy copy is detected on {caught} of {len(CASES)} cases")
check(fitness_diverged >= 1,
      f"on {fitness_diverged} case(s) the FITNESS SCORE itself differs, not just "
      f"the reported CAGR")
print("\n  Note the split. On most curves only the reported CAGR moves: sortino")
print("  either scales with it below the min(s/3.0, 1.0) cap or saturates above it,")
print("  and fitness comes out the same. The cases flagged FITNESS differs are the")
print("  ones where the true sortino sits under the cap and the inflated one clears")
print("  it -- there the bug changes the SCORE, so the random search can return a")
print("  different parameter set. That band is narrow but it is not empty, which is")
print("  why this is a selection bug and not merely a reporting one.")
print()


# ======================================================================
print("=" * 74)
if failures:
    print(f"FAILED -- {len(failures)} check(s):")
    for f in failures:
        print("  - " + f)
    print("=" * 74)
    sys.exit(1)
print("ALL PARITY CHECKS PASSED")
print("  The two copies of run_headless_simulation and calculate_fitness are")
print("  behaviourally identical on this panel, and the shared constants agree.")
print("=" * 74)
