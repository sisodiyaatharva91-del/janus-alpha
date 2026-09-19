"""
apply_fixes.py — Janus, session 2026-08-22
==========================================
Applies the fixes for the findings from this session to a repo checkout.
Exact-string replacement with assertions, so a silent partial patch is
impossible. Idempotent: refuses to double-apply.

Each fix is behind its own flag. Nothing is applied by default, and there is
no --all, because these three have different blast radii and should be
measured separately:

  --fix1   coiled_alpha_logic.py : the Sniper look-ahead (decision-timing lag)
           Affects BACKTEST AND LIVE. Requires re-running the WFO to get new
           numbers. This is the one to do first and alone.

  --fix3   live_pipeline.py : allocation rebalance ordering
           Affects LIVE ONLY -- it cannot contaminate a fix1 measurement, so
           it is safe to apply in the same sitting even though fix1's
           re-run is still pending.

  --fix5   wfo_engine_updated.py : CAGR annualization units in
           calculate_fitness(). Affects PARAMETER SELECTION and every
           per-window CAGR printed. Does NOT affect the chained CAGR headline.
           Apply BEFORE the fix1 re-run if you want the re-run's selection to
           be correct -- but then the new numbers reflect two changes at once,
           so decide deliberately.

Usage:
    python apply_fixes.py --fix1
    python apply_fixes.py --fix1 --fix3 --fix5
    python apply_fixes.py --fix3 --dir /path/to/janus-alpha
"""

import argparse
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--dir', default='.', help='repo directory containing the files')
ap.add_argument('--fix1', action='store_true', help='Sniper look-ahead decision-timing lag')
ap.add_argument('--fix3', action='store_true', help='live_pipeline rebalance ordering')
ap.add_argument('--fix5', action='store_true', help='calculate_fitness CAGR units')
args = ap.parse_args()

if not (args.fix1 or args.fix3 or args.fix5):
    ap.error("pick at least one of --fix1 / --fix3 / --fix5 (there is no --all on purpose)")


def load(name):
    p = os.path.join(args.dir, name)
    if not os.path.exists(p):
        sys.exit(f"ERROR: {p} not found. Use --dir to point at the repo.")
    return p, open(p, encoding='utf-8').read()


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ERROR [{label}]: anchor matched {n} times, expected exactly 1. "
                 f"The file has drifted from the version this patch was written "
                 f"against -- reconcile by hand rather than forcing it.")
    return src.replace(old, new, 1)


applied = []

# =====================================================================
# FIX 1 -- coiled_alpha_logic.py : decision-timing lag
# =====================================================================
if args.fix1:
    path, src = load('coiled_alpha_logic.py')
    if 'DECISION TIMING (see section 5b)' in src:
        print("  fix1: already applied, skipping.")
    else:
        src = sub(src, """- RS_Percentile and Daily_Turnover_Rank are computed per-DATE
  (groupby('DATE')) — "top 10%" = top 10% of the ENTIRE MARKET that day.
- Signal at close(t) -> intended execution at open(t+1), same convention
  as MR_Base_Signal.""", """- RS_Percentile and Daily_Turnover_Rank are computed per-DATE
  (groupby('DATE')) — "top 10%" = top 10% of the ENTIRE MARKET that day.

- DECISION TIMING (see section 5b) — signal at close(t) executes at open(t+1).
  This is now ENFORCED, not merely intended. Until 2026-08-22 this docstring
  claimed the convention while no code implemented it: every consumer
  (wfo_engine.py, live_pipeline.py) filled Sniper entries at OPEN(t) while
  reading BB_Enter_Today / Target_ATR / RS_Percentile / ATR_Contraction_Ratio
  computed from CLOSE(t) and HIGH(t)/LOW(t) of that SAME bar. That is
  look-ahead: the fill price precedes the information that justified it.
  Section 5b lags those four columns by one bar per SYMBOL, so bar t carries
  decision inputs as of close(t-1) while OPEN(t) remains the fill price.
  Consumers require no changes.

  ** READ THIS BEFORE "FIXING" AN APPARENT INCONSISTENCY **
  After section 5b, BB_Enter_Today is deliberately NOT equal to the AND of the
  Sniper_Pass_* columns on the same row — it equals their AND on the PREVIOUS
  row. The Sniper_Pass_* columns are unlagged diagnostics. Re-deriving
  BB_Enter_Today from them on the same row would silently reintroduce the
  look-ahead. Use BB_Enter_Signal_Raw for same-bar diagnostics instead.

- The MR sleeve is deliberately NOT lagged. MR_Base_Signal fires on close(t)
  and the engines fill it at CLOSE(t) — a market-on-close convention that is
  internally consistent and implementable. Lagging it would make the sleeve a
  full day late on a 1-3 day mean-reversion bounce. BB_Exhaustion_Today is
  likewise close(t) -> close(t) and left alone.""", 'fix1 docstring')

        src = sub(src, """    price_jump_threshold: float = 0.40,   # corporate-action artifact guard
    min_history_days: int = None,
) -> pd.DataFrame:""", """    price_jump_threshold: float = 0.40,   # corporate-action artifact guard
    min_history_days: int = None,
    lag_sniper_decision_inputs: bool = True,
) -> pd.DataFrame:""", 'fix1 signature')

        src = sub(src, "    nifty_df : optional. Nifty 50 index dataframe, columns",
                  """    lag_sniper_decision_inputs : keep True. Enforces the close(t) ->
         open(t+1) execution convention (section 5b). Set False ONLY to
         reproduce the pre-2026-08-22 contaminated numbers for an A/B
         impact measurement. Any research or live result produced with
         False is look-ahead biased and must not be compared against a
         True result as if both were valid.
    nifty_df : optional. Nifty 50 index dataframe, columns""", 'fix1 param doc')

        src = sub(src, '    df["Target_ATR"] = df["ATR_Short"]\n',
                  '''    df["Target_ATR"] = df["ATR_Short"]

    # ------------------------------------------------------------------
    # 5b. DECISION-TIMING LAG — enforces signal at close(t) -> fill at
    #     open(t+1). See the "DECISION TIMING" note in the module docstring
    #     for why this exists and what breaks if it is removed.
    #
    #     These are exactly the four columns the Sniper ENTRY block reads in
    #     wfo_engine.py / live_pipeline.py, and they are read nowhere else:
    #
    #       BB_Enter_Today          -> candidate selection
    #       Target_ATR              -> stop/target distance + risk-based size
    #       RS_Percentile           -> primary candidate sort key (descending)
    #       ATR_Contraction_Ratio   -> tiebreak sort key (ascending)
    #
    #     Because the entry block fills at that row's OPEN, lagging the inputs
    #     one bar per SYMBOL is sufficient and needs no engine edits — which
    #     matters, since run_headless_simulation is duplicated across several
    #     files and each hand-edit is a live/backtest drift risk.
    #
    #     shift(fill_value=False) rather than shift().fillna(False):
    #     bool(float('nan')) is True in Python, so a bare shift would leave a
    #     NaN on each SYMBOL's first bar that the engine's truthiness test
    #     ("if r['BB_Enter_Today']") reads as a VALID ENTRY SIGNAL — one
    #     phantom trade per listed symbol, silently. fill_value never creates
    #     the NaN in the first place, so the trap is unrepresentable rather
    #     than patched after the fact.
    #
    #     The numeric columns keep NaN on the first bar deliberately: the
    #     engine already guards with `if pd.isna(atr) or atr <= 0: continue`,
    #     and a NaN there can never be reached anyway, because a True lagged
    #     BB_Enter_Today implies the prior bar passed the RS and volatility
    #     -contraction tests, which implies those values were non-NaN.
    #
    #     shift() is positional within SYMBOL ("previous available bar for
    #     this stock"), not calendar-based. That is the correct semantic — the
    #     last observable close before this open. Note that for a symbol
    #     returning from a long suspension the previous bar may be far in the
    #     past; the min_history_days warmup gate limits but does not fully
    #     eliminate this.
    # ------------------------------------------------------------------
    df["BB_Enter_Signal_Raw"] = df["BB_Enter_Today"]   # unlagged, diagnostics only

    if lag_sniper_decision_inputs:
        df = df.sort_values(["SYMBOL", "DATE"]).reset_index(drop=True)
        g = df.groupby("SYMBOL")

        df["BB_Enter_Today"] = g["BB_Enter_Today"].shift(1, fill_value=False).astype(bool)
        for _col in ("Target_ATR", "RS_Percentile", "ATR_Contraction_Ratio"):
            df[_col] = g[_col].shift(1)

        # Fail loudly rather than trade on a malformed panel.
        assert df["BB_Enter_Today"].dtype == bool, "BB_Enter_Today must stay bool"
        assert not df["BB_Enter_Today"].isna().any(), "NaN leaked into BB_Enter_Today"
        _live = df["BB_Enter_Today"]
        assert not df.loc[_live, "Target_ATR"].isna().any(), \\
            "Target_ATR is NaN on a row flagged for entry"
        assert not df.loc[_live, "RS_Percentile"].isna().any(), \\
            "RS_Percentile is NaN on a row flagged for entry"
''', 'fix1 lag block')

        open(path, 'w', encoding='utf-8').write(src)
        applied.append('fix1  coiled_alpha_logic.py  (look-ahead decision-timing lag)')

# =====================================================================
# FIX 3 -- live_pipeline.py : rebalance ordering
# =====================================================================
if args.fix3:
    path, src = load('live_pipeline.py')
    if 'def rebalance_allocation(' in src:
        print("  fix3: already applied, skipping.")
    else:
        OLD = """def evaluate_entries(state, today_rows, today_lookup, today_regime, current_breadth, active_p, target_date):
    events = []
    total_equity = state['bb_equity'] + state['mr_equity']
    if today_regime == 'BULL':
        if current_breadth > 0.65: bb_frac, mr_frac = 0.80, 0.20
        elif current_breadth >= 0.50: bb_frac, mr_frac = 0.60, 0.40
        else: bb_frac, mr_frac = 0.35, 0.65
    else:
        bb_frac, mr_frac = 0.20, 0.80
    target_bb_equity, target_mr_equity = total_equity * bb_frac, total_equity * mr_frac
    state['bb_cash'] += (target_bb_equity - state['bb_equity'])
    state['mr_cash'] += (target_mr_equity - state['mr_equity'])
    state['bb_equity'], state['mr_equity'] = target_bb_equity, target_mr_equity
"""
        NEW = '''def rebalance_allocation(state, today_regime, current_breadth):
    """Split capital between the sleeves on regime AND breadth jointly.

    EXTRACTED OUT OF evaluate_entries ON 2026-08-22 so that main() can call it
    in the same position as wfo_engine's run_headless_simulation, which runs it
    BEFORE exits:

        engine : yield -> REBALANCE -> Sniper exits -> MR exits -> MR entries -> Sniper entries
        live   : (no yield) -> exits -> [rebalance was in here] -> entries

    Why the order is not cosmetic: bb_equity is a running sleeve balance, not a
    mark-to-market. An exit adds its realized profit to bb_equity/mr_equity, so
    rebalancing AFTER exits computes target_bb_equity off a different, larger
    base -- which then feeds every position size taken that day, since the
    Sniper entry block sizes off bb_equity three separate ways (risk-based
    shares, the 20% concentration cap, and gap_safe_shares) and is capped by
    bb_cash. Same signals, same params, different share counts.

    The engine is the reference implementation the Phase 1 parameters were
    fitted against, so live conforms to the engine, not the reverse.

    NOTE: the engine also accrues idle yield BEFORE this step, and live still
    has no yield accrual at all (separate open finding). When yield is added to
    live it must go before this call, not after.
    """
    total_equity = state['bb_equity'] + state['mr_equity']
    if today_regime == 'BULL':
        if current_breadth > 0.65: bb_frac, mr_frac = 0.80, 0.20
        elif current_breadth >= 0.50: bb_frac, mr_frac = 0.60, 0.40
        else: bb_frac, mr_frac = 0.35, 0.65
    else:
        bb_frac, mr_frac = 0.20, 0.80
    target_bb_equity, target_mr_equity = total_equity * bb_frac, total_equity * mr_frac
    state['bb_cash'] += (target_bb_equity - state['bb_equity'])
    state['mr_cash'] += (target_mr_equity - state['mr_equity'])
    state['bb_equity'], state['mr_equity'] = target_bb_equity, target_mr_equity
    return bb_frac, mr_frac


def evaluate_entries(state, today_rows, today_lookup, today_regime, current_breadth, active_p, target_date):
    events = []
    # Allocation rebalance deliberately NOT done here any more -- main() calls
    # rebalance_allocation() before evaluate_exits() to match the engine.
'''
        src = sub(src, OLD, NEW, 'fix3 extract rebalance')

        OLD_MAIN = """    exit_events = evaluate_exits(state, today_lookup, today_regime, active_p, target_date)
    entry_events = evaluate_entries(state, today_rows, today_lookup, today_regime, current_breadth, active_p, target_date)"""
        NEW_MAIN = """    # ORDER MATTERS -- must match wfo_engine.run_headless_simulation:
    #   rebalance -> exits -> entries.
    # See rebalance_allocation's docstring for why.
    rebalance_allocation(state, today_regime, current_breadth)
    exit_events = evaluate_exits(state, today_lookup, today_regime, active_p, target_date)
    entry_events = evaluate_entries(state, today_rows, today_lookup, today_regime, current_breadth, active_p, target_date)"""
        src = sub(src, OLD_MAIN, NEW_MAIN, 'fix3 main() call order')

        open(path, 'w', encoding='utf-8').write(src)
        applied.append('fix3  live_pipeline.py       (rebalance before exits, matching the engine)')

# =====================================================================
# FIX 5 -- wfo_engine_updated.py : CAGR annualization units
# =====================================================================
if args.fix5:
    path, src = load('wfo_engine_updated.py')
    # SENTINEL MUST BE UNIQUE TO THIS EDIT -- do not widen it back.
    # This guard used to be `if 'TRADING_DAYS_PER_YEAR' in src`, which was a bug:
    # apply_fixes_v2.py --idle-yield legitimately introduces a module-level
    # constant of that exact name into this same file. Running v2 first therefore
    # made fix5 print "already applied, skipping" and silently leave the CAGR
    # units bug in place -- the worst kind of failure, because the output
    # actively reassures you. Reproduced 2026-08-22. The comment banner below is
    # written by fix5 and by nothing else, so it is a safe sentinel.
    # (If both patches are applied, calculate_fitness ends up with a
    # function-local TRADING_DAYS_PER_YEAR = 252 shadowing v2's module-level
    # one. Same value, so harmless -- each patch stays self-contained and
    # correct when run alone, which matters more than avoiding the duplicate.)
    if 'UNITS FIX 2026-08-22' in src:
        print("  fix5: already applied, skipping.")
    else:
        OLD = """    days = len(eq_curve)
    cagr = ((eq_series.iloc[-1] / eq_series.iloc[0]) ** (365.25 / days) - 1) * 100"""
        NEW = """    # UNITS FIX 2026-08-22: `days` counts TRADING days (equity_curve gets one
    # append per entry in calendar_dates, which is the list of trading dates),
    # so annualizing with 365.25/days treated a 252-day year as 365.25 days
    # long and inflated CAGR by the exponent 365.25/252 = 1.4494. A true
    # 14.17% printed as 21.18%. Note the chained-CAGR block further down this
    # file already used days/252 and was correct -- the two disagreed.
    #
    # This was not only a reporting error: fitness uses
    # sortino = (cagr/100)/downside_std with norm_sortino = min(sortino/3, 1),
    # so inflated CAGR pushed candidates INTO that cap, where the
    # risk-adjusted term stopped discriminating between them and selection
    # fell through to profit factor / win rate / trade count. Demonstrated to
    # be able to flip the selected candidate -- see test_cagr_units.py and
    # test_cagr_units_selection.py.
    TRADING_DAYS_PER_YEAR = 252
    days = len(eq_curve)
    years = days / TRADING_DAYS_PER_YEAR
    cagr = ((eq_series.iloc[-1] / eq_series.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0.0"""
        src = sub(src, OLD, NEW, 'fix5 cagr units')
        open(path, 'w', encoding='utf-8').write(src)
        applied.append('fix5  wfo_engine_updated.py  (CAGR annualization units in calculate_fitness)')

# =====================================================================
print()
if applied:
    print("APPLIED:")
    for a in applied:
        print(f"  - {a}")
else:
    print("Nothing applied (all selected fixes were already present).")

if args.fix1:
    print("""
NEXT for fix1, in this order:
  1. python measure_lookahead_bias.py --data <V9 parquet>            (seconds)
     Then again with --stage2                                        (minutes)
     You do NOT need to re-run data_prep for this -- the script lags the four
     columns post-hoc, which is equivalent because data_prep never writes to
     them after calling apply_coiled_alpha_logic.
  2. Re-run data_prep_updated.py so the stored V9 parquet is correct on disk.
  3. Re-run wfo_engine_updated.py for ONE seed and read the chained CAGR / DD.
     Expect it to come in below the current 14.17% / -29.96%.""")
if args.fix3:
    print("""
NEXT for fix3: the live paper state file has fills recorded under the old
ordering AND the old look-ahead timing. Decide explicitly whether to reset
state/paper_portfolio_state.json or keep it with a documented discontinuity
marker -- the 3 Sniper positions opened on 2026-08-17 were entered at
look-ahead prices with look-ahead stops.""")
