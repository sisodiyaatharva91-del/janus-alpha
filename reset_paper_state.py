"""
reset_paper_state.py
====================
Archives the contaminated paper-trading state and writes a clean one.

WHY (dell's decision, 2026-08-22: "Reset and restart clean")
    state/paper_portfolio_state.json accumulated fills that cannot be compared
    with anything produced after the 2026-08-22 fixes:

      * finding #26 -- the 3 Sniper positions opened 2026-08-17 were entered at
        OPEN(t) on a signal computed from CLOSE(t), with stops and share counts
        sized from that same unseeable bar. Entry price, stop distance AND
        position size are all contaminated, so the open P&L is not a number that
        means anything.
      * finding #27 -- fills were recorded under the old exits-before-rebalance
        ordering, so the sleeve cash balances reflect a sequence the engine no
        longer uses.
      * finding #33 -- nothing prevented re-processing an already-processed
        bhavcopy, so MR positions may have aged extra sessions and
        equity_curve_log may hold duplicate dates.
      * items 29+36 -- accrued at a stated 6%/yr on a /365 basis (a true
        4.2291%) where live and backtest now both use a true 4.0%/yr on a /252
        basis.

    Any of those alone would justify a reset. Together they mean the existing
    curve is not a baseline, it is noise with a plausible shape.

WHY ARCHIVE RATHER THAN DELETE
    The contaminated state is the only record of what the pipeline actually did
    between going live and 2026-08-22. It is worthless as performance data and
    valuable as evidence -- e.g. it is how you would check whether a future bug
    is new or was always there. It costs a few KB to keep.

WHAT THIS SCRIPT DELIBERATELY DOES NOT DO
    It does not try to "repair" the old state by re-pricing entries at OPEN(t+1)
    or recomputing stops. That would be inventing history: the honest position
    set is not the contaminated one at different prices, because different
    entries would have consumed different cash and therefore permitted a
    different set of later entries. There is no local fix to a path-dependent
    simulation. Start clean.

USAGE
    python reset_paper_state.py --dry-run     # show what would happen
    python reset_paper_state.py               # archive + write clean state
    python reset_paper_state.py --repo /path/to/janus-alpha
"""

import argparse
import ast
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

STATE_REL = os.path.join('state', 'paper_portfolio_state.json')
ARCHIVE_REL = os.path.join('state', 'archive')
PIPELINE = 'live_pipeline.py'
ENGINE = 'wfo_engine_updated.py'

REASON = (
    "Reset after the 2026-08-22 audit. The prior state was produced under "
    "findings #26 (Sniper look-ahead in entry price, stop distance and position "
    "size), #27 (exits ordered before the allocation rebalance), #33 (no "
    "duplicate-session guard) and a 6%/365 idle-yield basis. Its equity curve "
    "is not comparable with anything recorded after this point."
)


def required_state_keys(pipeline_path):
    """Every key live_pipeline.py reads off the state dict, read FROM ITS SOURCE.

    Hardcoding the list here would let the reset script drift out of step with
    the pipeline it exists to serve -- write a state file missing a key the
    pipeline reads and the first live run dies with a KeyError, at 16:00 IST, in
    a GitHub Action. Same reasoning as engine_harness.engine_constants: read the
    thing, do not restate it.

    Matches state['key'] and state.get('key'. Keys starting with '_' are ours
    (provenance) and are excluded so they are never treated as required.
    """
    src = open(pipeline_path, encoding='utf-8').read()
    keys = set(re.findall(r"state\['([A-Za-z_][A-Za-z0-9_]*)'\]", src))
    keys |= set(re.findall(r"state\.get\('([A-Za-z_][A-Za-z0-9_]*)'", src))
    keys = {k for k in keys if not k.startswith('_')}
    if not keys:
        sys.exit(f"ERROR: found no state keys in {pipeline_path}. The access "
                 f"pattern changed -- fix the regex rather than writing a state "
                 f"file validated against nothing.")
    return keys


def module_constant(path, name, default=None):
    """A module-level literal constant, via ast.literal_eval (not import: both
    files execute work at import time)."""
    try:
        src = open(path, encoding='utf-8').read()
    except OSError:
        return default
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id == name:
            try:
                return ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                return default
    return default


def clean_state(start_capital, archived_to, reason):
    """A state file identical in shape to what run_headless_simulation starts
    from: both sleeves at half the capital, fully in cash, nothing open.

    last_run_date is '' ON PURPOSE. Both consumers document that case --
    is_new_trading_date returns True ("fresh or freshly reset state file") and
    trading_days_since returns 1 -- so the first run after a reset accrues one
    session of yield and is not blocked by the duplicate guard. Seeding a date
    here would either suppress the first run or invent a yield catch-up window.
    """
    half = round(start_capital * 0.5, 2)
    return {
        'bb_equity': half, 'bb_cash': half,
        'mr_equity': half, 'mr_cash': half,
        'active_bb': {}, 'active_mr': {},
        'closed_trades_log': [], 'equity_curve_log': [],
        'last_run_date': '',
        # Leading underscore: not read by the pipeline (verified -- every access
        # is a named key, nothing iterates the dict), and it survives the
        # load_state/save_state round trip, so the provenance travels with the
        # file instead of living only in a commit message.
        '_reset_metadata': {
            'reset_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'reset_by': 'reset_paper_state.py',
            'start_capital': start_capital,
            'reason': reason,
            'archived_previous_to': archived_to,
            'discontinuity': ('Do NOT splice equity_curve_log across this point. '
                              'The pre-reset curve was generated by different '
                              'entry timing, a different rebalance order and a '
                              'different yield basis.'),
        },
    }


def describe(state):
    """What is about to be discarded, in the terms that make the cost visible."""
    if not isinstance(state, dict):
        return ["  (state file is not a JSON object -- nothing to summarise)"]
    bb, mr = state.get('active_bb', {}) or {}, state.get('active_mr', {}) or {}
    closed = state.get('closed_trades_log', []) or []
    curve = state.get('equity_curve_log', []) or []
    lines = [
        f"  last_run_date      : {state.get('last_run_date', '') or '(empty)'}",
        f"  Sniper equity/cash : {state.get('bb_equity', 0):,.2f} / "
        f"{state.get('bb_cash', 0):,.2f}",
        f"  MR equity/cash     : {state.get('mr_equity', 0):,.2f} / "
        f"{state.get('mr_cash', 0):,.2f}",
        f"  open Sniper        : {len(bb)}  {sorted(bb)}",
        f"  open MR            : {len(mr)}  {sorted(mr)}",
        f"  closed trades      : {len(closed)}",
        f"  equity curve rows  : {len(curve)}",
    ]
    if curve:
        lines.append(f"  curve spans        : {curve[0].get('date')} -> "
                     f"{curve[-1].get('date')}")
    # Duplicate dates are the fingerprint of finding #33 actually having bitten,
    # as opposed to merely having been possible. Worth reporting before the
    # evidence is archived.
    dates = [r.get('date') for r in curve if isinstance(r, dict)]
    dupes = sorted({d for d in dates if dates.count(d) > 1})
    if dupes:
        lines.append(f"  DUPLICATE dates    : {len(dupes)} -> {dupes[:6]}"
                     f"{' ...' if len(dupes) > 6 else ''}")
        lines.append("                       (finding #33 did occur in practice, "
                     "not just in principle)")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default='.', help='repo root (holds state/ and the scripts)')
    ap.add_argument('--dry-run', action='store_true',
                    help='print the plan and the clean state, write nothing')
    ap.add_argument('--start-capital', type=float, default=None,
                    help=f'default: START_CAPITAL read from {ENGINE}')
    args = ap.parse_args()

    root = os.path.abspath(args.repo)
    state_path = os.path.join(root, STATE_REL)
    archive_dir = os.path.join(root, ARCHIVE_REL)
    pipeline_path = os.path.join(root, PIPELINE)

    if not os.path.exists(pipeline_path):
        sys.exit(f"ERROR: {pipeline_path} not found. Point --repo at the repo root.")

    # Capital comes from the engine, so a clean state cannot silently disagree
    # with the backtest it is supposed to be comparable to.
    start_cap = args.start_capital
    if start_cap is None:
        start_cap = module_constant(os.path.join(root, ENGINE), 'START_CAPITAL')
        if start_cap is None:
            sys.exit(f"ERROR: could not read START_CAPITAL from {ENGINE}. Pass "
                     f"--start-capital explicitly rather than guessing.")
        print(f"START_CAPITAL = {start_cap:,.0f}  (read from {ENGINE})")
    else:
        print(f"START_CAPITAL = {start_cap:,.0f}  (--start-capital override)")

    required = required_state_keys(pipeline_path)
    print(f"Pipeline reads {len(required)} state keys: {', '.join(sorted(required))}")

    # ---- inspect what exists -------------------------------------------
    old, old_err = None, None
    if os.path.exists(state_path):
        try:
            with open(state_path, encoding='utf-8') as f:
                old = json.load(f)
        except Exception as e:
            old_err = e
        print(f"\nEXISTING state at {STATE_REL}:")
        if old_err:
            print(f"  UNREADABLE ({old_err}). It will still be archived verbatim.")
        else:
            for line in describe(old):
                print(line)
    else:
        print(f"\nNo existing state at {STATE_REL} -- nothing to archive.")

    # ---- build and validate the clean state ----------------------------
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive_name = f'paper_portfolio_state.{stamp}.contaminated.json'
    archive_path = os.path.join(archive_dir, archive_name)
    new = clean_state(start_cap,
                      os.path.join(ARCHIVE_REL, archive_name) if old is not None
                      or os.path.exists(state_path) else None,
                      REASON)

    absent = sorted(required - set(new))
    if absent:
        sys.exit(f"ERROR: the clean state is missing {absent}, which "
                 f"{PIPELINE} reads. The pipeline gained a state key and this "
                 f"script was not updated -- add it to clean_state() rather "
                 f"than writing a state file that will KeyError on the first run.")
    print(f"\nClean state satisfies all {len(required)} required keys.")
    extra = sorted(set(new) - required - {'_reset_metadata'})
    if extra:
        print(f"  (also writing unused keys: {extra})")

    total = new['bb_equity'] + new['mr_equity']
    print(f"  Sniper {new['bb_equity']:,.2f}  +  MR {new['mr_equity']:,.2f}"
          f"  =  {total:,.2f}")
    if abs(total - start_cap) > 0.01:
        sys.exit(f"ERROR: sleeves sum to {total:,.2f}, not {start_cap:,.2f}.")

    if args.dry_run:
        print("\n--dry-run: nothing written. The state file would be:\n")
        print(json.dumps(new, indent=2))
        print(f"\nAnd the current file would be archived to {ARCHIVE_REL}/{archive_name}")
        return

    # ---- archive, then write ------------------------------------------
    if os.path.exists(state_path):
        os.makedirs(archive_dir, exist_ok=True)
        shutil.copy2(state_path, archive_path)          # copy2 keeps mtime
        print(f"\nArchived  {STATE_REL}  ->  {ARCHIVE_REL}/{archive_name}")
        note = os.path.join(archive_dir, 'README.md')
        if not os.path.exists(note):
            with open(note, 'w', encoding='utf-8') as f:
                f.write("# Archived paper-trading state\n\n"
                        "Files here are PRE-FIX state snapshots, kept as evidence "
                        "of what the pipeline did, NOT as performance data.\n\n"
                        f"{REASON}\n\n"
                        "Do not splice their `equity_curve_log` onto the current "
                        "one: entry timing, rebalance order and the idle-yield "
                        "basis all differ across the reset boundary.\n")
            print(f"Wrote     {ARCHIVE_REL}/README.md")
    else:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)

    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(new, f, indent=2)
    print(f"Wrote     {STATE_REL}  (clean, {total:,.0f} in cash, nothing open)")

    # Read it back. A state file that does not parse is the one failure mode
    # that would take the next scheduled run down, so do not assume the write
    # worked -- confirm it.
    with open(state_path, encoding='utf-8') as f:
        back = json.load(f)
    if back != new:
        sys.exit("ERROR: the file read back does not match what was written.")
    print("Verified  re-read matches what was written.")

    print("\nNEXT")
    print("  1. Commit both the clean state and the archived copy, so the")
    print("     discontinuity is in the history rather than in someone's memory.")
    print("  2. The first run after this will report one session of idle yield")
    print("     and will NOT be blocked by the duplicate-run guard, because")
    print("     last_run_date is empty. Both are intended.")
    print("  3. Expect the first Telegram report to show total equity within a")
    print(f"     rupee or two of {total:,.0f} and zero open positions. Anything")
    print("     else means the pipeline did not read this file.")


if __name__ == '__main__':
    main()
