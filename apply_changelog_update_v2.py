"""
apply_changelog_update_v2.py — Janus, session 2026-08-22 (second batch)
======================================================================
Second changelog patch. Records findings 32-40, folds in dell's two decisions,
and closes items 29 and 30.

WHY A SECOND SCRIPT RATHER THAN EDITING apply_changelog_update.py
    That script's idempotency sentinel is item 26's heading, so on a changelog
    it has already patched it exits early and does nothing — which is correct
    behaviour for it and useless for this update. Its anchors are also written
    against the PRE-item-26 text, so extending it would mean maintaining two
    sets of anchors for two different input states in one file.

    More importantly: apply_changelog_update.py is the record of what the FIRST
    pass found. Item 29 there describes idle yield as "6%/yr in the standard
    param set", which was true when it was written. Rewriting that line in the
    v1 script would make the record say the first pass knew something it did
    not. The supersession belongs in the new text, not in a retro-edit of the
    old. So v1 is left byte-for-byte alone.

ORDER
    Run apply_changelog_update.py FIRST. This script refuses to run otherwise
    and tells you so, rather than half-patching a file whose shape it does not
    recognise.

USAGE
    python apply_changelog_update_v2.py --out /tmp/dryrun    # writes a copy
    python apply_changelog_update_v2.py                      # in place
    python apply_changelog_update_v2.py --dir /path/to/janus-alpha
    python apply_changelog_update_v2.py --file ENGINEERING_CHANGELOG_updated.md
"""

import argparse
import os
import shutil
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--dir', default='.', help='repo directory holding the changelog')
ap.add_argument('--file', default='ENGINEERING_CHANGELOG.md',
                help='changelog filename inside --dir')
ap.add_argument('--out', default=None,
                help='dry run: write the patched copy into this directory instead '
                     'of editing in place')
args = ap.parse_args()

PATH = os.path.join(args.dir, args.file)

# Unique to THIS patch's own edit. Not a token any other script writes -- the
# fix5 sentinel collision (item 38 below) was exactly this mistake: a guard
# that tested for a string another script also introduced, and so silently
# skipped its own work.
SENTINEL = '32. **MACRO-GATE LOOK-AHEAD in the Sniper allocation and slot gates'

# What v1 must already have written, or this script's anchors do not exist.
PREREQ = '26. **LOOK-AHEAD BIAS in the Sniper entry path'

if not os.path.exists(PATH):
    sys.exit(f"ERROR: {PATH} not found. Point --dir at the repo root, or pass "
             f"--file if the changelog has a different name.")

with open(PATH, encoding='utf-8') as f:
    src = original = f.read()

if SENTINEL in src:
    print(f"{PATH}: items 32-40 already present -- nothing to do.")
    sys.exit(0)

if PREREQ not in src:
    sys.exit(f"ERROR: {PATH} does not contain Part E item 26, so the first "
             f"changelog patch has not been applied. Run\n"
             f"    python apply_changelog_update.py --dir {args.dir}\n"
             f"first. This script's anchors are written against that script's "
             f"output; applying it now would produce a changelog with items 32-40 "
             f"referring to items 26-31 that are not there.")


def sub(old, new, label):
    """Exact-string replacement that refuses to guess.

    A count of 0 means the changelog has drifted from the version this patch
    was written against; a count above 1 means the anchor is not specific
    enough and the patch would land somewhere arbitrary. Either way, stop and
    reconcile by hand rather than forcing it.
    """
    global src
    n = src.count(old)
    if n != 1:
        sys.exit(f"ERROR [{label}]: anchor matched {n} times, expected exactly 1.\n"
                 f"  anchor: {old[:90]!r}...\n"
                 f"  The changelog has drifted from the version this patch was "
                 f"written against. Reconcile by hand.")
    src = src.replace(old, new, 1)
    print(f"  applied: {label}")


def replace_between(start, end, new, label):
    """Replace everything from `start` up to (not including) `end`.

    Used for the two items being rewritten wholesale. Anchoring on a dozen
    lines of exact prose is brittle for no benefit -- one reflowed line and the
    patch dies. Anchoring on the two item headings is precise and survives
    edits to the bodies in between.
    """
    global src
    for marker, which in ((start, 'start'), (end, 'end')):
        n = src.count(marker)
        if n != 1:
            sys.exit(f"ERROR [{label}]: {which} marker matched {n} times, "
                     f"expected 1.\n  marker: {marker[:90]!r}")
    i = src.index(start)
    j = src.index(end)
    if j <= i:
        sys.exit(f"ERROR [{label}]: end marker precedes start marker. The items "
                 f"have been reordered; reconcile by hand.")
    src = src[:i] + new + src[j:]
    print(f"  applied: {label}")


print(f"Patching {PATH}\n")

# ======================================================================
# 1. The supersession warning at the top. It currently blames item 26 alone
#    and says two items await a decision. Both statements are now wrong: item
#    32 is a SECOND, independent look-ahead in the same execution path, and
#    the decisions have been made. A reader who acts on the old text would
#    under-estimate what the re-run has to undo.
# ======================================================================
# The anchor runs to the end of a source line AND the replacement ends with the
# same trailing fragment ("**The 14.17% CAGR /"), so the line that follows it in
# the original continues to read correctly. Ending the replacement anywhere else
# leaves an orphaned short line in a file wrapped at 79. The fragment also keeps
# the U+2212 minus sign and em dash on the next line out of the anchor, where a
# transcription slip would silently mean a zero-count match.
sub("""> A live/backtest reconciliation audit found a **look-ahead bias in the Sniper
> entry path** (Part E item 26) that was present in every Phase 1 backtest and
> in every live Sniper fill up to and including 2026-08-22. **The 14.17% CAGR /""",
    """> A live/backtest reconciliation audit found **two independent look-ahead
> biases in the Sniper entry path** (Part E items 26 and 32), both present in
> every Phase 1 backtest and in every live Sniper fill up to and including
> 2026-08-22. **The 14.17% CAGR /""",
    'top warning — name both look-aheads')

sub("""> figure in Parts B/C/D and in the closure summary as an upper bound, not a
> result. The same audit found four smaller defects (items 27–31), two of which
> need a decision from you rather than a code change.""",
    """> figure in Parts B/C/D and in the closure summary as an upper bound, not a
> result.
>
> Item 26 is per-stock (entry signal, stop distance, position size); item 32 is
> market-wide (how much capital the sleeve got and how many positions it was
> allowed to hold at all). Fixing 26 alone leaves the second one running.
>
> The audit ran in two passes. Items 26-40 break down as **ten defects in the
> traded system** (26, 27, 28, 29, 32, 33, 34, 35, 36, 37), **three in the
> audit tooling** built to check it (38, 39, 40), one operational consequence
> that needed a decision from you (30), and one deferred documentation fix
> (31). If you read only one, read **34**: it is a selection defect in the
> script that writes the parameters live actually trades.
>
> All thirteen defects are fixed and unit-verified. **Nothing has been applied
> to the repo, the WFO re-run has not been done, and the paper state has not
> been reset** — see `RUNBOOK_2026-08-22.md` for the order and for what each
> step should and should not produce.
>
> The two items that needed a decision from you are closed: idle yield goes in
> **both** engine and live at a true **4%/yr** (29), and the paper-trading
> state is **reset clean** (30).""",
    'top warning — honest counts, decisions closed')

# ======================================================================
# 2. File inventory.
# ======================================================================
sub("""- `test_window_gap_decomposition.py` — shows item 15's "~4pp volatility drag"
  gap is not a valid measurement""",
    """- `test_window_gap_decomposition.py` — shows item 15's "~4pp volatility drag"
  gap is not a valid measurement

Added by the second pass (items 32-40):
- `apply_fixes_v2.py` — the second batch of code fixes: `--macro-lag`,
  `--idle-yield`, `--run-guard`, `--sheets`, `--live-params`. Same contract as
  `apply_fixes.py` (exact-string replacement, assertions, idempotent, nothing
  applied by default)
- `apply_changelog_update_v2.py` — applies this changelog update
- `reset_paper_state.py` — archives the contaminated paper state and writes a
  clean one; reads the required state keys out of `live_pipeline.py` rather
  than hardcoding them
- `engine_harness.py` — shared loader for the engine's functions, reading the
  engine's module-level constants instead of restating them (item 39)
- `make_fake_v9.py` — builds a synthetic V9-shaped panel so the measurement
  and test scripts can be exercised without the real 15-year parquet
- `run_measure_test.py` — runs `measure_lookahead_bias.py` against that panel
- `test_macro_lag.py` — proves the macro gates are lagged per DATE, not per
  SYMBOL, and that the NaN-truthy trap is closed
- `test_yield_and_guard.py` — the idle-yield units fix and the duplicate-run
  guard
- `test_sheets_payload.py` — every Sheets payload must survive `json.dumps`
- `test_engine_copy_parity.py` — proves `generate_live_params.py`'s embedded
  engine copy matches `wfo_engine_updated.py` (item 34)
- `test_macro_gate_measure.py` — tests the MEASUREMENT, including its sign
  convention, against three panels whose answer is known by construction
- `test_reset_state.py` — pushes the freshly-written clean state through the
  real `live_pipeline.py` call sequence, not a mock
- `test_patch_order_independence.py` — runs both patch scripts in both orders
  and asserts fingerprints, compilation and idempotency (item 38)
- `RUNBOOK_2026-08-22.md` — the ordered apply/re-run/redeploy path with the
  result each step should and should not produce""",
    'file inventory — second-pass files')

# ======================================================================
# 3. The audit preamble. "Six items landed at once" is now the description of
#    the first pass only.
# ======================================================================
sub("""Six items landed at once because they came from one deliberate exercise:
reading `wfo_engine_updated.py` and `live_pipeline.py` side by side and asking
"where do these two disagree?" rather than waiting for a symptom. Phase 2's
whole premise is that live executes the system the backtest validated, so every
divergence between them is either a live bug or a backtest lie. Two were
backtest lies (26, 28), two were live divergences (27, 29), and two are
operational decisions the findings force (30, 31).

Ordering discipline for the fixes: **26 alone first**, then re-run and read the
numbers, because 27-29's magnitudes are only worth quantifying against
corrected numbers rather than contaminated ones.""",
    """Six items landed at once because they came from one deliberate exercise:
reading `wfo_engine_updated.py` and `live_pipeline.py` side by side and asking
"where do these two disagree?" rather than waiting for a symptom. Phase 2's
whole premise is that live executes the system the backtest validated, so every
divergence between them is either a live bug or a backtest lie. Two were
backtest lies (26, 28), two were live divergences (27, 29), and two are
operational decisions the findings force (30, 31).

Ordering discipline for the fixes: **26 alone first**, then re-run and read the
numbers, because 27-29's magnitudes are only worth quantifying against
corrected numbers rather than contaminated ones.

> **AMENDED after the second pass.** That ordering advice is superseded by
> items 32 and 34. Item 32 is a second look-ahead in the same execution path,
> so "26 alone first" would have produced a re-run that was still
> contaminated — a number that looks like a result and is not one. The revised
> grouping is: apply every fix that changes backtest behaviour (26, 32, 28, 35)
> in one batch, then re-run ONCE. See `RUNBOOK_2026-08-22.md`.
>
> Worth recording why the first pass stopped at six. It compared the engine
> against the live pipeline, which is a good lens and a partial one: it can
> only surface defects where the two files DISAGREE. Item 32 was invisible to
> it because both files had the identical macro-gate timing bug, and two files
> that are wrong in the same way reconcile perfectly. Item 34 was invisible
> because `generate_live_params.py` was not in the comparison at all. The
> second pass found them by reading each file against the EXECUTION MODEL
> ("this value is consumed at OPEN(t), so when was it knowable?") rather than
> against its counterpart.""",
    'audit preamble — why the first pass stopped at six')

# ======================================================================
# 4. Item 29 -> resolved.
# ======================================================================
replace_between(
    '29. **OPEN — the backtest accrues idle yield; live does not.**',
    '30. **OPEN — the paper-trading state file contains fills taken under both',
    """29. **RESOLVED (dell's decision, 2026-08-22: "Both, at 4%") — the backtest
    accrued idle yield and live accrued none.** The engine credited
    `idle_yield` on uninvested sleeve cash every simulated day, before the
    rebalance; `live_pipeline.py` had no accrual at all. Since the Sniper
    sleeve is frequently far from fully deployed, this was a persistent,
    compounding, one-directional difference that inflated backtest CAGR
    relative to anything live could produce.

    **DECISION: keep yield in the backtest AND add it to live, both at a true
    4.0%/yr.** The reasoning behind the earlier lean toward stripping it was
    that a paper account earns no interest. That is true of the paper account
    and not of the strategy: idle cash in a real deployment of this system
    would sit in a liquid fund, and modelling it as earning nothing understates
    Sniper's opportunity cost of holding cash, which is one of the things the
    allocation gates exist to trade off. Both sides now model the same
    operational commitment, so the two are comparable, which was the actual
    problem. 4% rather than 6% because it is the conservative end of Indian
    liquid-fund yields and because — see item 36 — the "6%" in the Phase 1
    param set was never delivering 6% anyway.

    In live it is credited **before** `rebalance_allocation`, matching the
    engine's simulation order (yield → breadth read → rebalance → exits →
    entries). Order matters here: yield accrued after the rebalance would be
    allocated on the wrong sleeve balances.

    **FIX**: `apply_fixes_v2.py --idle-yield` (both files). Verified by
    `test_yield_and_guard.py` and again by `test_reset_state.py`, which asserts
    the credited amount equals one session at 4%/252 *and* is not the old
    6%/365 figure — asserting only the former would pass under a fix that
    silently kept the old basis when the two happened to be close.

    **Cost, stated plainly**: this recalibrates every CAGR number again, on top
    of items 26, 32 and 28. That is why all four go into one re-run.

""",
    'item 29 -> RESOLVED (both, at 4%)')

# ======================================================================
# 5. Item 30 -> resolved.
# ======================================================================
replace_between(
    '30. **OPEN — the paper-trading state file contains fills taken under both',
    '31. **OPEN (small) — `SETUP_GUIDE.md` §4 path text does not match',
    """30. **RESOLVED (dell's decision, 2026-08-22: "Reset and restart clean") —
    the paper-trading state file contained fills taken under four separate
    defects.** `state/paper_portfolio_state.json` is the git-committed single
    source of truth and the pipeline had been running daily against it. What
    was wrong with it:

    - the 3 Sniper positions opened on the first live run (2026-08-17) were
      entered at look-ahead prices, with stop distances and share counts sized
      off the same unseeable bar (item 26) — so entry price, risk and size are
      all contaminated, and the open P&L is not a number that means anything;
    - every day since had rebalanced in the wrong order (item 27);
    - macro gates were read same-bar and `VIX_Spike` was hardcoded `False`
      (items 32, 35), so the slot cap and capital share were both wrong;
    - idle yield accrued at nothing in live while the backtest it is compared
      against accrued at a 6%/365 basis (items 29, 36).

    **DECISION: reset.** Option (b) — keep it with a discontinuity marker —
    was rejected because a marker only helps a reader who is looking for it,
    and the segment being marked is four days long. There is nothing of value
    to preserve on one side of the boundary and a real risk of it being
    averaged into the other.

    **FIX**: `reset_paper_state.py`. It archives the existing file verbatim to
    `state/archive/paper_portfolio_state.<UTC>.contaminated.json` before
    writing a clean one — worthless as performance data, useful as evidence
    for deciding whether some future bug is new or was always there.

    What it deliberately does **not** do is "repair" the old state by
    re-pricing entries at `OPEN(t+1)` and recomputing stops. That would be
    inventing history: the honest position set is not the contaminated one at
    different prices, because different entries would have consumed different
    cash and therefore permitted a different set of later entries. There is no
    local fix to a path-dependent simulation.

    Two design points worth knowing before running it:

    - it derives the required state keys by **reading `live_pipeline.py`**
      rather than hardcoding a list, so adding a state key to the pipeline
      cannot silently produce an incomplete reset. The failure it is guarding
      against is a `KeyError` at 16:00 IST inside a GitHub Action, where the
      first symptom is no Telegram message at all. `test_reset_state.py`
      proves the check has teeth by sabotaging the pipeline to read an
      unwritten key and asserting the reset refuses;
    - `last_run_date` is written as `''` on purpose. Both consumers document
      that case (`is_new_trading_date` returns True, `trading_days_since`
      returns 1), so the first run after a reset accrues exactly one session of
      yield and is not blocked by the item 33 guard.

    **Status: decided and scripted, NOT yet run.** Running it is step 6 of the
    runbook, after the fixes are deployed — resetting before the fixed code is
    live would just start accumulating a second contaminated segment.

""",
    'item 30 -> RESOLVED (reset clean)')

# ======================================================================
# 6. Items 32-40.
# ======================================================================
NEW_ITEMS = """    loudly at startup instead of part-way through a fit.


---

### 2026-08-22 (second pass) — EXECUTION-MODEL AUDIT (items 32-40)

The first pass compared two files against each other. This one compared each
file against the **execution model**: for every value the Sniper sleeve
consumes, when was that value knowable? The Sniper fills at `OPEN(t)`, so
anything it reads must be as of `close(t-1)`. The MR sleeve fills at
`row['CLOSE']` (market-on-close), so same-bar reads there are legitimate. That
asymmetry is the single most important fact about this codebase and it is why
"lag everything" is as wrong as "lag nothing".

Items 32-37 are defects in the traded system. Items 38-40 are defects in the
audit tooling built to check it — recorded at equal weight on purpose, because
a broken measurement does not announce itself: it produces a plausible number
with a confident sentence attached, and the first pass shipped exactly that.

32. **MACRO-GATE LOOK-AHEAD in the Sniper allocation and slot gates. Fixed;
    invalidates the same numbers item 26 does.** `apply_fixes.py --fix1`
    lagged the four **per-stock** Sniper decision inputs (`BB_Enter_Today`,
    `Target_ATR`, `RS_Percentile`, `ATR_Contraction_Ratio`) and left the four
    **market-wide** gates — `Market_Breadth`, `Regime_Label`, `VIX_Spike`,
    `Systemic_Panic` — reading bar t's own close. fix1 was therefore
    incomplete, and in the most misleading possible way: the obvious
    look-ahead was fixed, so the path looked audited.

    What those gates control, read from `wfo_engine_updated.py`:

    ```
    slot cap  (line 233/246)  0 if VIX_Spike
                              6 if breadth > 0.65
                              3 if breadth >= 0.50
                              1 otherwise
    capital   (lines 150-156) BULL: 0.80/0.20 if breadth > 0.65
                                    0.60/0.40 if breadth >= 0.50
                                    0.35/0.65 otherwise
                              BEAR: 0.20/0.80 fixed
    ```

    So the contaminated engine decided how much capital Sniper got, and how
    many positions it could hold, using a breadth reading that included the
    very day's move. Breadth is a count of stocks above their moving average,
    which means it is mechanically high on up days. The sleeve was therefore
    sized largest, with the most slots, on precisely the days it was about to
    make money.

    **Lagged per DATE, not per SYMBOL.** These are market-wide scalars.
    `groupby("SYMBOL").shift(1)` would hand a thinly-traded stock an older
    day's breadth than its liquid neighbour, because that stock has fewer rows
    in the panel — a subtler and harder-to-find bug than the one being fixed.
    `test_macro_lag.py` asserts every symbol on a given date sees the same
    macro values.

    **The NaN-truthy trap.** `bool(float('nan')) is True`, so a plain
    `shift(1)` on `VIX_Spike` turns row 0 into a spike and zeroes the slot cap
    on the first bar of every window. `shift(1, fill_value=False)` — fail
    safe, in the direction of trading normally rather than sitting out. Also
    note `Regime_Label` must be cast to `str` before shifting: `shift(1)` on a
    categorical yields NaN, and filling it with a value outside the category
    set raises.

    **Only TIER changes matter.** Breadth 0.71 → 0.69 changes nothing;
    0.66 → 0.64 halves the slot cap. Counting how much the raw value moved
    when lagged is the wrong measurement and would wildly overstate the
    exposure. `measure_lookahead_bias.py` Stage 1b counts tier transitions and
    the resulting slot/capital deltas, and reports base rates alongside them so
    that "0 changes" is distinguishable from "this gate never fires on this
    panel" — two very different statements that the first draft printed
    identically.

    **FIX**: `apply_fixes_v2.py --macro-lag`. It also collapses the duplicated
    macro block — the same computation existed independently in
    `data_prep_updated.py` and `live_pipeline.py` — into one shared
    `compute_macro_regime()`. That de-duplication is not tidying: the
    duplication is what allowed item 35 to exist undetected.

    **AFFECTS BACKTEST AND LIVE. Needs the WFO re-run**, in the same batch as
    26, 28 and 35.

33. **No guard against re-processing an already-processed session. Fixed.**
    `state['last_run_date']` was written on every run and never read. Nothing
    stopped the pipeline from processing the same bhavcopy twice — a
    re-triggered GitHub Action, a manual run after a failure, a scheduled run
    on a day the exchange data had not rolled. Each duplicate pass would age
    MR positions an extra session toward their time stop, append a second
    `equity_curve_log` row for the same date, and (once item 29's fix lands)
    credit a second day of idle yield.

    This was not hypothetical. `reset_paper_state.py` reports duplicate dates
    in `equity_curve_log` before archiving, precisely so the question "did this
    actually bite?" is answered from the file rather than assumed either way.

    **FIX**: `apply_fixes_v2.py --run-guard`. Exits cleanly (not with an error)
    when `last_run_date` already equals the target date, and treats an empty
    `last_run_date` as a fresh state that should proceed. **Apply this BEFORE
    `--idle-yield` reaches production**, or the first duplicate run
    double-accrues yield with nothing to stop it.

34. **`generate_live_params.py` carried its own drifted copy of the engine, and
    it is the script that writes the parameters actually traded. Fixed.** The
    file embeds a duplicate of `run_headless_simulation` and
    `calculate_fitness` rather than importing them, so it received none of the
    2026-08-22 fixes: not the look-ahead lags, not the CAGR units fix (item
    28), not the idle-yield fix.

    This is the most consequential item in either pass, and the easiest to
    under-rate because it is phrased as code duplication. `live_params.json`
    is not a report — it is the Bull/Bear parameter set the live pipeline
    trades. A **selection** defect in this path does not produce a wrong number
    in a document; it produces the wrong parameters in production. The CAGR
    units bug inflates the fitness of high-volatility candidates specifically,
    so the live parameter set was chosen by a fitness function biased toward
    exactly the candidates that look best for a bad reason.

    It also explains why the first pass missed it: the reconciliation compared
    `wfo_engine_updated.py` with `live_pipeline.py`, and
    `generate_live_params.py` sits between them without being either.

    **FIX**: `apply_fixes_v2.py --live-params`, plus `test_engine_copy_parity.py`
    which asserts the embedded copy matches the engine and will fail the next
    time they diverge. The parity test is the durable half of this fix —
    patching the copy once solves today's problem, and a duplicate with no test
    holding it in place will drift again.

    **Consequence for the re-run: `generate_live_params.py` must be re-run and
    `live_params.json` regenerated.** Re-running the WFO without regenerating
    the live params would leave the fixed backtest validating a parameter set
    that was chosen by the unfixed selector.

35. **`VIX_Spike` was hardcoded `False` in the live pipeline. The volatility
    kill-switch was never armed in production.** `live_pipeline.py:239` set
    `macro['VIX_Spike'] = False` unconditionally, with a comment noting that
    `NIFTY_HIGH`/`NIFTY_LOW` were not being fetched in the "lean" live version.
    `data_prep_updated.py:109` computes it properly as
    `ATR_10 > ATR_Baseline_50 * 1.75`. The live pipeline then fed that constant
    `False` into the *exact* expression the engine uses for the slot cap
    (`live_pipeline.py:391`), where `VIX_Spike` is the term that sets
    `max_bb_pos = 0`.

    Consequence: the backtest was validated with a working volatility
    kill-switch and live was running with it permanently disabled. Of every
    gate to have inert in production, this is the worst one — it is the
    circuit-breaker whose entire purpose is to stop opening trend positions
    into a volatility expansion, i.e. it only ever matters on the days that
    matter.

    Note what this does to the item 32 measurement: on a panel where
    `VIX_Spike` never fires, lagging it changes nothing, and a measurement
    script that reported "0 changes" without reporting the base rate would have
    been read as "this gate is fine". It was not fine; it was absent.

    **FIX**: `apply_fixes_v2.py --macro-lag`, via the shared
    `compute_macro_regime()`. Fixing it required fetching the Nifty high/low
    columns in live, which is why the fix is bundled with the de-duplication
    rather than being a one-line change. **AFFECTS LIVE ONLY** — the backtest
    always computed this correctly.

36. **IDLE-YIELD UNITS BUG: the annual rate was divided by 365 and accrued
    only on trading days, so every Phase 1 run earned 69% of the stated
    rate.** `(idle_yield/100)/365` credited 252 times a year delivers
    252/365 = 69.0% of the annual figure in the parameter set. The Phase 1
    "6.0%" was really **4.23%/yr effective**. Nobody wrote 4.23% anywhere; the
    param set said 6.0 and the engine quietly paid less.

    Measured concretely on 600,000 of idle cash, to make the size legible:

    ```
    6.0% / 365  ->  98.6301 per session
    4.0% / 252  ->  95.2381 per session      difference 3.3920/session
    ```

    Which is the useful thing about this bug: the corrected 4% is worth almost
    exactly what the broken 6% was actually paying, so the headline effect of
    items 29+36 together is small (about −0.15pp on CAGR) even though the
    parameter moved by a third. A number that changed by 2 and an outcome that
    changed by 0.15 is the signature of a units bug, and it is why "we lowered
    the yield assumption from 6% to 4%" would be an actively misleading
    description of this change.

    **FIX**: `apply_fixes_v2.py --idle-yield` — divisor becomes
    `TRADING_DAYS_PER_YEAR` (252) so the stated rate means what it says, rate
    set to 4.0, and matching accrual added to live per item 29.

37. **LIVE REPORTING — three JSON-safety defects in the Google Sheets payload,
    found by serialising it rather than by reading it.** The new Trade_Log and
    enriched Open_Positions tabs carried `float('nan')` values and raw
    `numpy.float64` / `numpy.bool_` scalars, none of which survive
    `json.dumps`, which is what `gspread` does on the way out. The symptom
    would have been a live run that computed everything correctly and then died
    while reporting it — all the work done, nothing visible, at 16:00 IST.

    Filed as a defect in the traded system, not in the tooling: the bug is in
    `live_pipeline.py`'s payload builder. What the tooling contributed was
    finding it. `test_sheets_payload.py` now asserts `json.dumps` succeeds on
    every tab, and that single assertion found all three; no amount of
    re-reading the payload code had. Worth generalising: for a data structure
    crossing a boundary, test the boundary, not the structure.

38. **AUDIT TOOLING — `apply_fixes.py --fix5` could silently skip itself
    depending on the order the two patch scripts were run in. Reproduced and
    fixed.** `--fix5` guarded its idempotency with
    `if 'TRADING_DAYS_PER_YEAR' in src`. `apply_fixes_v2.py --idle-yield`
    introduces a module-level constant of exactly that name into the same file.
    So on a `v2`-first run, `--fix5` printed "already applied, skipping" and
    left the CAGR units bug in place — and item 28 is a *selection* bug, so
    the failure mode is a WFO that silently picks different parameters, with a
    reassuring "skipping" line in the log as the only trace.

    **The generalisable rule: an idempotency sentinel must be unique to the
    edit that writes it, not merely present in the file afterwards.** Every
    sentinel in both patch scripts was audited against that rule; `--fix5`'s
    was narrowed to a banner unique to its own edit. The sentinel in this
    changelog script is item 32's heading for the same reason.

    `test_patch_order_independence.py` now runs both scripts in both orders and
    asserts all 16 fix fingerprints present, all 9 bug fingerprints absent,
    every file compiles, and a second application changes nothing. It passes.
    Note it does **not** assert byte-identical output: the `lag_macro_gates`
    docstring and parameter land in a different position in
    `apply_coiled_alpha_logic`'s signature depending on order. Same behaviour,
    different bytes — asserting identity there would have meant either a
    failing test or contorting the patches to satisfy it.

39. **AUDIT TOOLING — the exec harness hardcoded the engine's constants, so
    the idle-yield fix broke every engine test at once. Fixed.**
    `wfo_engine_updated.py` runs the whole WFO at import time (module-level
    parquet read), so tests extract `run_headless_simulation`'s source text and
    `exec` it. Three separate test files had each hand-written the globals dict:

    ```
    ns = {'pd': pd, 'np': np, 'MAX_GAP_LOSS_PCT': 0.03,
          'ASSUMED_WORST_CASE_GAP_PCT': 0.20}
    ```

    Item 36's fix made the engine reference `TRADING_DAYS_PER_YEAR`, and all
    three failed with `NameError` — including
    `measure_lookahead_bias.py`, which is the first thing the runbook says to
    run. The hardcoded `0.03` and `0.20` were also copies of the engine's
    values, free to disagree with it silently.

    **FIX**: `engine_harness.py` reads every module-level literal constant out
    of the engine with `ast.literal_eval`. A new constant is picked up
    automatically and a changed value cannot diverge. Same principle as
    `reset_paper_state.py` reading its required keys from `live_pipeline.py`:
    **read the thing, do not restate it.** Assignments whose right-hand side is
    not a literal are skipped rather than guessed at, so the `NameError` says
    so plainly instead of the harness inventing a value.

40. **AUDIT TOOLING — the first draft of the item 32 measurement overstated
    its own result three separate ways. All three fixed before it was run on
    real data.** Recorded in full because this is the defect class most likely
    to recur and least likely to be noticed: the script produced
    self-consistent arithmetic wrapped in a confident, wrong conclusion.

    - **A fail-safe seed counted as a finding.** Row 0 has no yesterday, so its
      lag is seeded (`breadth 0.0`, `regime 'BEAR'`). Counting that seed as a
      lag-induced difference made a fixture with **zero** BEAR days report
      `Regime_Label changed when lagged: 1`. Comparison now starts at row 1 and
      the comparable count is printed. Verified by sabotage: reverting the
      change produces 8 test failures including that exact symptom.
    - **Noise reported as a direction.** It printed "Positive => the backtest
      was flattered" for a spread of +0.030% with `t = +0.57`. There is now a
      Welch's t-test and an explicit `|t| < 2` floor that prints
      "INDISTINGUISHABLE FROM NOISE. Do not report a direction." (Welch's by
      hand — no scipy in the sandbox. It *overstates* confidence, because
      daily cross-sectional returns are fat-tailed and serially correlated, so
      treat `|t| < 2` as a floor and not as a p-value.)
    - **An inert gate read as a healthy one.** "0 changes" meant both "lagging
      this gate changes no decision" and "this gate never fires on this panel".
      Base rates are now printed, and an inert gate is named as inert — which
      is what makes item 35 visible in the output rather than invisible.

    `test_macro_gate_measure.py` tests the measurement against three panels
    whose answer is known by construction: breadth following returns (expect
    `flattering`), breadth independent (expect `noise`), and breadth
    **inverted** (expect `penalising`). The inverted panel is the load-bearing
    one — a `spread` computed backwards maps it and the first panel to the same
    verdict, so the first two panels alone would pass with the sign reversed.

#### Measurements taken during the second pass, for the record

Facts established by measurement rather than reasoning, so they do not have to
be re-derived:

- **Sortino cap saturation.** `norm_sortino = min(sortino/3.0, 1.0)`, so the
  item 28 CAGR inflation pushes Sortino into the cap and flattens the
  differences the fitness function is supposed to rank on. Measured band: at
  daily vol 0.006, true Sortino 2.854 vs inflated 4.273; at 0.008, 2.134 vs
  3.195. The inflated values saturate; the true ones do not. This is the
  mechanism by which item 28 changes *selection* and not merely a printed
  number.
- **Stage 1b on the synthetic fixture** (899 comparable dates): breadth tier
  changed on 187 (20.8%), slot count differed on 187, capital share differed on
  187, mean slots 4.464 contaminated vs 4.458 lagged, spread +0.030% at
  `t = +0.57` → **noise**. Stage 2: CAGR +14.34% → +12.39% (−1.95pp), MaxDD
  −1.67% → −1.75%.

  **These are not a preview of the real panel** and must not be quoted as one.
  The fixture's breadth is near-random (autocorrelation 0.891 vs the real
  panel's much higher persistence), it contains zero VIX-spike days, and it is
  100% BULL — so the `BEAR` branch of `bb_frac` and the entire `VIX_Spike`
  kill-switch are untested by it. The numbers demonstrate the measurement works;
  the real panel's numbers are what the runbook's step 1 produces.
- **The means barely move by construction.** Mean slots 4.464 → 4.458 is not
  evidence the bias is small. Lagging shifts capacity *in time*; it does not
  add or remove capacity on average. The whole effect lives in the correlation
  between when capacity arrives and when returns arrive, which is why the
  direction test exists and why the mean is close to useless here.

#### Test inventory at the end of the second pass

11 behavioural test files pass against a fully-patched tree:
`test_macro_lag.py`, `test_yield_and_guard.py`, `test_sheets_payload.py`,
`test_ordering_fix.py`, `test_cagr_units.py`, `test_cagr_units_selection.py`,
`test_lookahead.py`, `test_fix_verification.py`,
`test_window_gap_decomposition.py`, `test_engine_copy_parity.py`,
`test_macro_gate_measure.py`. `test_reset_state.py` passes separately (it
`chdir`s into a temp repo). `test_patch_order_independence.py` passes against a
pristine checkout.

Every one of these was run against the BROKEN state first and confirmed to
fail there. A test that has only ever been seen passing is not evidence that it
tests anything — items 38 and 40 were both found this way, and item 38 in
particular was a check that had been passing while doing nothing.

"""

sub("""    loudly at startup instead of part-way through a fit.


---""",
    NEW_ITEMS.rstrip('\n') + "\n\n\n---",
    'items 32-40 + measurements + test inventory')

# ======================================================================
# 7. Closure-summary supersession note: name the second look-ahead there too.
#    Someone reading only that section should not come away thinking item 26
#    is the whole story.
# ======================================================================
sub("""> **SUPERSEDED 2026-08-22.** Everything in this section was measured with the
> look-ahead bias of Part E item 26 active.""",
    """> **SUPERSEDED 2026-08-22.** Everything in this section was measured with
> BOTH look-ahead biases active (Part E items 26 and 32), with the CAGR units
> bug (item 28) affecting candidate selection, and with idle yield accruing at
> 69% of its stated rate (item 36).""",
    'closure summary — name all four contaminants')

# ======================================================================
if src == original:
    sys.exit("ERROR: nothing changed. Every anchor matched but no edit landed -- "
             "that should be impossible, so treat it as a bug in this script "
             "rather than a no-op.")

if args.out:
    os.makedirs(args.out, exist_ok=True)
    dest = os.path.join(args.out, os.path.basename(PATH))
    with open(dest, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f"\nDRY RUN: wrote {dest}. {PATH} untouched.")
else:
    backup = PATH + '.bak'
    if not os.path.exists(backup):
        shutil.copy2(PATH, backup)
        print(f"\nBacked up  {PATH} -> {backup}")
    with open(PATH, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f"Updated    {PATH}")

# Read it back rather than trusting the write.
check_path = dest if args.out else PATH
with open(check_path, encoding='utf-8') as f:
    back = f.read()
if back != src:
    sys.exit("ERROR: the file read back does not match what was written.")

added = len(src.splitlines()) - len(original.splitlines())
print(f"Verified   re-read matches ({added:+d} lines)\n")

print("WHAT CHANGED")
print("  - top warning names BOTH look-aheads (26 and 32), gives the honest")
print("    defect breakdown (10 traded-system + 3 tooling), and records that")
print("    items 29 and 30 are closed")
print("  - file inventory gains the 14 second-pass files")
print("  - the audit preamble's '26 alone first' advice is amended, with the")
print("    reason the first pass stopped at six")
print("  - item 29 -> RESOLVED: yield in BOTH engine and live, at a true 4%/yr")
print("  - item 30 -> RESOLVED: reset clean, via reset_paper_state.py")
print("  - items 32-40 added, plus the measurements and the test inventory")
print("  - the closure summary names all four contaminants, not just item 26")
print()
print("DELIBERATELY NOT CHANGED")
print("  - apply_changelog_update.py is untouched. Its item 29 text says idle")
print("    yield was '6%/yr in the standard param set', which was TRUE when the")
print("    first pass wrote it. Retro-editing it would make the record claim the")
print("    first pass knew about item 35, and would break this script's anchors.")
print("    The supersession lives in the new item 29 text instead.")
print("  - item 31 (SETUP_GUIDE §4 path text) stays OPEN. Still documentation")
print("    plus a startup guard, still the right thing to defer, and saying so")
print("    is more useful than quietly closing it.")
