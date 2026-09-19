"""
test_sheets_payload.py
----------------------
Behavioural tests for the Google Sheets mirror.

The mirror had three problems before 2026-08-22:
  * closed_trades_log had been populated since day one and was written
    NOWHERE -- the entire trade history existed only inside the JSON state
    file, so there was no way to look at what the system had actually done.
  * Days_Held was written as '' for every Sniper row, because Sniper positions
    carry no day counter (only MR does).
  * worksheets were created at rows=100 / rows=20 and never resized, and
    ws.clear() does not resize either, so the log would silently truncate once
    it outgrew the grid.

build_sheet_payloads was split out of update_sheet_mirror as a PURE function
precisely so these can be tested with no gspread, no credentials and no
network. The formatting is where the bugs live; the API call is trivial.

THE FAILURE MODE THIS FILE CARES ABOUT MOST
    gspread serialises to JSON, and JSON has no NaN and no Infinity. A single
    NaN raises mid-write and takes the whole mirror down -- after some tabs
    have already been overwritten, so it fails dirty. Section 3 feeds a state
    full of NaN, inf, None and numpy scalars and asserts the payload survives
    json.dumps(..., allow_nan=False), which is the strict check that matches
    what gspread actually does.

RUN (against a tree with apply_fixes_v2.py --sheets applied)
    python test_sheets_payload.py
    python test_sheets_payload.py --dir /path/to/janus-alpha
"""

import argparse
import json
import os
import sys
import types

import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument('--dir', default='.')
args = ap.parse_args()
sys.path.insert(0, os.path.abspath(args.dir))
os.chdir(os.path.abspath(args.dir))

for name in ('yfinance', 'requests', 'gspread'):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)

import live_pipeline as lp

assert hasattr(lp, 'build_sheet_payloads'), \
    "live_pipeline.py has no build_sheet_payloads -- run: python apply_fixes_v2.py --sheets"

failures = []


def check(cond, label, detail=''):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(f"{label}  {detail}")


def col(rows, name):
    """Column index by header name."""
    return rows[0].index(name)


# --------------------------------------------------------------------------
STATE = {
    'bb_equity': 520_000.0, 'bb_cash': 300_000.0,
    'mr_equity': 495_000.0, 'mr_cash': 495_000.0,
    'last_run_date': '2026-08-21',
    'active_bb': {
        'TCS': {'shares': 100, 'entry_price': 3000.0, 'entry_date': '2026-08-17',
                'stop_price': 2900.0, 'target_price': 3200.0, 'net_cost': 300_000.0},
    },
    'active_mr': {
        'HDFCBANK': {'shares': 50, 'entry_price': 1600.0, 'entry_date': '2026-08-19',
                     'net_cost': 80_000.0, 'trading_days': 2},
    },
    'closed_trades_log': [
        {'sleeve': 'Sniper', 'symbol': 'INFY', 'entry_date': '2026-08-03',
         'exit_date': '2026-08-10', 'entry_price': 1500.0, 'exit_price': 1620.0,
         'shares': 100, 'pnl': 12_000.0, 'exit_reason': 'TARGET'},
        {'sleeve': 'MR', 'symbol': 'WIPRO', 'entry_date': '2026-08-11',
         'exit_date': '2026-08-14', 'entry_price': 500.0, 'exit_price': 480.0,
         'shares': 200, 'pnl': -4_000.0, 'exit_reason': 'TIME_STOP'},
        {'sleeve': 'Sniper', 'symbol': 'RELIANCE', 'entry_date': '2026-08-12',
         'exit_date': '2026-08-18', 'entry_price': 2800.0, 'exit_price': 2750.0,
         'shares': 50, 'pnl': -2_500.0, 'exit_reason': 'STOP'},
    ],
    'equity_curve_log': [{'date': d, 'total_equity': 1_000_000.0} for d in
                         ['2026-08-17', '2026-08-18', '2026-08-19',
                          '2026-08-20', '2026-08-21']],
}
LOOKUP = {'TCS': {'CLOSE': 3100.0}, 'HDFCBANK': {'CLOSE': 1650.0}}
CONTEXT = {'date': '2026-08-21', 'regime': 'BULL', 'breadth': 0.63, 'vix_spike': False}

p = lp.build_sheet_payloads(STATE, LOOKUP, CONTEXT)

print("=" * 70)
print("1. shape")
print("=" * 70)
check(set(p) == {'Open_Positions', 'Trade_Log', 'Equity_Summary'},
      "three tabs: Open_Positions, Trade_Log, Equity_Summary", f"(got {sorted(p)})")
for tab, rows in p.items():
    widths = {len(r) for r in rows}
    check(len(widths) == 1,
          f"{tab}: every row is the same width as the header", f"(widths={widths})")
check(len(p['Open_Positions']) == 3, "2 open positions + header")
check(len(p['Trade_Log']) == 4, "3 closed trades + header")


print()
print("=" * 70)
print("2. Open_Positions")
print("=" * 70)
op = p['Open_Positions']
tcs = op[1]
hdfc = op[2]
check(tcs[col(op, 'Sleeve')] == 'Sniper' and hdfc[col(op, 'Sleeve')] == 'MR',
      "Sniper rows first, then MR")

# Sessions_Held: equity_curve_log has 2026-08-17..21; TCS entered 08-17, so
# sessions strictly after entry = 18,19,20,21 = 4.
check(tcs[col(op, 'Sessions_Held')] == 4,
      "Sniper Sessions_Held is a real number, not the old blank ''",
      f"(got {tcs[col(op, 'Sessions_Held')]!r})")
check(hdfc[col(op, 'Sessions_Held')] == 2,
      "MR Sessions_Held == 2 (20th, 21st)", f"(got {hdfc[col(op, 'Sessions_Held')]!r})")
check(hdfc[col(op, 'Sessions_Held')] == STATE['active_mr']['HDFCBANK']['trading_days'],
      "and it agrees with MR's OWN trading_days counter -- the number its time "
      "stop fires on, so the sheet cannot disagree with the engine")

check(tcs[col(op, 'Market_Value')] == 310_000.0, "Market_Value = shares x last close")
check(tcs[col(op, 'Unrealized_PnL')] == 10_000.0, "Unrealized_PnL = MV - cost")
check(abs(tcs[col(op, 'Unrealized_Pct')] - 3.33) < 0.01, "Unrealized_Pct = PnL / cost")
check(abs(tcs[col(op, 'Pct_To_Stop')] - 6.45) < 0.01,
      "Pct_To_Stop = (last - stop)/last x 100", f"(got {tcs[col(op, 'Pct_To_Stop')]})")
check(abs(tcs[col(op, 'Pct_To_Target')] - 3.23) < 0.01,
      "Pct_To_Target = (target - last)/last x 100")
check(hdfc[col(op, 'Stop_Price')] == '' and hdfc[col(op, 'Pct_To_Stop')] == '',
      "MR carries no stop, so those cells are blank rather than 0 or NaN")


print()
print("=" * 70)
print("3. JSON-safety -- the gspread killer")
print("=" * 70)

dirty = json.loads(json.dumps(STATE))
dirty['active_bb']['NANCO'] = {'shares': float('nan'), 'entry_price': float('nan'),
                               'entry_date': '', 'stop_price': float('inf'),
                               'target_price': float('-inf'), 'net_cost': None}
dirty['active_mr']['NPCO'] = {'shares': None, 'entry_price': None, 'entry_date': None}
dirty['closED'] = None
dirty['closed_trades_log'].append(
    {'sleeve': 'MR', 'symbol': 'ZERO', 'entry_date': '2026-08-01',
     'exit_date': '2026-08-05', 'entry_price': 0.0, 'exit_price': 0.0,
     'shares': 0, 'pnl': float('nan'), 'exit_reason': 'WEIRD'})
dirty_lookup = dict(LOOKUP)
dirty_lookup['NANCO'] = {'CLOSE': float('nan')}
dirty_ctx = {'date': '2026-08-21', 'regime': 'BULL',
             'breadth': float('nan'), 'vix_spike': True}

dp = lp.build_sheet_payloads(dirty, dirty_lookup, dirty_ctx)


def bad_cells(payload):
    out = []
    for tab, rows in payload.items():
        for ri, row in enumerate(rows):
            for ci, v in enumerate(row):
                if isinstance(v, float) and (v != v or v in (float('inf'), float('-inf'))):
                    out.append((tab, ri, ci, v))
    return out


bad = bad_cells(dp)
check(not bad, "no NaN or Inf survives into any cell", f"({bad[:4]})")

try:
    json.dumps(dp, allow_nan=False)
    check(True, "the whole payload passes json.dumps(allow_nan=False), as gspread needs")
except (ValueError, TypeError) as e:
    check(False, "the whole payload passes json.dumps(allow_nan=False)", f"({e})")

# numpy scalars are the OTHER thing json refuses, and shares/prices can arrive
# as numpy types when they were derived from a DataFrame row rather than
# round-tripped through the JSON state file.
np_state = json.loads(json.dumps(STATE))
np_state['active_bb']['TCS']['shares'] = np.int64(100)
np_state['active_bb']['TCS']['entry_price'] = np.float64(3000.0)
np_state['closed_trades_log'][0]['shares'] = np.int64(100)
np_state['closed_trades_log'][0]['pnl'] = np.float64(12_000.0)
np_p = lp.build_sheet_payloads(np_state, {'TCS': {'CLOSE': np.float64(3100.0)}}, CONTEXT)
try:
    json.dumps(np_p, allow_nan=False)
    check(True, "numpy int64/float64 in the state also serialise cleanly")
except (ValueError, TypeError) as e:
    check(False, "numpy int64/float64 in the state also serialise cleanly",
          f"({type(e).__name__}: {e})")


print()
print("=" * 70)
print("4. Trade_Log ordering and Cum_PnL")
print("=" * 70)
tl = p['Trade_Log']
dates = [r[col(tl, 'Exit_Date')] for r in tl[1:]]
check(dates == sorted(dates, reverse=True),
      "displayed newest-first, so the useful end needs no scrolling", f"({dates})")

cum = [r[col(tl, 'Cum_PnL')] for r in tl[1:]]
# chronological order is reversed(display): INFY +12000, WIPRO -4000, RELIANCE -2500
check(cum == [5500.0, 8000.0, 12000.0],
      "Cum_PnL was accumulated CHRONOLOGICALLY, so each row shows the running "
      "total as of that trade even though display is reversed", f"({cum})")
check(cum[0] == sum(t['pnl'] for t in STATE['closed_trades_log']),
      "the topmost (newest) Cum_PnL equals total realized PnL", f"({cum[0]})")

infy = [r for r in tl[1:] if r[col(tl, 'Symbol')] == 'INFY'][0]
check(abs(infy[col(tl, 'Return_Pct')] - 8.0) < 0.01,
      "Return_Pct = pnl / (shares x entry_price) x 100", f"({infy[col(tl, 'Return_Pct')]})")

zero = [r for r in dp['Trade_Log'][1:] if r[col(dp['Trade_Log'], 'Symbol')] == 'ZERO']
check(len(zero) == 1 and zero[0][col(dp['Trade_Log'], 'Return_Pct')] == '',
      "a zero-cost-basis trade yields a blank Return_Pct, not a ZeroDivisionError")


print()
print("=" * 70)
print("5. Equity_Summary")
print("=" * 70)
es = {r[0]: r[1] for r in p['Equity_Summary']}
check(es['Total Equity'] == 1_015_000.0, "Total Equity = bb_equity + mr_equity")
check(es['Regime'] == 'BULL' and es['Market Breadth'] == 0.63,
      "regime and breadth come from the caller's context, not from the state file")
check(es['Vol Spike (Nifty ATR proxy)'] == 'False',
      "the vol-spike row is labelled as the ATR proxy it is, not 'VIX'")
check(es['Closed Trades'] == 3, "Closed Trades counts the log")
check(es['Realized PnL'] == 5_500.0, "Realized PnL = 12000 - 4000 - 2500")
check(abs(es['Win Rate %'] - 33.33) < 0.01, "Win Rate % = 1 of 3")
check(abs(es['Profit Factor'] - 1.85) < 0.01,
      "Profit Factor = 12000 / 6500", f"({es['Profit Factor']})")
# Sniper risk: (3100 - 2900) x 100 = 20000. MR contributes nothing (no stop).
check(es['Sniper Risk to Stops'] == 20_000.0,
      "Sniper Risk to Stops = (last - stop) x shares, MR excluded")
check(es['Open Positions'] == 2, "Open Positions counts both sleeves")


print()
print("=" * 70)
print("6. degenerate states")
print("=" * 70)
empty = lp.build_sheet_payloads({}, {}, {})
# Open_Positions and Trade_Log are variable-length lists, so an empty state
# means header-only. Equity_Summary is a FIXED-SHAPE metrics tab -- it always
# has the same rows, just with blank values -- so asserting header-only there
# would be asserting the wrong thing.
check(len(empty['Open_Positions']) == 1 and len(empty['Trade_Log']) == 1,
      "a totally empty state yields header-only position and trade tabs, no crash",
      f"(op={len(empty['Open_Positions'])} tl={len(empty['Trade_Log'])})")
es_empty = {r[0]: r[1] for r in empty['Equity_Summary']}
check(es_empty['Total Equity'] == 0 and es_empty['Closed Trades'] == 0
      and es_empty['Win Rate %'] == '',
      "and Equity_Summary still renders its fixed rows with zeros/blanks",
      f"({es_empty.get('Total Equity')!r} {es_empty.get('Win Rate %')!r})")
try:
    json.dumps(empty, allow_nan=False)
    check(True, "and it still serialises")
except Exception as e:
    check(False, "and it still serialises", str(e))

no_loss = json.loads(json.dumps(STATE))
no_loss['closed_trades_log'] = [t for t in no_loss['closed_trades_log'] if t['pnl'] > 0]
es2 = {r[0]: r[1] for r in lp.build_sheet_payloads(no_loss, LOOKUP, CONTEXT)['Equity_Summary']}
check(es2['Profit Factor'] == 'n/a (no losing trades yet)',
      "no losing trades yet -> an explicit 'n/a', not inf or a crash",
      f"({es2['Profit Factor']!r})")

nolog = json.loads(json.dumps(STATE))
nolog['equity_curve_log'] = []
op2 = lp.build_sheet_payloads(nolog, LOOKUP, CONTEXT)['Open_Positions']
check(op2[1][col(op2, 'Sessions_Held')] == '',
      "no equity_curve_log -> Sessions_Held is blank rather than a wrong number")

no_lookup = lp.build_sheet_payloads(STATE, {}, CONTEXT)['Open_Positions']
check(no_lookup[1][col(no_lookup, 'Last_Close')] == '',
      "a symbol missing from today's panel leaves Last_Close blank, no crash")


print()
print("=" * 70)
if failures:
    print(f"FAILED ({len(failures)})")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("PASSED: three tabs, rectangular, JSON-safe, and the trade history is "
      "finally visible.")
