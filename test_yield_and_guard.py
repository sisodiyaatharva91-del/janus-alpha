"""
test_yield_and_guard.py
-----------------------
Behavioural tests for two coupled fixes:

  * IDLE YIELD (finding #29 + the units bug). The backtest divided an annual
    rate by 365 but accrued it once per TRADING day, ~252 times a year, so the
    stated 6% actually delivered 4.23%. Live credited nothing at all. Both are
    now 4.0% on a 252-day basis.

  * DUPLICATE-RUN GUARD (finding #33). state['last_run_date'] was written every
    run and never read. Once yield exists in live, a duplicate run accrues it
    twice -- which is why the guard had to land alongside the yield change
    rather than after it.

WHAT "4%" MEANS HERE, PRECISELY
    4.0 is a NOMINAL annual rate compounded once per trading session, so the
    effective annual figure is (1 + 0.04/252)**252 - 1, which is slightly above
    4%. This test prints the exact number rather than asserting a round 4.00%,
    because the honest statement is "4% nominal, ~4.08% effective", not "4%".

RUN (against a tree with apply_fixes_v2.py --idle-yield --run-guard applied)
    python test_yield_and_guard.py
    python test_yield_and_guard.py --dir /path/to/janus-alpha
"""

import argparse
import json
import os
import sys
import tempfile
import types

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument('--dir', default='.')
args = ap.parse_args()
ROOT = os.path.abspath(args.dir)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# live_pipeline imports yfinance/requests at module scope for the data-fetch
# half of the file. Nothing under test here touches the network.
for name in ('yfinance', 'requests', 'gspread'):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)

import live_pipeline as lp

for fn in ('accrue_idle_yield', 'trading_days_since', 'is_new_trading_date'):
    assert hasattr(lp, fn), (
        f"live_pipeline.py has no {fn} -- run: "
        f"python apply_fixes_v2.py --idle-yield --run-guard")

failures = []


def check(cond, label, detail=''):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(f"{label}  {detail}")


def fresh_state(cash=1_000_000.0, last_run=''):
    return {'bb_cash': cash / 2, 'bb_equity': cash / 2,
            'mr_cash': cash / 2, 'mr_equity': cash / 2,
            'active_bb': {}, 'active_mr': {},
            'last_run_date': last_run,
            'closed_trades_log': [], 'equity_curve_log': []}


SESSIONS = pd.bdate_range('2026-07-01', periods=60)
WINDOW = pd.DataFrame({'DATE': SESSIONS.repeat(3),
                       'SYMBOL': ['A', 'B', 'C'] * len(SESSIONS)})


print("=" * 70)
print("1. the units bug, in numbers")
print("=" * 70)

old_rate = (6.0 / 100) / 365          # what the engine used to do
new_rate = (lp.IDLE_YIELD_PCT / 100) / lp.TRADING_DAYS_PER_YEAR
old_eff = ((1 + old_rate) ** 252 - 1) * 100
new_eff = ((1 + new_rate) ** 252 - 1) * 100

print(f"        old: 6.0%/365, accrued 252x  -> {old_eff:.4f}% effective/yr")
print(f"        new: {lp.IDLE_YIELD_PCT}%/{lp.TRADING_DAYS_PER_YEAR}, accrued 252x -> {new_eff:.4f}% effective/yr")
print(f"        delta on the headline: {new_eff - old_eff:+.4f} pp/yr")

check(4.20 < old_eff < 4.25,
      "the OLD 6% setting really delivered ~4.23%/yr, not 6%", f"({old_eff:.4f}%)")
check(4.05 < new_eff < 4.10,
      "the NEW 4% setting delivers ~4.08%/yr (4% nominal, compounded per session)",
      f"({new_eff:.4f}%)")
check(abs(new_eff - old_eff) < 0.20,
      "so switching 6->4 with the units fix barely moves the headline",
      f"({new_eff - old_eff:+.4f} pp)")
check(lp.IDLE_YIELD_PCT == 4.0 and lp.TRADING_DAYS_PER_YEAR == 252,
      "live constants are 4.0 / 252")


print()
print("=" * 70)
print("2. trading_days_since counts SESSIONS, not calendar days")
print("=" * 70)

# Fri 2026-07-10 -> Mon 2026-07-13 is 3 calendar days but 1 session.
n = lp.trading_days_since(WINDOW, '2026-07-10', pd.Timestamp('2026-07-13'))
check(n == 1, "Fri->Mon is 1 trading session, not 3 calendar days", f"(got {n})")

n = lp.trading_days_since(WINDOW, '2026-07-01', pd.Timestamp('2026-07-08'))
check(n == 5, "2026-07-01 -> 2026-07-08 is 5 sessions", f"(got {n})")

n = lp.trading_days_since(WINDOW, '', pd.Timestamp('2026-07-08'))
check(n == 1, "empty last_run_date credits exactly 1 session (fresh/reset state)", f"(got {n})")

n = lp.trading_days_since(WINDOW, '2026-07-08', pd.Timestamp('2026-07-08'))
check(n == 0, "same date is 0 new sessions", f"(got {n})")

n = lp.trading_days_since(WINDOW, 'not-a-date', pd.Timestamp('2026-07-08'))
check(n == 1, "unparseable date falls back to 1 session with a warning", f"(got {n})")

# A date absent from the panel (an NSE holiday) must not be counted.
n_hol = lp.trading_days_since(WINDOW, '2026-07-03', pd.Timestamp('2026-07-06'))
check(n_hol == 1, "a weekend between two sessions counts as 1, from the panel itself",
      f"(got {n_hol})")


print()
print("=" * 70)
print("3. accrue_idle_yield")
print("=" * 70)

st = fresh_state(1_000_000.0, last_run='2026-07-07')
before_bb, before_mr = st['bb_cash'], st['mr_cash']
total = lp.accrue_idle_yield(st, WINDOW, pd.Timestamp('2026-07-08'))
one_day = 500_000.0 * new_rate
check(abs(st['bb_cash'] - (before_bb + one_day)) < 1e-6,
      "one session credits cash x daily rate to the Sniper sleeve")
check(abs(st['mr_cash'] - (before_mr + one_day)) < 1e-6,
      "and the same to the MR sleeve")
check(abs(st['bb_equity'] - (500_000.0 + one_day)) < 1e-6,
      "equity moves with cash (yield is real P&L, not just a cash reshuffle)")
check(abs(total - 2 * one_day) < 1e-6, "returned total matches the sum of both sleeves")

# --- catch-up must compound, because the engine's cash compounds too -------
st_catch = fresh_state(1_000_000.0, last_run='2026-07-01')
lp.accrue_idle_yield(st_catch, WINDOW, pd.Timestamp('2026-07-08'))   # 5 sessions

st_daily = fresh_state(1_000_000.0, last_run='')
for d in ['2026-07-02', '2026-07-03', '2026-07-06', '2026-07-07', '2026-07-08']:
    st_daily['last_run_date'] = pd.Timestamp(d) - pd.Timedelta(days=1)
    # force exactly one session per call
    lp.accrue_idle_yield(st_daily, WINDOW, pd.Timestamp(d))

check(abs(st_catch['bb_cash'] - st_daily['bb_cash']) < 1e-6,
      "a 5-session catch-up == 5 separate 1-session accruals",
      f"(catchup={st_catch['bb_cash']:.6f} daily={st_daily['bb_cash']:.6f})")

simple = 500_000.0 * (5 * new_rate)
compound = 500_000.0 * ((1 + new_rate) ** 5 - 1)
check(compound > simple,
      "and compounding is not the same as n x r (so the formula choice is real)",
      f"(compound={compound:.6f} simple={simple:.6f})")

# --- degenerate inputs ----------------------------------------------------
st_zero = fresh_state(0.0, last_run='2026-07-07')
lp.accrue_idle_yield(st_zero, WINDOW, pd.Timestamp('2026-07-08'))
check(st_zero['bb_cash'] == 0.0, "zero cash accrues zero")

st_neg = fresh_state(1_000_000.0, last_run='2026-07-07')
st_neg['bb_cash'] = -5_000.0          # over-allocated sleeve
st_neg['bb_equity'] = 495_000.0
lp.accrue_idle_yield(st_neg, WINDOW, pd.Timestamp('2026-07-08'))
check(st_neg['bb_cash'] == -5_000.0,
      "NEGATIVE cash accrues zero, not negative yield (max(0.0, cash))",
      f"(got {st_neg['bb_cash']})")

st_same = fresh_state(1_000_000.0, last_run='2026-07-08')
got = lp.accrue_idle_yield(st_same, WINDOW, pd.Timestamp('2026-07-08'))
check(got == 0.0 and st_same['bb_cash'] == 500_000.0,
      "0 new sessions accrues nothing (belt-and-braces behind the run guard)")

st_stale = fresh_state(1_000_000.0, last_run='2020-01-01')
lp.accrue_idle_yield(st_stale, WINDOW, pd.Timestamp('2026-07-08'))
n_from_window = lp.trading_days_since(WINDOW, '2020-01-01', pd.Timestamp('2026-07-08'))
natural = 500_000.0 * ((1 + new_rate) ** n_from_window - 1)
check(abs(st_stale['bb_cash'] - (500_000.0 + natural)) < 1e-6,
      "a state file predating the panel is bounded by the PANEL, not by the calendar "
      f"({n_from_window} sessions, not ~1600)")
check(n_from_window <= len(SESSIONS),
      "so the rolling data window is itself the first line of defence against "
      "a stale state file")

# The MAX_YIELD_CATCHUP_DAYS cap is the second line of defence, for when the
# window is long enough to exceed it. Needs a panel longer than the cap to
# exercise at all -- with a 60-session window above it can never fire, which is
# exactly why the first check could not test it.
LONG_SESSIONS = pd.bdate_range('2025-01-01', periods=400)
LONG_WINDOW = pd.DataFrame({'DATE': LONG_SESSIONS})
st_cap = fresh_state(1_000_000.0, last_run='2025-01-02')
lp.accrue_idle_yield(st_cap, LONG_WINDOW, pd.Timestamp('2026-06-30'))
capped = 500_000.0 * ((1 + new_rate) ** lp.MAX_YIELD_CATCHUP_DAYS - 1)
uncapped_n = lp.trading_days_since(LONG_WINDOW, '2025-01-02', pd.Timestamp('2026-06-30'))
check(abs(st_cap['bb_cash'] - (500_000.0 + capped)) < 1e-6,
      f"with a {len(LONG_SESSIONS)}-session panel, a {uncapped_n}-session gap is "
      f"capped at MAX_YIELD_CATCHUP_DAYS={lp.MAX_YIELD_CATCHUP_DAYS}")


print()
print("=" * 70)
print("4. duplicate-run guard")
print("=" * 70)

tmp = tempfile.mkdtemp(prefix='janus_guard_')
os.makedirs(os.path.join(tmp, 'state'), exist_ok=True)
lp.STATE_PATH = os.path.join(tmp, 'state', 'paper_portfolio_state.json')


def write_state(last_run):
    with open(lp.STATE_PATH, 'w') as f:
        json.dump(fresh_state(1_000_000.0, last_run), f)


write_state('2026-07-07')
check(lp.is_new_trading_date(pd.Timestamp('2026-07-08')) is True,
      "a genuinely newer session is allowed through")
check(lp.is_new_trading_date(pd.Timestamp('2026-07-07')) is False,
      "the SAME session is blocked (the NSE-holiday case)")
check(lp.is_new_trading_date(pd.Timestamp('2026-07-06')) is False,
      "an OLDER session is blocked too")

write_state('')
check(lp.is_new_trading_date(pd.Timestamp('2026-07-08')) is True,
      "a freshly reset state file is allowed through")

write_state('2026-07-07')
os.environ['JANUS_FORCE_RERUN'] = '1'
check(lp.is_new_trading_date(pd.Timestamp('2026-07-07')) is True,
      "JANUS_FORCE_RERUN=1 overrides the guard")
del os.environ['JANUS_FORCE_RERUN']

# --- fails OPEN, not closed ----------------------------------------------
missing = os.path.join(tmp, 'state', 'does_not_exist.json')
saved, lp.STATE_PATH = lp.STATE_PATH, missing
check(lp.is_new_trading_date(pd.Timestamp('2026-07-08')) is True,
      "an unreadable state file FAILS OPEN (a silent permanent halt is worse)")
lp.STATE_PATH = saved

with open(lp.STATE_PATH, 'w') as f:
    json.dump({'last_run_date': 'garbage-not-a-date'}, f)
check(lp.is_new_trading_date(pd.Timestamp('2026-07-08')) is True,
      "an unparseable last_run_date FAILS OPEN with a warning")


print()
print("=" * 70)
print("5. the interaction: the guard is what stops yield double-accruing")
print("=" * 70)

write_state('2026-07-08')
st_dup = fresh_state(1_000_000.0, last_run='2026-07-08')
allowed = lp.is_new_trading_date(pd.Timestamp('2026-07-08'))
if not allowed:
    pass          # main() returns here; no accrual, no ageing, no equity row
else:
    lp.accrue_idle_yield(st_dup, WINDOW, pd.Timestamp('2026-07-08'))
check(allowed is False and st_dup['bb_cash'] == 500_000.0,
      "a same-date re-run credits no yield because the guard returns first")

# And show the counterfactual the guard prevents.
st_unguarded = fresh_state(1_000_000.0, last_run='2026-07-07')
lp.accrue_idle_yield(st_unguarded, WINDOW, pd.Timestamp('2026-07-08'))
first = st_unguarded['bb_cash']
st_unguarded['last_run_date'] = '2026-07-07'     # what an unguarded re-run looks like
lp.accrue_idle_yield(st_unguarded, WINDOW, pd.Timestamp('2026-07-08'))
check(st_unguarded['bb_cash'] > first,
      "without the guard, re-running the same date WOULD accrue twice",
      f"({first:.4f} -> {st_unguarded['bb_cash']:.4f})")


print()
print("=" * 70)
if failures:
    print(f"FAILED ({len(failures)})")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"PASSED: yield is {new_eff:.4f}% effective/yr on a {lp.TRADING_DAYS_PER_YEAR}-session")
print("basis, catch-up compounds correctly, and the guard blocks duplicate sessions.")
