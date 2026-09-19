"""
test_ordering_fix.py
--------------------
Behavioural test for fix3: the allocation rebalance must run BEFORE exits, as
it does in wfo_engine.run_headless_simulation.

The claim under test is not "the code moved" -- it is that the move changes
position sizing, so the old live pipeline was taking different-sized trades
than the backtest it was validated against, on identical signals and params.

Scenario: one open Sniper position gaps up through its target today (a
realized profit lands in bb_equity/bb_cash), and one new symbol signals an
entry the same day. Sizing depends on bb_equity, so whether the rebalance sees
pre-exit or post-exit equity is directly observable in the share count.
"""

import copy
import sys
import types
import pandas as pd

# live_pipeline imports yfinance/requests at module scope for the data-fetch
# half of the file. Stub them: nothing under test here touches the network.
for name in ('yfinance', 'requests'):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)

sys.path.insert(0, '.')
import live_pipeline as lp

assert hasattr(lp, 'rebalance_allocation'), \
    "live_pipeline.py is not patched -- run: python apply_fixes.py --fix3"

TARGET_DATE = pd.Timestamp('2026-08-21')
ACTIVE_P = {'bb_tgt': 4.0, 'bb_stop': 2.0, 'bb_risk': 2.0, 'mr_time': 5, 'mr_pos_size': 10.0}

# HOLD gaps up through its 130 target -> exits at OPEN 138 for a large profit.
# NEW signals an entry the same day.
TODAY_ROWS = [
    {'SYMBOL': 'HOLD', 'OPEN': 138.0, 'HIGH': 140.0, 'LOW': 137.0, 'CLOSE': 139.0,
     'BB_Enter_Today': False, 'BB_Exhaustion_Today': False, 'MR_Base_Signal': False,
     'Target_ATR': 3.0, 'RS_Percentile': 0.99, 'ATR_Contraction_Ratio': 0.7,
     'Turnover_SMA_50': 5e9, 'SMA_5': 135.0, 'Regime_Label': 'BULL',
     'Market_Breadth': 0.80, 'VIX_Spike': False, 'Systemic_Panic': False},
    {'SYMBOL': 'NEW', 'OPEN': 200.0, 'HIGH': 204.0, 'LOW': 199.0, 'CLOSE': 203.0,
     'BB_Enter_Today': True, 'BB_Exhaustion_Today': False, 'MR_Base_Signal': False,
     'Target_ATR': 5.0, 'RS_Percentile': 0.97, 'ATR_Contraction_Ratio': 0.6,
     'Turnover_SMA_50': 5e9, 'SMA_5': 198.0, 'Regime_Label': 'BULL',
     'Market_Breadth': 0.80, 'VIX_Spike': False, 'Systemic_Panic': False},
]
LOOKUP = {r['SYMBOL']: r for r in TODAY_ROWS}

BASE_STATE = {
    'bb_equity': 300000.0, 'mr_equity': 300000.0,
    'bb_cash': 200000.0, 'mr_cash': 300000.0,
    'active_bb': {'HOLD': {'entry_price': 100.0, 'stop_price': 94.0, 'target_price': 130.0,
                           'shares': 1000, 'net_cost': 100000.0,
                           'entry_date': '2026-08-10', 'trading_days': 5,
                           'regime_at_entry': 'BULL', 'breadth_at_entry': 0.8}},
    'active_mr': {},
    'closed_trades_log': [], 'equity_curve_log': [],
}


def run(order):
    """order='fixed'  -> rebalance, exits, entries   (engine order, post-fix)
       order='old'    -> exits, rebalance, entries   (pre-fix live behaviour)"""
    st = copy.deepcopy(BASE_STATE)
    snapshot = {}
    if order == 'fixed':
        lp.rebalance_allocation(st, 'BULL', 0.80)
        snapshot['bb_equity_at_rebalance'] = st['bb_equity']
        lp.evaluate_exits(st, LOOKUP, 'BULL', ACTIVE_P, TARGET_DATE)
    else:
        lp.evaluate_exits(st, LOOKUP, 'BULL', ACTIVE_P, TARGET_DATE)
        lp.rebalance_allocation(st, 'BULL', 0.80)
        snapshot['bb_equity_at_rebalance'] = st['bb_equity']
    snapshot['bb_equity_before_entries'] = st['bb_equity']
    snapshot['bb_cash_before_entries'] = st['bb_cash']
    lp.evaluate_entries(st, TODAY_ROWS, LOOKUP, 'BULL', 0.80, ACTIVE_P, TARGET_DATE)
    snapshot['state'] = st
    snapshot['new_shares'] = st['active_bb'].get('NEW', {}).get('shares', 0)
    snapshot['new_stop'] = st['active_bb'].get('NEW', {}).get('stop_price', 0)
    return snapshot


print("=" * 74)
print("Scenario")
print("=" * 74)
pre_total = BASE_STATE['bb_equity'] + BASE_STATE['mr_equity']
print(f"  Sleeve equity at start of day : Sniper {BASE_STATE['bb_equity']:,.0f} | "
      f"MR {BASE_STATE['mr_equity']:,.0f}  (total {pre_total:,.0f})")
print(f"  HOLD: entered 100.00, target 130.00, opens at 138.00 -> gap_up_target exit")
print(f"  NEW : BB_Enter_Today True, OPEN 200.00, Target_ATR 5.00")
print(f"  Regime BULL, breadth 0.80 -> allocation 80/20 to Sniper\n")

fixed = run('fixed')
old = run('old')

print("=" * 74)
print("RESULT")
print("=" * 74)
print(f"  {'':<34} {'OLD (exits first)':>19} {'FIXED (engine order)':>21}")
print("  " + "-" * 76)
for k, label in (('bb_equity_at_rebalance', 'Sniper equity the rebalance saw'),
                 ('bb_equity_before_entries', 'Sniper equity sizing the entry'),
                 ('bb_cash_before_entries', 'Sniper cash available'),
                 ('new_shares', 'NEW: shares bought')):
    a, b = old[k], fixed[k]
    fmt = (lambda v: f"{v:,.0f}") if k != 'new_shares' else (lambda v: f"{v:,d}")
    print(f"  {label:<34} {fmt(a):>19} {fmt(b):>21}")

print(f"\n  Rebalance base: FIXED used the pre-exit total ({pre_total:,.0f} x 0.80 = "
      f"{pre_total*0.8:,.0f}),")
print(f"  OLD used the post-exit total, which already contained HOLD's realized profit.")

assert abs(fixed['bb_equity_at_rebalance'] - pre_total * 0.80) < 1e-6, \
    "fixed path did not rebalance off pre-exit equity"
assert old['bb_equity_at_rebalance'] > fixed['bb_equity_at_rebalance'], \
    "expected the old path to rebalance off a larger, post-profit base"
assert old['new_shares'] != fixed['new_shares'], \
    "ordering change did not affect position sizing in this scenario"

diff = old['new_shares'] - fixed['new_shares']
print(f"\n  => CONFIRMED: same signal, same params, same prices -- the old ordering")
print(f"     bought {abs(diff)} {'more' if diff > 0 else 'fewer'} shares of NEW "
      f"({old['new_shares']} vs {fixed['new_shares']}, "
      f"{abs(diff)/fixed['new_shares']*100:.1f}% difference).")
print("     Live was therefore sizing trades differently from the backtest that")
print("     validated the parameters. Post-fix, live matches the engine's order:")
print("     rebalance -> exits -> entries.")

print("\n  Note: the engine ALSO accrues idle yield before the rebalance, and live")
print("  still has none. That is a separate open finding; this test isolates")
print("  ordering only.")
print("=" * 74)
