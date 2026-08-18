"""
init_state.py
--------------
Run ONCE to initialize state/paper_portfolio_state.json before the daily
pipeline runs for the first time. This JSON is the SINGLE SOURCE OF TRUTH
for the paper portfolio -- not the Google Sheet, which is a write-only
human-readable mirror regenerated from this file each run.

Schema:
{
  "bb_cash": float,          # Sniper sleeve cash
  "bb_equity": float,        # Sniper sleeve total equity (cash + open position value at last close)
  "mr_cash": float,          # MR sleeve cash
  "mr_equity": float,        # MR sleeve total equity
  "active_bb": {             # open Sniper positions, keyed by symbol
    "SYMBOL": {
      "entry_date": "YYYY-MM-DD",
      "entry_price": float,
      "shares": int,
      "net_cost": float,
      "stop_price": float,
      "target_price": float,
      "regime_at_entry": "BULL" | "BEAR",
      "breadth_at_entry": float
    }
  },
  "active_mr": {             # open MR positions, keyed by symbol
    "SYMBOL": {
      "entry_date": "YYYY-MM-DD",
      "entry_price": float,
      "shares": int,
      "net_cost": float,
      "trading_days": int    # incremented each day the position stays open
    }
  },
  "closed_trades_log": [],   # append-only history of every closed trade, for later analysis
  "equity_curve_log": [],    # append-only [{"date": ..., "total_equity": ...}, ...] daily snapshot
  "last_run_date": "YYYY-MM-DD"
}
"""

import json
import os

STATE_PATH = 'state/paper_portfolio_state.json'
START_CAPITAL = 600000  # match wfo_engine_updated.py's START_CAPITAL


def init_state(start_capital=START_CAPITAL, force=False):
    if os.path.exists(STATE_PATH) and not force:
        print(f"{STATE_PATH} already exists. Pass force=True to overwrite (WILL WIPE current paper portfolio).")
        return

    state = {
        "bb_cash": start_capital * 0.5,
        "bb_equity": start_capital * 0.5,
        "mr_cash": start_capital * 0.5,
        "mr_equity": start_capital * 0.5,
        "active_bb": {},
        "active_mr": {},
        "closed_trades_log": [],
        "equity_curve_log": [],
        "last_run_date": None
    }

    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2)

    print(f"Initialized {STATE_PATH} with start capital {start_capital:,}")
    print(f"  Sniper sleeve: {state['bb_cash']:,}")
    print(f"  MR sleeve: {state['mr_cash']:,}")


if __name__ == "__main__":
    init_state()
