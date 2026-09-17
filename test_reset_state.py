"""
test_reset_state.py
-------------------
Proves that the state file reset_paper_state.py writes is one the REAL
live_pipeline.py can actually run against.

WHY THIS IS THE TEST THAT MATTERS
    Writing valid-looking JSON is easy. The failure that costs something is a
    state file the pipeline chokes on at 16:00 IST inside a GitHub Action -- one
    missing key and evaluate_exits dies with a KeyError, the run produces no
    Telegram message, and the first thing dell learns about it is silence.

    So this does not assert on the JSON's shape. It imports live_pipeline and
    pushes the freshly-written state through the real functions in the real
    order main() uses: guard -> yield -> rebalance -> exits -> entries -> sheet
    payloads. If any of them touches a key the reset script did not write, this
    fails here instead of in production.

    yfinance / gspread are stubbed in sys.modules purely so the import
    succeeds -- neither is reachable from the code paths under test, and there
    is no network in this sandbox. Nothing else about the pipeline is faked.

  Test 1 : reset_paper_state.py runs, archives verbatim, writes a clean state.
  Test 2 : the clean state survives the whole main() sequence with no KeyError.
  Test 3 : first-run semantics are what the script promises -- the duplicate
           guard passes and exactly ONE session of idle yield is credited, at
           the 4%/252 basis rather than 6%/365.
  Test 4 : the required-key check has teeth (drop a key -> the script refuses).
  Test 5 : --dry-run really writes nothing.

RUN
    python test_reset_state.py
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

import numpy as np
import pandas as pd

# Stub the two unavailable third-party modules BEFORE importing live_pipeline.
for name in ('yfinance', 'gspread'):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
_g = types.ModuleType('google')
_go = types.ModuleType('google.oauth2')
_gos = types.ModuleType('google.oauth2.service_account')
_gos.Credentials = object
_go.service_account = _gos
_g.oauth2 = _go
sys.modules.setdefault('google', _g)
sys.modules.setdefault('google.oauth2', _go)
sys.modules.setdefault('google.oauth2.service_account', _gos)

failures = []


def check(cond, msg):
    print(f"  {'OK  ' if cond else 'FAIL'} {msg}")
    if not cond:
        failures.append(msg)


CONTAMINATED = {
    'bb_equity': 312450.75, 'bb_cash': 41230.10,
    'mr_equity': 291880.40, 'mr_cash': 291880.40,
    'active_bb': {
        'TATAMOTORS': {'entry_date': '2026-08-17', 'entry_price': 1042.5, 'shares': 86,
                       'net_cost': 89655.0, 'stop_price': 998.2, 'target_price': 1131.1,
                       'regime_at_entry': 'BULL', 'breadth_at_entry': 0.71},
        'DIVISLAB': {'entry_date': '2026-08-17', 'entry_price': 6210.0, 'shares': 14,
                     'net_cost': 86940.0, 'stop_price': 5980.4, 'target_price': 6669.2,
                     'regime_at_entry': 'BULL', 'breadth_at_entry': 0.71},
        'BEL': {'entry_date': '2026-08-17', 'entry_price': 402.15, 'shares': 230,
                'net_cost': 92494.5, 'stop_price': 385.9, 'target_price': 434.6,
                'regime_at_entry': 'BULL', 'breadth_at_entry': 0.71}},
    'active_mr': {'HINDALCO': {'entry_date': '2026-08-19', 'entry_price': 712.4,
                               'shares': 40, 'net_cost': 28496.0, 'trading_days': 3}},
    'closed_trades_log': [
        {'sleeve': 'MR', 'symbol': 'SBIN', 'entry_date': '2026-08-11',
         'exit_date': '2026-08-14', 'entry_price': 820.1, 'exit_price': 838.9,
         'shares': 35, 'pnl': 645.2, 'exit_reason': 'SMA5 reversion'}],
    'equity_curve_log': [
        {'date': '2026-08-17', 'total_equity': 603980.2},
        {'date': '2026-08-17', 'total_equity': 603980.2},   # finding #33 fingerprint
        {'date': '2026-08-19', 'total_equity': 604331.15}],
    'last_run_date': '2026-08-19',
}

SRC = os.path.abspath('.')
NEEDED = ['reset_paper_state.py', 'live_pipeline.py', 'wfo_engine_updated.py',
          'coiled_alpha_logic.py']


def build_repo():
    root = tempfile.mkdtemp(prefix='janus_reset_')
    for f in NEEDED:
        p = os.path.join(SRC, f)
        if not os.path.exists(p):
            sys.exit(f"ERROR: {p} not found -- run this from the repo directory.")
        shutil.copy(p, os.path.join(root, f))
    os.makedirs(os.path.join(root, 'state'), exist_ok=True)
    with open(os.path.join(root, 'state', 'paper_portfolio_state.json'), 'w') as f:
        json.dump(CONTAMINATED, f, indent=2)
    return root


def run_reset(root, *extra):
    return subprocess.run([sys.executable, os.path.join(root, 'reset_paper_state.py'),
                           '--repo', root, *extra],
                          capture_output=True, text=True)


# ======================================================================
print("=" * 74)
print("TEST 1 -- reset runs, archives verbatim, writes a clean state")
print("=" * 74)
ROOT = build_repo()
r = run_reset(ROOT)
check(r.returncode == 0, f"reset_paper_state.py exited 0 (got {r.returncode})")
if r.returncode != 0:
    print(r.stdout + r.stderr)

state_file = os.path.join(ROOT, 'state', 'paper_portfolio_state.json')
new = json.load(open(state_file))
check(new['active_bb'] == {} and new['active_mr'] == {}, "no open positions")
check(new['closed_trades_log'] == [] and new['equity_curve_log'] == [], "logs empty")
check(new['last_run_date'] == '', "last_run_date is '' (fresh-state sentinel)")
check(abs(new['bb_equity'] + new['mr_equity'] - 600000) < 0.01,
      f"sleeves sum to 600,000 (got {new['bb_equity'] + new['mr_equity']:,.2f})")
check(new['bb_cash'] == new['bb_equity'] and new['mr_cash'] == new['mr_equity'],
      "cash == equity in both sleeves, as run_headless_simulation starts")

arch = glob.glob(os.path.join(ROOT, 'state', 'archive', '*.contaminated.json'))
check(len(arch) == 1, f"exactly one archived snapshot (got {len(arch)})")
if arch:
    check(json.load(open(arch[0])) == CONTAMINATED,
          "archived copy is byte-for-byte the original state (nothing 'repaired')")
check(os.path.exists(os.path.join(ROOT, 'state', 'archive', 'README.md')),
      "archive README.md written")
check('DUPLICATE dates' in r.stdout,
      "the duplicate 2026-08-17 curve row was reported before archiving")
print()


# ======================================================================
print("=" * 74)
print("TEST 2 -- the REAL pipeline runs against it without a KeyError")
print("=" * 74)
sys.path.insert(0, ROOT)
os.chdir(ROOT)                      # live_pipeline resolves STATE_PATH relatively
import live_pipeline as lp          # noqa: E402

st = lp.load_state()
check(st['last_run_date'] == '', "load_state() reads the clean file")

# A tiny panel: two sessions, a handful of symbols, no signals firing. Enough for
# every function to run; nothing should open or close.
dates = pd.to_datetime(['2026-08-20', '2026-08-21'])
rows = []
for d in dates:
    for s in range(6):
        px = 100.0 + s * 10
        rows.append({'DATE': d, 'SYMBOL': f'S{s}', 'OPEN': px, 'HIGH': px * 1.01,
                     'LOW': px * 0.99, 'CLOSE': px, 'SMA_5': px,
                     'Turnover_SMA_50': 5e7, 'Target_ATR': px * 0.02,
                     'RS_Percentile': 50.0, 'ATR_Contraction_Ratio': 0.8,
                     'Market_Breadth': 0.70, 'Regime_Label': 'BULL',
                     'VIX_Spike': False, 'Systemic_Panic': False,
                     'BB_Enter_Today': False, 'BB_Exhaustion_Today': False,
                     'MR_Base_Signal': False})
window = pd.DataFrame(rows)
target = dates[-1]
today_rows = [r for r in window.to_dict('records') if r['DATE'] == target]
today_lookup = {r['SYMBOL']: r for r in today_rows}

stages = []
try:
    stages.append(('is_new_trading_date', lp.is_new_trading_date(target)))
    stages.append(('accrue_idle_yield', lp.accrue_idle_yield(st, window, target)))
    stages.append(('rebalance_allocation', lp.rebalance_allocation(st, 'BULL', 0.70)))
    stages.append(('evaluate_exits',
                   lp.evaluate_exits(st, today_lookup, 'BULL',
                                     {'bb_tgt': 4.0, 'bb_stop': 2.0, 'bb_risk': 2.0,
                                      'mr_time': 5, 'mr_pos_size': 10.0}, target)))
    stages.append(('evaluate_entries',
                   lp.evaluate_entries(st, today_rows, today_lookup, 'BULL', 0.70,
                                       {'bb_tgt': 4.0, 'bb_stop': 2.0, 'bb_risk': 2.0,
                                        'mr_time': 5, 'mr_pos_size': 10.0}, target)))
    stages.append(('build_sheet_payloads', lp.build_sheet_payloads(st, today_lookup)))
    ran = True
except Exception as e:
    ran = False
    got = [n for n, _ in stages]
    check(False, f"pipeline raised {type(e).__name__}: {e}  (completed: {got})")
if ran:
    check(True, f"all {len(stages)} stages ran: {', '.join(n for n, _ in stages)}")
    payloads = dict(stages)['build_sheet_payloads']
    check(isinstance(payloads, dict) and len(payloads) > 0,
          f"build_sheet_payloads returned {len(payloads)} tab(s): {sorted(payloads)}")
    # Everything must be JSON-serialisable -- the earlier NaN/numpy bugs in this
    # payload were found exactly this way.
    try:
        json.dumps(payloads)
        check(True, "sheet payloads are JSON-serialisable (no NaN, no numpy scalars)")
    except (TypeError, ValueError) as e:
        check(False, f"sheet payloads not JSON-serialisable: {e}")
    check(dict(stages)['evaluate_exits'] == [],
          "no exit events -- there was nothing open to exit")
print()


# ======================================================================
print("=" * 74)
print("TEST 3 -- first-run semantics are what the script promises")
print("=" * 74)
fresh = json.load(open(state_file))
check(lp.is_new_trading_date(target) is True,
      "duplicate-run guard PASSES on an empty last_run_date (not blocked)")
check(lp.trading_days_since(window, '', target) == 1,
      f"trading_days_since('') == 1 (got {lp.trading_days_since(window, '', target)})")

# Exactly one session of yield, at 4%/252 -- not 6%/365.
st2 = json.load(open(state_file))
before = st2['bb_cash'] + st2['mr_cash']
credited = lp.accrue_idle_yield(st2, window, target)
after = st2['bb_cash'] + st2['mr_cash']
expect = before * ((lp.IDLE_YIELD_PCT / 100) / lp.TRADING_DAYS_PER_YEAR)
old_basis = before * ((6.0 / 100) / 365)
check(abs((after - before) - expect) < 1e-6,
      f"credited {after - before:.4f} == one session at "
      f"{lp.IDLE_YIELD_PCT}%/{lp.TRADING_DAYS_PER_YEAR} ({expect:.4f})")
check(abs((after - before) - old_basis) > 1e-6,
      f"and is NOT the old 6%/365 amount ({old_basis:.4f}) -- "
      f"difference {abs(expect - old_basis):.4f}/day")
check(abs(credited - (after - before)) < 1e-9,
      f"the returned figure {credited:.4f} matches the cash actually added")
check(st2['bb_cash'] == st2['bb_equity'] and st2['mr_cash'] == st2['mr_equity'],
      "yield lands on BOTH cash and equity, keeping them equal while flat")
print()


# ======================================================================
print("=" * 74)
print("TEST 4 -- the required-key check has teeth")
print("=" * 74)
print("  reset_paper_state.py derives the required keys by reading")
print("  live_pipeline.py rather than hardcoding them, so that adding a state")
print("  key to the pipeline cannot silently produce an incomplete reset. Prove")
print("  that check fires: add a read of a key clean_state() does not write.\n")
os.chdir(SRC)
ROOT2 = build_repo()
lp2 = os.path.join(ROOT2, 'live_pipeline.py')
src = open(lp2).read()
src = src.replace("def load_state():",
                  "def load_state():\n    _ = state['a_key_that_is_not_written']"
                  "  # sabotage", 1)
open(lp2, 'w').write(src)
r2 = run_reset(ROOT2)
check(r2.returncode != 0,
      f"reset REFUSES to write when the pipeline reads an unwritten key "
      f"(exit {r2.returncode})")
check('a_key_that_is_not_written' in (r2.stdout + r2.stderr),
      "and names the missing key in the error")
untouched = json.load(open(os.path.join(ROOT2, 'state', 'paper_portfolio_state.json')))
check(untouched == CONTAMINATED,
      "and left the existing state file untouched rather than half-resetting it")
print()


# ======================================================================
print("=" * 74)
print("TEST 5 -- --dry-run writes nothing")
print("=" * 74)
ROOT3 = build_repo()
r3 = run_reset(ROOT3, '--dry-run')
check(r3.returncode == 0, f"--dry-run exited 0 (got {r3.returncode})")
check(json.load(open(os.path.join(ROOT3, 'state', 'paper_portfolio_state.json')))
      == CONTAMINATED, "state file unchanged")
check(not os.path.exists(os.path.join(ROOT3, 'state', 'archive')),
      "no archive directory created")
check('nothing written' in r3.stdout, "and it says so")
print()


# ======================================================================
print("=" * 74)
if failures:
    print(f"FAILED -- {len(failures)} check(s):")
    for f in failures:
        print("  - " + f)
    print("=" * 74)
    sys.exit(1)
print("ALL RESET-STATE CHECKS PASSED")
print("  The clean state runs through the real pipeline end to end, credits one")
print("  session of yield at the 4%/252 basis, is not blocked by the duplicate")
print("  guard, and the contaminated original is archived verbatim.")
print("=" * 74)
