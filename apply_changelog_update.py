"""
apply_changelog_update.py — Janus, session 2026-08-22
=====================================================
Writes this session's audit findings into ENGINEERING_CHANGELOG.md.

Separate from apply_fixes.py on purpose: this touches only documentation, so it
is safe to run before any code fix and before the WFO re-run. Run it now so the
findings are recorded even if the re-run slips.

Same discipline as apply_fixes.py: exact-string replacement, each anchor
asserted to match exactly once, idempotent (refuses to double-apply).

    python apply_changelog_update.py
    python apply_changelog_update.py --dir /path/to/janus-alpha
    python apply_changelog_update.py --out /tmp/preview.md   # dry-run to a copy
"""

import argparse
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--dir', default='.', help='directory containing ENGINEERING_CHANGELOG.md')
ap.add_argument('--out', default=None,
                help='write the result here instead of in place (for review/diffing)')
args = ap.parse_args()

path = os.path.join(args.dir, 'ENGINEERING_CHANGELOG.md')
if not os.path.exists(path):
    sys.exit(f"ERROR: {path} not found. Use --dir to point at the repo.")
src = open(path, encoding='utf-8').read()

SENTINEL = '26. **LOOK-AHEAD BIAS in the Sniper entry path'
if SENTINEL in src:
    print("Already applied (item 26 present). Nothing to do.")
    sys.exit(0)


def sub(old, new, label):
    global src
    n = src.count(old)
    if n != 1:
        sys.exit(f"ERROR [{label}]: anchor matched {n} times, expected exactly 1.\n"
                 f"The changelog has drifted from the version this patch was written\n"
                 f"against. Reconcile by hand rather than forcing it.")
    src = src.replace(old, new, 1)


# =====================================================================
# 1. STATUS block at the top — the headline numbers are now provisional.
# =====================================================================
sub("""for the final backtest numbers and the decision rationale for stopping
backtest iteration there.""",
    """for the final backtest numbers and the decision rationale for stopping
backtest iteration there.

> **⚠ READ THIS BEFORE QUOTING ANY PHASE 1 NUMBER (added 2026-08-22).**
> A live/backtest reconciliation audit found a **look-ahead bias in the Sniper
> entry path** (Part E item 26) that was present in every Phase 1 backtest and
> in every live Sniper fill up to and including 2026-08-22. **The 14.17% CAGR /
> −29.96% DD headline is therefore SUPERSEDED and not yet replaced** — it was
> measured under contaminated decision timing and the corrected number is
> expected to be lower. The fix is written and unit-verified; the re-run that
> produces honest numbers has not been done. Until it has, treat every Sniper
> figure in Parts B/C/D and in the closure summary as an upper bound, not a
> result. The same audit found four smaller defects (items 27–31), two of which
> need a decision from you rather than a code change.""",
    'status block')

# =====================================================================
# 2. Files in this build — add the audit's test/tool files.
# =====================================================================
sub("- `SETUP_GUIDE.md` — Phase 2 setup instructions",
    """- `SETUP_GUIDE.md` — Phase 2 setup instructions

Added by the 2026-08-22 reconciliation audit (see Part E items 26-31):
- `apply_fixes.py` — applies the code fixes, one flag per finding, idempotent
- `apply_changelog_update.py` — applies this changelog update
- `measure_lookahead_bias.py` — cheap 2-stage measurement of the look-ahead's
  cost on the real panel, BEFORE committing to a full WFO re-run
- `test_lookahead.py` — proves the look-ahead existed (property test over every
  position the real engine opens, not a rigged fixture)
- `test_fix_verification.py` — proves the fix does exactly what it claims and
  nothing else (blast-radius test: exactly 4 columns change, 35 unchanged)
- `test_ordering_fix.py` — proves the rebalance-ordering fix changes position
  sizing, i.e. that it was a real divergence and not a cosmetic move
- `test_cagr_units.py` / `test_cagr_units_selection.py` — the CAGR units bug
  and a worked existence proof that it can flip candidate selection
- `test_window_gap_decomposition.py` — shows item 15's "~4pp volatility drag"
  gap is not a valid measurement""",
    'files list')

# =====================================================================
# 3. Part A item 1 — the column contract changed.
# =====================================================================
sub("1. **Column contract**: final entry signal is named `BB_Enter_Today` (not",
    """> **AMENDED 2026-08-22**: `BB_Enter_Today`, `Target_ATR`, `RS_Percentile` and
> `ATR_Contraction_Ratio` are now lagged one bar per SYMBOL inside
> `apply_coiled_alpha_logic` (new section 5b), and a new diagnostic column
> `BB_Enter_Signal_Raw` carries the unlagged signal. See Part E item 26 before
> relying on anything in this section. Consequence worth knowing up front:
> `BB_Enter_Today` is deliberately NOT the AND of the `Sniper_Pass_*` columns
> on the same row any more — it is their AND on the PREVIOUS row.

1. **Column contract**: final entry signal is named `BB_Enter_Today` (not""",
    'part A item 1')

# =====================================================================
# 4. Part B item 15 — the drag quantification does not hold up.
# =====================================================================
sub("by volatility drag / Jensen's inequality).",
    """by volatility drag / Jensen's inequality).
    **CORRECTION 2026-08-22 — the 15.69% vs 11.72% pair does not support that
    quantification; see Part E item 28.** `Average OOS CAGR` is computed by
    `calculate_fitness()`, which had a units bug inflating it by the exponent
    365.25/252 = 1.4494, while the chained CAGR in section 6 was always
    correct. The two lines were therefore never on the same annualization
    convention. Worse, the pair is arithmetically impossible: one-year windows
    compounding to 11.72%/yr must report an average of **at least 17.43%**
    under the buggy formula (convexity floor, attained only at zero
    dispersion), so a reported 15.69% cannot coexist with it. Note also that
    11.72% appears twice in this item — once as the SYNTHETIC unit test's
    expectation and once as a real run's compounded CAGR — so the comparison
    may simply have paired a real average against the synthetic test's number.
    **What survives: the CONCLUSION.** Per-window resets genuinely cannot show
    a losing streak compounding across window boundaries, and arithmetic mean
    ≥ geometric mean always holds, so the chained curve remains the correct
    headline. Only the "~4pp driven by volatility drag" magnitude is
    withdrawn; the true drag term is unmeasured. To measure it, deflate the
    stored per-window column first — `test_window_gap_decomposition.py` prints
    the two-line snippet.""",
    'part B item 15')

# =====================================================================
# 5. Part D — mark the Phase 1 result bullets superseded.
# =====================================================================
sub("""- **Chained CAGR post-fix: mean 14.17%, median 14.82%, only 1/5 of the latest
  seed batch clears 15%.**""",
    """- **SUPERSEDED 2026-08-22 (look-ahead, Part E item 26) — expect lower.**
  **Chained CAGR post-fix: mean 14.17%, median 14.82%, only 1/5 of the latest
  seed batch clears 15%.**""",
    'part D cagr bullet')

sub("""- **Chained Max DD remains ~28-36% across all 8 seeds tested — never got
  under even the loosened 20% fallback ceiling, let alone the original
  15-20% target.**""",
    """- **PARTLY SUPERSEDED 2026-08-22 (look-ahead, Part E item 26).** The
  drawdown numbers were produced under contaminated entry timing, so the
  magnitudes will move. The *structural* diagnosis below (multi-year loss
  clustering reproducible across every seed) is unlikely to be an artifact of
  the bug, because the bug flattered entries and so if anything MASKED
  drawdown rather than manufacturing it — but that is reasoning, not a
  measurement, and the re-run should confirm it.
  **Chained Max DD remains ~28-36% across all 8 seeds tested — never got
  under even the loosened 20% fallback ceiling, let alone the original
  15-20% target.**""",
    'part D dd bullet')

# =====================================================================
# 6. Part E — the new items.
# =====================================================================
NEW_ITEMS = r'''
---

### 2026-08-22 — LIVE/BACKTEST RECONCILIATION AUDIT (items 26-31)

Six items landed at once because they came from one deliberate exercise:
reading `wfo_engine_updated.py` and `live_pipeline.py` side by side and asking
"where do these two disagree?" rather than waiting for a symptom. Phase 2's
whole premise is that live executes the system the backtest validated, so every
divergence between them is either a live bug or a backtest lie. Two were
backtest lies (26, 28), two were live divergences (27, 29), and two are
operational decisions the findings force (30, 31).

Ordering discipline for the fixes: **26 alone first**, then re-run and read the
numbers, because 27-29's magnitudes are only worth quantifying against
corrected numbers rather than contaminated ones.

26. **LOOK-AHEAD BIAS in the Sniper entry path — the most consequential defect
    found in this project.** Every Sniper number in Phase 1 was produced with
    it, and every live Sniper fill through 2026-08-22 was taken under it.

    **What it was.** `coiled_alpha_logic.py`'s docstring stated the convention
    "signal at close(t) -> intended execution at open(t+1)" — but no code
    anywhere implemented it. Both consumers filled Sniper entries at `OPEN(t)`
    while reading `BB_Enter_Today`, `Target_ATR`, `RS_Percentile` and
    `ATR_Contraction_Ratio` computed from `CLOSE(t)` and `HIGH(t)`/`LOW(t)` of
    that **same bar** (`wfo_engine_updated.py`'s Sniper entry block;
    `live_pipeline.py` line ~394 filtering on `r.get('BB_Enter_Today')` and
    line ~416 setting `'entry_price': row['OPEN']`). The fill price therefore
    preceded the information that justified it. The docstring made this
    genuinely hard to spot: it read like a spec that had been implemented.

    **Why it flatters the strategy specifically, not just generically.** The
    Sniper selects for high relative strength plus volatility compression —
    names primed to break out. Filling at the open of the very bar that
    confirms the breakout systematically buys before the move it is selecting
    on. And `Target_ATR` came from the same unseen bar, so the stop distance,
    the target distance AND the risk-based share count were all sized off
    information the strategy could not have had.

    **How it was confirmed** (`test_lookahead.py`, 5 tests, all passing —
    reproduced before any fix was written). The test extracts the real
    production `run_headless_simulation` by source-parsing
    `wfo_engine_updated.py` and injecting a probe, so it tests shipped code
    rather than a reimplementation. Evidence:
    - *Test A*: perturbing **only** `CLOSE(t)` flips whether the engine takes
      a trade at `OPEN(t)` — direct proof of information flowing backwards.
    - *Test B*: every position the engine naturally opened (4/4) filled at the
      OPEN of a bar that was itself the signal bar.
    - *Test D*: a bare `.shift()` would leave NaN on each symbol's first bar,
      and `bool(float('nan')) is True` in Python — so the engine's
      `if r['BB_Enter_Today']` truthiness test reads NaN as a **valid entry
      signal**. Measured: 24/24 first bars NaN -> 24 phantom trades, one per
      listed symbol, silently. This is why the fix uses
      `shift(1, fill_value=False)` rather than `shift().fillna(False)` — the
      NaN is never created, so the trap is unrepresentable rather than patched.
    - *Test E*: on synthetic data the honest fill was worse by mean +0.585% /
      median +0.620% per entry, worse 65.1% of the time. **Synthetic
      magnitude, not a forecast for the real panel** — run
      `measure_lookahead_bias.py` for that.

    An earlier version of this test used a hand-engineered "hero" symbol and
    failed with `KeyError: 'HERO'` because the forced up-day inflated
    `True_Range`, pushed `ATR_Contraction_Ratio` above 1.0 and broke
    `Sniper_Pass_VolContraction` — the up-day defeated its own signal. Worth
    remembering: in this system you cannot force a signal by making a bar big.
    The fixture was abandoned for a property test over whatever the engine
    naturally does, which is a stronger test anyway.

    **The fix, and why it lives where it does.** New section 5b in
    `coiled_alpha_logic.py` lags exactly those four columns by one bar per
    SYMBOL, leaving `OPEN(t)` as the fill price. It went in
    `coiled_alpha_logic.py` and **not** `data_prep_updated.py` for a decisive
    reason: `live_pipeline.py` calls `apply_coiled_alpha_logic` directly and
    never runs data_prep, so fixing data_prep would have corrected the
    backtest while leaving live contaminated — recreating the exact class of
    live/backtest divergence this audit exists to remove.

    **Zero engine edits required**, verified deliberately: those four columns
    are the only ones the Sniper entry block reads, and they are read nowhere
    else. This matters because `run_headless_simulation` is duplicated across
    several files, and every hand-edit to it is a drift risk.

    **What is NOT lagged, and why.** The MR sleeve is untouched.
    `MR_Base_Signal` fires on close(t) and the engines fill it at **CLOSE(t)**
    — a market-on-close convention that is internally consistent and actually
    implementable. Lagging it would make the sleeve a full day late on a 1-3
    day mean-reversion bounce, i.e. would break a working sleeve to fix a bug
    it does not have. `BB_Exhaustion_Today` is likewise close(t) -> close(t)
    and left alone. Verified bit-identical before and after.

    **Verified by `test_fix_verification.py` (5 tests, passing).** The
    blast-radius test asserts the set of columns that differ between
    `lag_sniper_decision_inputs=False` and `True` is **exactly**
    `['ATR_Contraction_Ratio', 'BB_Enter_Today', 'RS_Percentile',
    'Target_ATR']` — all 35 other columns bit-identical. Post-fix, every fill
    lands on the bar AFTER the signal, with the stop sized off the signal
    bar's ATR (4/4 positions had materially different ATR on the two bars,
    confirming the sizing effect is real and not rounding).

    **STATUS: fix written and unit-verified; NOT yet measured or re-run on the
    real panel.** Nothing in this item restates the Phase 1 numbers. Sequence:
    (a) `measure_lookahead_bias.py` (seconds, then `--stage2` for minutes) to
    learn the sign and rough size cheaply; (b) re-run `data_prep_updated.py`
    so the stored V9 parquet is correct on disk; (c) one seed of
    `wfo_engine_updated.py` end-to-end and read the chained CAGR/DD. Step (a)
    does **not** need a data_prep re-run: verified by inspection that data_prep
    never writes to those four columns after calling
    `apply_coiled_alpha_logic` (it only lists them in `columns_to_keep`), so
    lagging them post-hoc on the existing parquet is exactly equivalent to
    regenerating it — saving the raw download and yfinance fetch.

27. **Live/backtest divergence: allocation rebalance ran in the wrong place.**
    The engine's per-day order is idle yield -> regime hot-swap -> **allocation
    rebalance** -> Sniper exits -> MR exits -> MR entries -> Sniper entries.
    `live_pipeline.py` had the rebalance buried inside `evaluate_entries()`,
    i.e. running *after* exits.

    **Why this is not cosmetic.** `bb_equity` is a running sleeve balance, not
    a mark-to-market — it moves only on yield, rebalance and *realized*
    profit. So an exit's realized P&L lands in `bb_equity` before a
    post-exit rebalance sees it, and `target_bb_equity` is then computed off a
    different base. That base feeds all three Sniper sizing paths (risk-based
    shares, the 20% concentration cap, `gap_safe_shares`) plus the `bb_cash`
    affordability check.

    **FIX**: extracted `rebalance_allocation(state, today_regime,
    current_breadth)` out of `evaluate_entries` and called it from `main()`
    before `evaluate_exits`. Live conforms to the engine, not the reverse —
    the engine is the reference implementation the Phase 1 parameters were
    fitted against.

    **VALIDATED behaviourally**, not just structurally
    (`test_ordering_fix.py`): one position gapping through its target plus one
    new signal the same day, identical prices and params both ways — the old
    ordering bought **382** shares, the engine ordering **388** (1.5%
    difference), because the old path rebalanced off a base that already
    contained the exit's profit. Live was demonstrably taking
    different-sized trades than the backtest that validated its parameters.

28. **CAGR annualization units bug in `calculate_fitness()` — affects
    parameter SELECTION, not just reporting.** `days = len(eq_curve)` counts
    **trading** days (one append per entry in `calendar_dates`), but the
    annualization used `365.25 / days`. So a 252-day year was treated as
    365.25 days long and every per-window CAGR was raised to the power
    365.25/252 = **1.4494**. Measured (`test_cagr_units.py`): a true 5% prints
    as 7.33%, 10% as 14.81%, 14.17% as 21.18%, 20% as 30.25%, 30% as 46.27%.
    The distortion is a constant exponent, independent of window length
    (verified across 1/2/3-year windows).

    **Why it is not merely cosmetic.** Fitness uses `sortino =
    (cagr/100)/downside_std` with `norm_sortino = min(sortino/3.0, 1.0)`.
    Inflating CAGR pushes candidates **into** that cap, where the
    risk-adjusted term stops discriminating and selection falls through to
    profit factor / win rate / trade count. `test_cagr_units_selection.py`
    constructs a worked pair where the two formulas disagree: buggy picks A
    (0.8815 vs 0.8595), fixed picks B (0.8228 vs 0.8595). Exposure band: for
    downside deviation 10-15%, which is ordinary for this strategy, the
    at-risk true-CAGR range is roughly 19.8-30% up to 29.2-45%.
    **Honest scope limit**: that is a constructed existence proof. It does
    **not** show selection actually changed in any of the 14 real windows —
    only a re-run can show that. A companion attempt to produce a flip from
    two realistic candidates was **inconclusive** (both saturated the cap
    under both formulas) and is reported as such rather than dressed up.

    **What is NOT affected: the 14.17% / −29.96% headline.** The chained-CAGR
    block in section 6 of the same file already used `days/252` and was always
    correct — the two blocks silently disagreed with each other. Verified by
    feeding the chained block exactly 14.17% and confirming it reports 14.17%.
    What IS affected: every `OOS_CAGR`/`Fit_CAGR`/`Val_CAGR` value in the
    stored WFO CSV, the `Average OOS CAGR` / `Median OOS CAGR` summary lines,
    and potentially which parameters were selected.

    **Knock-on: it invalidates a documented explanation.** Part B item 15
    attributed the ~4pp per-window-vs-chained gap to volatility drag, using
    numbers from these two mutually-inconsistent code paths. See the
    correction inline there. `test_window_gap_decomposition.py` shows the
    units bug alone forces a gap of **at least +5.71pp**, larger than the
    +3.97pp actually published — so the published pair cannot both come from
    one coherent run, and is not evidence of anything.

    **FIX**: `apply_fixes.py --fix5`. Numerically verified. **Decide
    deliberately whether to apply it before or after the item 26 re-run** — if
    before, the re-run's selection is correct but the new numbers reflect two
    changes at once and the two effects cannot be separated afterwards.

29. **OPEN — the backtest accrues idle yield; live does not.** The engine
    credits `idle_yield` (6%/yr in the standard param set) on uninvested sleeve
    cash every day, before the rebalance. `live_pipeline.py` has no yield
    accrual at all. Since the Sniper sleeve is frequently far from fully
    deployed, this is a persistent, compounding difference in the same
    direction, and it inflates backtest CAGR relative to what live can produce.

    **DECISION REQUIRED — not a mechanical fix.** Either add yield to live (and
    then it must go *before* `rebalance_allocation`, matching the engine) or
    strip it from the backtest. Current lean is to **strip it from the
    backtest** as the more conservative direction — a paper account earns no
    interest, and a live one only earns it if the cash is actually parked in a
    liquid fund, which is an operational commitment rather than an assumption.
    Note the cost: stripping it recalibrates every CAGR number again, so it is
    best decided *before* the item 26 re-run to avoid running the whole thing
    twice.

30. **OPEN — the paper-trading state file contains fills taken under both
    defects. Decision required before it is used as a performance record.**
    `state/paper_portfolio_state.json` is the git-committed single source of
    truth, and the pipeline has been running daily against it. The 3 Sniper
    positions opened on the first live run (2026-08-17) were entered at
    look-ahead prices with look-ahead stops and targets, and every day since
    has also rebalanced in the wrong order (item 27). Two clean options:
    **(a)** reset the state file and restart paper trading from the corrected
    code, losing the short history but yielding a record that means something;
    **(b)** keep it and write a dated discontinuity marker into the file plus
    this changelog, so the pre-fix segment is never silently averaged together
    with the post-fix segment. **Do not leave this undecided** — the whole
    point of the paper phase is a trustworthy record, and a mixed one is worse
    than a short one.

31. **OPEN (small) — `SETUP_GUIDE.md` §4 path text does not match
    `generate_live_params.py`'s actual expectations.** Deliberately deferred
    until the items above settle, since it is documentation plus a guard
    rather than a correctness bug. When picked up: fix the guide's text AND add
    an explicit path/environment check to the script so a wrong path fails
    loudly at startup instead of part-way through a fit.
'''

sub("""    coming out of the API — confirms the general lesson (always explicitly
    normalize date/time handling at the exact point external data enters the
    pipeline; don't rely on a particular source's incidental formatting).""",
    """    coming out of the API — confirms the general lesson (always explicitly
    normalize date/time handling at the exact point external data enters the
    pipeline; don't rely on a particular source's incidental formatting).
""" + NEW_ITEMS,
    'part E new items')

# =====================================================================
# 7. Closure summary — add the missing header the top of the file promises,
#    and mark the numbers superseded.
# =====================================================================
sub("**Final honest numbers (5-seed post-fix batch, current code)**:",
    """## PHASE 1 CLOSURE SUMMARY

> **SUPERSEDED 2026-08-22.** Everything in this section was measured with the
> look-ahead bias of Part E item 26 active. The numbers below are an upper
> bound on the real system's Phase 1 performance, not a result. They are kept
> verbatim rather than deleted, because the *decision* they justified (stop
> iterating on the backtest, get to live infrastructure) is still the right
> call — arguably more so now, since the defect that most needed finding was
> found by reconciling live against backtest, which is exactly what Phase 2 is
> for and what no amount of further backtest tuning would have surfaced.

**Final honest numbers (5-seed post-fix batch, current code)**:""",
    'closure summary header')

# =====================================================================
if args.out:
    open(args.out, 'w', encoding='utf-8').write(src)
    print(f"Wrote preview to {args.out} (original untouched).")
    print(f"Review with:  diff -u {path} {args.out} | less")
else:
    open(path, 'w', encoding='utf-8').write(src)
    print(f"Updated {path}")

print("""
Applied 7 edits:
  - STATUS block         : Phase 1 headline flagged SUPERSEDED
  - Files in this build  : audit's test/tool files listed
  - Part A item 1        : column contract amended (four columns now lagged)
  - Part B item 15       : volatility-drag quantification withdrawn, with the
                           arithmetic that withdraws it
  - Part D               : CAGR bullet superseded, DD bullet partly superseded
  - Part E               : new items 26-31 + audit preamble
  - Closure summary      : missing section header added, numbers superseded

Items 29, 30 and 31 need a DECISION from you, not a code change. Item 30 is the
time-sensitive one: the live pipeline is still writing to the paper state file
on every run, so the mixed-record problem grows until it is settled.""")
