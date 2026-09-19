# Janus — Engineering Changelog & Open Flags

Paste this file into a future conversation if you hit an issue that might trace
back to this system's build. It's a record of every substantive decision, gap,
diagnostic finding, and still-open item, in case something downstream breaks
and needs to be root-caused back to here.

**Project name: Janus** (dual-brain regime-switching architecture — Sniper
sleeve / MR sleeve, each facing a different market regime). Repo: `janus-alpha`.

**STATUS: Phase 1 (backtest/data pipeline) CLOSED. Phase 2 (paper trading /
live infrastructure) IN PROGRESS** — pipeline is live on GitHub Actions and
has produced real trade entries (first live run: 2026-08-17, 3 Sniper
positions opened). Three real bugs found and fixed via live-fire testing
(NSE fetch headers, backward date search, DATE normalization — see Part E
items 22-25); one known issue (same-day publish-timing race, item #24)
identified but not yet fixed. See "PHASE 1 CLOSURE SUMMARY" near the bottom
for the final backtest numbers and the decision rationale for stopping
backtest iteration there.

> **⚠ READ THIS BEFORE QUOTING ANY PHASE 1 NUMBER (added 2026-08-22).**
> A live/backtest reconciliation audit found **two independent look-ahead
> biases in the Sniper entry path** (Part E items 26 and 32), both present in
> every Phase 1 backtest and in every live Sniper fill up to and including
> 2026-08-22. **The 14.17% CAGR /
> −29.96% DD headline is therefore SUPERSEDED and not yet replaced** — it was
> measured under contaminated decision timing and the corrected number is
> expected to be lower. The fix is written and unit-verified; the re-run that
> produces honest numbers has not been done. Until it has, treat every Sniper
> figure in Parts B/C/D and in the closure summary as an upper bound, not a
> result.
>
> Item 26 is per-stock (entry signal, stop distance, position size); item 32 is
> market-wide (how much capital the sleeve got and how many positions it was
> allowed to hold at all). Fixing 26 alone leaves the second one running.
>
> The audit ran in two passes. Items 26-41 break down as **ten defects in the
> traded system** (26, 27, 28, 29, 32, 33, 34, 35, 36, 37), **four in the
> audit tooling** built to check it and in this record (38, 39, 40, 41), one
> operational consequence that needed a decision from you (30), and one
> deferred documentation fix (31). That is 16 items and 14 defects: 10 + 4 +
> 1 + 1. If you read only one, read **34**: it is a selection defect in the
> script that writes the parameters live actually trades.
>
> All fourteen defects are fixed and unit-verified. **Nothing has been applied
> to the repo, the WFO re-run has not been done, and the paper state has not
> been reset** — see `RUNBOOK_2026-08-22.md` for the order and for what each
> step should and should not produce.
>
> The two items that needed a decision from you are closed: idle yield goes in
> **both** engine and live at a true **4%/yr** (29), and the paper-trading
> state is **reset clean** (30).

## Files in this build
- `coiled_alpha_logic.py` — replaces the old `apply_blue_box_logic` (entry signal generation)
- `data_prep_updated.py` — replaces the old data_prep orchestration script
- `wfo_engine_updated.py` — replaces the old wfo_engine.py (candidate sort order, nested validation, throughput fixes, DD fixes, breadth-gated allocation, gap-safe sizing, chained equity curve, random seed)
- `diagnostic_window_analysis.py` — trade-level diagnostic for specific weak years
- `run_multi_seed.py` — batch runner for seed-variance testing
- `PHASE1_CHECKLIST.md` — the pre-closure verification checklist
- `live_pipeline.py` — Phase 2 daily automated pipeline (data update, signal
  generation, exit/entry evaluation, reporting) — repo `janus-alpha`
- `generate_live_params.py` — Phase 2 final-fit script (produces the actual
  live Bull/Bear trading params, distinct from any historical WFO window)
- `init_state.py` — Phase 2 one-time paper portfolio state bootstrap
- `trim_master_for_github.py` — Phase 2 one-time Colab script to produce the
  size-bounded `NSE_EQ_Master_Raw.parquet` for the live repo
- `SETUP_GUIDE.md` — Phase 2 setup instructions

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
  gap is not a valid measurement

Added by the second pass (items 32-41):
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
- `test_changelog_consistency.py` — asserts that the changelog's item
  numbers and the scripts' references to them agree, by keyword and not
  merely by existence (item 41)
- `renumber_finding_refs.py` — one-shot rename of the retired fix-flag
  numbering in prose, so "finding #N" has a single meaning (item 41)
- `apply_changelog_update_v3.py` — applies this changelog update (item 41)
- `RUNBOOK_2026-08-22.md` — the ordered apply/re-run/redeploy path with the
  result each step should and should not produce

---

## PART A — DATA PIPELINE (coiled_alpha_logic.py / data_prep_updated.py)

> **AMENDED 2026-08-22**: `BB_Enter_Today`, `Target_ATR`, `RS_Percentile` and
> `ATR_Contraction_Ratio` are now lagged one bar per SYMBOL inside
> `apply_coiled_alpha_logic` (new section 5b), and a new diagnostic column
> `BB_Enter_Signal_Raw` carries the unlagged signal. See Part E item 26 before
> relying on anything in this section. Consequence worth knowing up front:
> `BB_Enter_Today` is deliberately NOT the AND of the `Sniper_Pass_*` columns
> on the same row any more — it is their AND on the PREVIOUS row.

1. **Column contract**: final entry signal is named `BB_Enter_Today` (not
   `Coiled_Alpha_Signal` or `Sniper_Base_Signal`) to match exactly what
   `wfo_engine.py` reads. `Target_ATR` = the short-window (14-day) ATR used
   for stop/target sizing.

2. **Relative Strength formula**: uses `RS_Excess = stock_60d_return -
   nifty_60d_return` (subtraction) as the default ranking basis, NOT
   `RS_Ratio = stock_60d_return / nifty_60d_return` (division), because the
   ratio's sign inverts when the Nifty's 60-day return is negative — exactly
   at Bull/Bear regime boundaries, where correct ranking matters most.

3. **`Turnover_SMA_50` / `Daily_Turnover_Rank` / `Is_Liquid`**: built inside
   `apply_coiled_alpha_logic` itself, at the very top, BEFORE anything else —
   the downstream MR sleeve depends on `Turnover_SMA_50` existing. Requires a
   `VOLUME` column in the raw data with that exact name.

4. **`Market_Breadth`**: NOT part of the entry-logic rewrite conceptually
   (independent market-wide health gauge — % of liquid stocks above their own
   50-EMA), but required by `wfo_engine.py` (gates `max_bb_pos` AND, as of
   Part B below, capital allocation). Carried over unchanged inside
   `apply_coiled_alpha_logic`, reusing `Is_Liquid`.

5. **`BB_Exhaustion_Today`** (exit signal): kept EXACTLY as legacy logic —
   `(RSI_3 >= 85) & (CLOSE < Prev_Close)`. Only the entry side was rewritten.

6. **NIFTY_CLOSE dependency ordering**: Nifty fetch moved BEFORE the
   entry-logic call in `data_prep_updated.py` (Coiled Alpha's RS calc needs it
   first; the old blue-box logic never needed Nifty data at all).

7. **Vectorized True Range**: switched from slow `groupby().apply()` to
   `shift()` + `np.maximum()`. ~3.4s for 1M rows.

8. **Corporate-action artifact guard** (`Contains_Suspicious_Jump`,
   `price_jump_threshold=0.40`): unadjusted NSE bhavcopy data contains real
   corporate actions (CONFIRMED case: KAUSHALYA underwent a 100:1 share
   consolidation — verified via Business Standard listing). This manufactures
   fake 60-day returns of +10,000%+ that distort the cross-sectional
   RS_Percentile ranking for OTHER stocks, not just the affected one. FIX: any
   day whose 60-day RS lookback contains a single-day |return| > 40% gets its
   RS ranking input masked to NaN (removed from the percentile denominator,
   not just excluded from the final signal). **STATUS: validated stopgap on a
   3-year slice (~1.9-2.1% flagged); NEVER explicitly re-validated on the full
   corrected 15-year file post-gap-fix (see Part D). A proper fix would use
   split/bonus-adjusted OHLC data from a vendor — not done, acceptable interim
   given low flagged %.**

9. **Candidate sort order in wfo_engine.py**: changed from `Target_ATR`
   descending to `RS_Percentile` descending with `ATR_Contraction_Ratio`
   ascending as tiebreak. Full-universe signal supply (2,000-3,800+/year)
   vastly exceeds slot capacity, making this sort order the dominant selection
   mechanism. **Requires `RS_Percentile`/`ATR_Contraction_Ratio` in
   `columns_to_keep`** — added; pipeline was re-run after this change.

10. **Raw data gap found and closed**: 2017-01-23 to 2022-05-25 (~1,950 days,
    ~2M rows) was completely missing from the raw scrape, almost certainly due
    to Step 1's `except Exception: pass` silently dropping failed requests
    during a rate-limited/interrupted run. Root-caused via a precise gap
    diagnostic (found ONE clean contiguous gap, not scattered thin coverage).
    Fixed via a targeted re-fetch (10 workers instead of 25, 3x retry with
    backoff, explicit failure logging) — recovered row count from 4.45M to
    6.46M, within 0.6% of the original validated 6.495M.

---

## PART B — WFO ENGINE FIXES (wfo_engine_updated.py)

11. **Nested Fit/Validation anti-overfitting**: each 3-year training window
    split into 2-year Fit + 1-year Validation (both inside the training
    window; true OOS test year untouched). Candidate selection uses
    `min(fit_fitness, val_fitness)` instead of a single aggregate score —
    directly rejects candidates that only work on one sub-period.
    **IMPORTANT FINDING**: this fix alone (without throughput fix) made OOS
    CAGR dispersion WORSE (std 33.3% -> 40.5%) because splitting an
    already-small trade sample into two even-smaller samples increased
    measurement noise faster than better selection could compensate. Only
    combined with throughput fix (#12) did dispersion improve (-> 32.7%,
    better than baseline). **Lesson: this fix needed more data to work, it
    wasn't sufficient alone.**

12. **Throughput fix**: slot count raised from 4/2/0 (by breadth tier) to
    6/3/1 — critically, removed the old hard ZERO-slot lockout below 0.50
    breadth (a stock can be a genuine top-decile RS leader even when broader
    breadth is weak). Stop/target search ranges narrowed (Bull: tgt 4-10x ATR
    -> 2.5-6.0x ATR, stop 2.5-4.5x -> 1.5-3.0x ATR; similar for Bear) to bias
    toward faster-resolving trades and free slots more often. Result: Sniper
    trades roughly doubled (~18-20/window -> ~37-73/window depending on
    seed/fixes).

13. **DD fixes** (three, none touching throughput levers):
    - Fitness DD penalty changed from a single -25% cliff to graduated: -1.0
      penalty below -15%, -3.0 penalty below -20%. Old version never
      penalized anything in the 15-25% range — exactly where most breaches
      were happening.
    - Max per-position size cut from 40% to 20% of sleeve equity (was
      calibrated for the old 2-4 slot regime; too concentrated now with 6
      slots available).
    - Risk-per-trade search range narrowed 2.0-4.0% -> 1.5-3.5%.

14. **RANDOM SEED REPRODUCIBILITY FIX — important, was missing from EVERY
    prior version**: `random.seed()` was never called anywhere, meaning every
    run drew a completely different set of 1,000 candidates per window with
    no way to reproduce results or isolate a code change's effect from pure
    sampling noise. Fixed with `RANDOM_SEED` constant + `random.seed()` +
    `np.random.seed()`. **This was likely a major, possibly dominant,
    contributor to how dramatically different early "before/after"
    comparisons looked in this project** — always seed-test (multiple seeds)
    before trusting any single run's numbers going forward.

15. **Chained full-period OOS equity curve**: per-window CAGR/DD are each
    computed on independently-reset capital and cannot reveal what a REAL
    continuously-deployed strategy would experience — specifically, a
    multi-year losing streak spanning several windows compounds into a much
    deeper drawdown than any single window's isolated Max DD can show.
    Implemented by converting each window's OOS equity curve to returns and
    chaining them sequentially into one continuous curve. Validated against a
    synthetic smooth-curve unit test (matched analytical expectation exactly:
    11.72% CAGR, -43.6% DD). **This is the correct headline metric — per-window
    averages meaningfully overstate true performance** (confirmed: arithmetic
    mean 15.69% vs. true compounded 11.72% on one early run, a ~4pp gap driven
    by volatility drag / Jensen's inequality).
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
    the two-line snippet.

16. **Breadth-gated capital allocation** (diagnostic-driven fix): the 80/20
    Sniper/MR allocation was previously gated ONLY on `Regime_Label` (Nifty
    200-SMA). Root-caused via trade-level diagnostic that 2018 had
    `Regime_Label`=BULL for 79% of days while `Market_Breadth` averaged only
    0.416 — a real, historically documented divergence (2018 IL&FS crisis:
    Nifty50 stayed flat/positive while the broader mid/small-cap universe,
    where Sniper actually trades, fell 25-30%+ underneath it). The old slot
    throttle reacted to weak breadth but the ALLOCATION PERCENTAGE never did.
    FIX: graduated allocation — 80/20 only when regime AND breadth both agree
    (breadth > 0.65); 60/40 when breadth is 0.50-0.65; 35/65 when regime says
    BULL but breadth says danger (the 2018 pattern). Bear regime unchanged
    (20/80). **VALIDATED**: reran 2018/2024/2025 diagnostics — 2018 year
    return improved -15.44% -> -13.03%.

17. **Gap-safe position sizing** (diagnostic-driven fix): root-caused via
    trade-level diagnostic that a single trade (PARAS, 2025, gapped down and
    stopped out at -47.7% in 2 days) accounted for 73% of that ENTIRE year's
    Sniper sleeve loss. ATR-based stops assume the exit fills near the
    intended stop price, but a gap (overnight news, lower-circuit lockdown)
    can blow straight through it. FIX: added `gap_safe_shares` as a fourth
    position-sizing constraint — caps position size so that even an assumed
    worst-case 20% overnight gap couldn't lose more than 3% of sleeve equity
    (`MAX_GAP_LOSS_PCT=0.03`, `ASSUMED_WORST_CASE_GAP_PCT=0.20`, both tunable
    constants). **VALIDATED, dramatic result**: 2025 year return improved
    -6.55% -> -0.12%; PARAS-style outlier completely eliminated from the
    worst-trades list in the re-run.

---

## PART C — DIAGNOSTIC FINDINGS (from trade-level analysis of 2018/2024/2025)

- **Across all three weak years, the Sniper sleeve did 82-101% of the total
  damage; MR sleeve was consistently a non-factor (roughly flat).** Narrows
  any future investigation to trend-following entry/exit logic specifically.

- **2018 remains a genuinely bad year even after fixes #16 and #17, and this
  is a KNOWN, ACCEPTED, UNRESOLVED weak spot**: win rate stayed poor (20.0% ->
  17.5%, actually ticked down slightly) even though dollar damage per trade
  shrank substantially (avg loss -7,246 -> -4,785). The two fixes bound the
  SIZE of the damage from a bad edge; they do not and were never going to fix
  WHY the edge is bad in this specific type of market (narrow/index-resilient-
  but-breadth-collapsing conditions). **Flagged for Phase 2 monitoring**: if
  live breadth sits persistently below ~0.42 while Regime_Label stays BULL,
  that's the 2018 signature repeating — treat with extra caution.

- **2024** was a moderate, unremarkable losing year (churn, not crisis) —
  improved modestly with the fixes (-8.99% -> -6.41%), not investigated
  further, not considered a red flag on its own.

- **Reproducible year clustering across ALL 8 seeds tested (42-49)**: 2018 is
  negative in every seed; 2024 AND 2025 are BOTH negative in every seed
  (a genuine 2-3 year consecutive losing stretch, not random noise — confirmed
  reproducible regardless of which 1,000 random parameter candidates got
  drawn). This is very likely the actual driver of the persistently high
  chained Max DD (~28-36% across every seed tested, both pre- and post-fix) —
  **the targeted fixes reduced per-trade/per-year damage but did NOT resolve
  this multi-year clustering pattern, and chained DD barely moved in aggregate
  as a result (pre-fix mean -31.43% -> post-fix mean -29.96%).**

---

## PART D — OPEN / DELIBERATELY DEFERRED (carrying into Phase 2)

- **PARTLY SUPERSEDED 2026-08-22 (look-ahead, Part E item 26).** The
  drawdown numbers were produced under contaminated entry timing, so the
  magnitudes will move. The *structural* diagnosis below (multi-year loss
  clustering reproducible across every seed) is unlikely to be an artifact of
  the bug, because the bug flattered entries and so if anything MASKED
  drawdown rather than manufacturing it — but that is reasoning, not a
  measurement, and the re-run should confirm it.
  **Chained Max DD remains ~28-36% across all 8 seeds tested — never got
  under even the loosened 20% fallback ceiling, let alone the original
  15-20% target.** This looks structural (see Part C clustering finding), not
  a bug. A real fix would likely require either a sleeve-level circuit
  breaker that throttles Sniper allocation after a sustained losing stretch
  (bigger, untested architectural idea, deliberately NOT pursued in Phase 1
  to avoid open-ended backtest iteration) or accepting a materially lower
  CAGR. **Decision made**: close Phase 1 without solving this further; treat
  it as a known, quantified risk to observe in Phase 2 live/paper data, which
  will be a more honest test than further backtest engineering.

- **SUPERSEDED 2026-08-22 (look-ahead, Part E item 26) — expect lower.**
  **Chained CAGR post-fix: mean 14.17%, median 14.82%, only 1/5 of the latest
  seed batch clears 15%.** Right at the edge of, not clearly above, your own
  stated floor. Documented honestly rather than rounded up.

- **`Systemic_Panic` threshold** (-0.5%/-1.5%) still measured looser than its
  name implies (18.37% of days qualify) — never revisited. Low priority
  unless MR sleeve behavior looks off in live/paper data.

- **Corporate-action guard's flagged % on the FULL corrected 15-year file** —
  never explicitly re-checked after the gap-fill (only checked pre-gap-fix and
  on a 3-year slice). Cheap to verify, not yet done.

- **MR quarantine (0 violations) last explicitly verified BEFORE the
  throughput/DD/breadth/gap-safe changes.** None of those changes touched MR
  logic directly, very likely still fine, not re-confirmed since.

- **Determinism check never actually completed** — plan was "run seed 42
  twice, confirm identical output" before trusting different-seed
  comparisons; went straight to different seeds instead. Low risk
  (single-threaded, no other source of nondeterminism identified) but
  technically unconfirmed.

- **`Fit_Val_Sortino_Gap` diagnostic uses raw uncapped Sortino**, which can
  look artificially alarming due to small-sample fragility (a Sortino of 45
  was observed in one run). Actual selection logic already caps normalized
  Sortino at 1.0 and isn't fooled by it — this is a reporting quirk only,
  never fixed at the code level. Judge overfitting by OOS CAGR dispersion
  instead, not this diagnostic.

- **8 seeds tested are NOT all apples-to-apples**: 42/43/44 used pre-fix
  allocation/sizing logic; 45/46/47/48/49 used post-fix logic. Treat 42-44 as
  "the baseline we learned from," and 45-49 as the actual current-system read.

---

## PART E — PHASE 2 INFRASTRUCTURE (post Phase-1-closure)

18. **Project renamed to Janus** (dual-brain regime-switching architecture —
    Sniper sleeve / MR sleeve, each facing a different market regime; the name
    was chosen deliberately over anything literal like "BB+MR strategy").
    Repo: `janus-alpha`. Updated in the changelog title, `SETUP_GUIDE.md`,
    `live_pipeline.py`'s Telegram report header and Google Sheets document
    name, and the GitHub Actions workflow name/commit identity. NOT changed
    (cosmetic only, no functional dependency on the string): any remaining
    "Coiled Alpha" references in code comments, docstrings, or Colab notebook
    cell titles from earlier in the project — safe to update opportunistically,
    not urgent.

19. **Live pipeline architecture built** (data updater -> quant engine ->
    portfolio evaluator -> reporting), adapted from a prior GitHub Actions +
    Telegram + Sheets template with three deliberate deviations, each with a
    specific reason:
    - **Data source kept as NSE bhavcopy, NOT switched to yfinance** for stock
      OHLCV (the template's original source) — using a different data source
      live than what validated the backtest would silently test a different
      system than the one that was backtested. Nifty index data still uses
      yfinance (matches what `data_prep_updated.py` already does).
    - **State management uses a git-committed JSON file
      (`state/paper_portfolio_state.json`) as the single source of truth,
      NOT Google Sheets.** The original template's own operational checklist
      flagged the exact fragility this avoids (`ValueError: could not convert
      string to float: ''` from stray spreadsheet cells). Sheets is now a
      write-only human dashboard, regenerated from state each run, never read
      back by the pipeline.
    - **Entries fully automated, no human-confirmation step** — deliberate
      for the paper-trading phase, since running the full pipeline
      unattended end-to-end is the actual thing Phase 2 needs to prove out
      before real capital is at risk. Revisit this before live capital.
    - Exit/entry logic in `live_pipeline.py` reuses the exact same rules as
      `wfo_engine_updated.py` (ATR stop/target, `BB_Exhaustion_Today`,
      breadth-gated slots/allocation, RS-sorted candidates, gap-safe sizing)
      — functionally tested against synthetic positions (stop-hit, SMA5-cross,
      gap-safe-sized entry all confirmed correct) before being trusted.

20. **`generate_live_params.py` created as a SEPARATE step from the 14
    historical WFO windows.** None of those 14 windows' selected parameters
    are "the current live parameters" — every one of them held out a real OOS
    test year for validation purposes. Live deployment needs its own final
    fit: most recent 3 years, 2-year Fit + 1-year Validation, same
    `min()`-based nested selection, NO held-out test year (there's no future
    data to hold out for live use — live/paper performance itself is the test).
    **Re-optimization cadence recommendation**: quarterly at most, lean
    toward annual. Selected parameters swing 21-28% window-to-window even on
    an annual cadence in backtest, and a meaningful chunk of that swing is
    confirmed random-search noise (seed-to-seed variance), not genuine
    market-regime signal — re-fitting more often very likely means chasing
    that same noise more frequently, not adapting to anything real.

21. **Master data file split into two, to solve a GitHub file-size problem
    BEFORE it caused one**: `NSE_EQ_2015_Fast.parquet` (full 15-year archive,
    stays on Drive only, never uploaded to the repo) vs.
    `NSE_EQ_Master_Raw.parquet` (3-year / 1,095-calendar-day trailing window,
    the only one uploaded to `janus-alpha`). Window size chosen with
    comfortable margin above the strict minimum the live pipeline needs
    (~720 calendar days, from `DEPLOYMENT_WINDOW_DAYS=450 * 1.6` buffer in
    `live_pipeline.py`).
    **IMPORTANT — this required a matching code fix, not just a one-time
    export**: `live_pipeline.py`'s daily save previously appended each new
    day to the full master file with no trimming, meaning the repo file
    would have silently grown by one day's rows every single run, forever,
    and hit the same GitHub size problem again on its own within a year or
    two. Added `MASTER_RETENTION_DAYS=1095` rolling-window trim to the daily
    save step itself (`update_master_data()`), so this is now self-maintaining
    going forward. **VALIDATED**: simulated 400 consecutive daily runs — row
    count grows during the initial ~21-trading-day fill-up (expected, matches
    when the oldest rows first age past the 1,095-day cutoff), then stays
    completely flat for the remaining ~380 simulated days. No unbounded growth.

22. **NSE bhavcopy fetch was failing on EVERY GitHub Actions run** (first
    real live run: `HTTP 404` on the current day). Root-caused via manual
    `curl` testing (not guessed): the endpoint requires a `Referer:
    https://www.nseindia.com/` header (plus a browser-matching `User-Agent`)
    — without it, requests either hang until timeout or receive NSE's own
    custom "file doesn't exist" page served with an HTTP `200` status
    (confirmed by inspecting the actual response body — it was NSE's branded
    error page HTML, not a real bhavcopy, despite curl reporting "success").
    This is NOT Akamai bot-fingerprinting/a CAPTCHA wall — the header fix
    alone was sufficient, no `curl_cffi`/proxy/headless-browser workaround
    was needed. `HEADERS` in `live_pipeline.py` updated accordingly.

23. **`find_latest_available_bhavcopy()` added** — the pipeline previously
    assumed `datetime.today()` was always the correct date to fetch, but NSE
    does not publish "today's" bhavcopy during/immediately after today's own
    session. Fixed to search backward from yesterday (up to 5 days) for the
    most recent actually-published date, handling weekends/holidays/publish
    delays uniformly without a hardcoded NSE holiday calendar. **VALIDATED**
    via a mocked test reproducing the exact real scenario (date N missing,
    date N-1 present) — confirmed it correctly skips the missing date and
    lands on the right one.

24. **Same-day publish-timing race identified, NOT yet fixed** — even with
    fix #23, one run genuinely fetched the wrong (previous) day's data
    because that day's bhavcopy simply hadn't been published yet at the
    cron's fire time (14:13 UTC / ~19:43 IST), confirmed by manually curling
    the same URL later and getting a real file. This is a timing race, not a
    logic bug: the backward-search did the right thing with the information
    available at that moment. **RECOMMENDED FIX, NOT YET IMPLEMENTED**: (a)
    shift the cron trigger later (e.g. ~21:00 IST) for more buffer, and/or
    (b) add same-day-first retry logic (a few attempts with a short delay
    before falling back to the prior day) so a slightly-late publish on one
    particular day doesn't need a permanently later schedule to handle.

25. **DATE column time-of-day mismatch bug — root cause of "No signal rows
    found" failing for 3 consecutive days despite the master file updating
    correctly each time.** `fetch_todays_bhavcopy` was stamping new rows with
    `target_date` as-is, which carries whatever time-of-day the script
    happened to run at (e.g. `14:13:07`), not midnight — while all historical
    data (and the exact-match filter in `compute_todays_signals`, which
    calls `.normalize()`) expects midnight-normalized dates. The row was
    fetched correctly and merged correctly (merge logic only uses `>=`
    comparisons, unaffected by time-of-day), but became invisible to the
    exact-equality "get today's rows" filter — explaining exactly the
    observed symptom (2,632 symbols fetched, master file updated, then zero
    signal rows found for that same date). **FIX**: normalize to
    `pd.Timestamp(target_date.date())` at the earliest point DATE is created,
    plus defensive `.dt.normalize()` added at every other DATE-touching point
    in the live pipeline (`master_df`, `new_day_df`, `window_df`) as
    belt-and-suspenders against any other stray source of non-midnight
    timestamps. **VALIDATED**: reproduced the exact bug in isolation (old
    code: date equality check returns `False`; new code: returns `True`) —
    not a guessed fix.
    **Useful cross-check**: a separate live-trading script (`live_greybox.py`,
    same author, different strategy) never hit this bug because it sources
    from `yfinance`, whose daily-bar index is already midnight-normalized
    coming out of the API — confirms the general lesson (always explicitly
    normalize date/time handling at the exact point external data enters the
    pipeline; don't rely on a particular source's incidental formatting).

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
> against its counterpart.

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

29. **RESOLVED (dell's decision, 2026-08-22: "Both, at 4%") — the backtest
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

30. **RESOLVED (dell's decision, 2026-08-22: "Reset and restart clean") —
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

31. **OPEN (small) — `SETUP_GUIDE.md` §4 path text does not match
    `generate_live_params.py`'s actual expectations.** Deliberately deferred
    until the items above settle, since it is documentation plus a guard
    rather than a correctness bug. When picked up: fix the guide's text AND add
    an explicit path/environment check to the script so a wrong path fails
    loudly at startup instead of part-way through a fit.


---

### 2026-08-22 (second pass) — EXECUTION-MODEL AUDIT (items 32-41)

The first pass compared two files against each other. This one compared each
file against the **execution model**: for every value the Sniper sleeve
consumes, when was that value knowable? The Sniper fills at `OPEN(t)`, so
anything it reads must be as of `close(t-1)`. The MR sleeve fills at
`row['CLOSE']` (market-on-close), so same-bar reads there are legitimate. That
asymmetry is the single most important fact about this codebase and it is why
"lag everything" is as wrong as "lag nothing".

Items 32-37 are defects in the traded system. Items 38-41 are defects in the
audit tooling built to check it, and in this record itself (41) — recorded at
equal weight on purpose, because
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
    items 29+36 together is small — an effective **4.2291%/yr becomes
    4.0807%**, a change of **−0.1484pp of gross cash yield** — even though the
    parameter moved by a third. A parameter that changed by 2 and an outcome
    that changed by a seventh of a point is the signature of a units bug, and
    it is why "we lowered the yield assumption from 6% to 4%" would be an
    actively misleading description of this change.

    **−0.1484pp is an upper bound on the CAGR effect, not the expected
    value.** Yield accrues only on *uninvested* sleeve cash, so the full
    figure lands only if capital sits 100% in cash throughout. With the
    sleeves partly invested the realised drag is smaller, scaled by the
    average cash fraction — which the re-run reports and which has not been
    measured here. Called out because the earlier wording ("about −0.15pp on
    CAGR") gave a bound the authority of a forecast.

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

41. **AUDIT TOOLING / RECORD KEEPING — two numbering schemes shared one
    syntax, so a cross-reference could resolve to a real item about the wrong
    thing. Fixed.** Found 2026-08-22 by `test_changelog_consistency.py`, which
    is also the reason it survived as long as it did.

    Two schemes were in use, both written `#N`:

    - the **fix-flag** scheme — `--fix1`, `--fix3`, `--fix5` in
      `apply_fixes.py`, written in prose as "finding #1/#3/#5"
    - the **changelog** scheme — Part E items 26-41, written in prose as
      "finding #32/#33/#34"

    16 references used the first. `apply_fixes_v2.py` carried
    `<- finding #5` next to the CAGR formula, meaning `--fix5`, i.e. **item
    28** — but changelog item 5 exists, in Part A, about something else
    entirely. A reader following that reference lands on a real entry and has
    no signal that it is the wrong one. **That is worse than a dangling
    reference: a dangling reference announces itself.**

    Fixed by `renumber_finding_refs.py`: fix1 → 26, fix3 → 27, fix5 → 28,
    applied to 16 references across 6 files, with per-file expected counts
    asserted before anything is written and a closing sweep that proves no
    reference below 26 remains. The **flags keep their names** — `--fix1` is a
    command line already run and recorded in shell history; renaming it to fix
    a problem that exists only in prose would invalidate notes to no purpose.
    Verified by re-running from a pristine snapshot: byte-identical result, and
    a second run is a clean no-op.

    **WHY THE TEST DID NOT CATCH IT SOONER — the part worth keeping.** TEST 3
    checked each `finding #N` against the changelog and printed, as a pass:

    ```
    OK   apply_fixes_v2.py: 'finding #5' exists (no keyword registered)
    ```

    It reported OK *because item 5 exists*. It had no keyword for 5, could not
    evaluate whether the reference pointed at the right thing, and returned
    green anyway. **A check that reports success on the input it cannot assess
    is worse than no check — it converts an unknown into a tick.** TEST 3 now
    fails on any reference with no keyword registered or with a number below 26
    (all real audit findings are Part E items, so a low number is the retired
    scheme leaking back in). The two files that legitimately *quote* the old
    scheme are allowed to, per file and per number, rather than by exempting
    the whole file — a blanket exemption would stop checking their valid
    references too, which is the same trade that produced the false OK.

    Two further gaps closed in the same pass, both the same class of defect —
    a record that omits something without saying so:

    - **The file inventory omitted two files that exist**
      (`test_changelog_consistency.py`, `renumber_finding_refs.py`). TEST 4 now
      checks the inventory in **both** directions: every file the build claims
      to have added must exist, and every `.py` in the directory must be
      listed. Pre-existing repo files are reported but not asserted, since the
      changelog can legitimately be read from a partial checkout.
    - **`apply_lookahead_patch.py` deleted.** A superseded standalone draft of
      `--fix1`, referenced by nothing, that wrote the **same sentinel**
      (`'DECISION TIMING (see section 5b)'`) as `apply_fixes.py --fix1`.
      Running it first made `--fix1` silently no-op and left one stale comment
      line. Verified comment-only — stripping comment lines from both outputs
      gives byte-identical files — so no behaviour was at risk, but the
      sentinel-collision class already bit once in item 38 and a second live
      instance of it is not worth keeping on disk.

    A note on all three of items 38-41 and on the two counting errors the top
    warning now shows arithmetic for: every one was a defect in **my own
    output**, and every one biased toward making the audit look tidier than it
    was. What caught them was checking each claim against a source instead of
    re-reading the prose — counting the item list, asking which file a bug is
    actually in, diffing the scripts' help text against the changelog
    headings. Re-reading is not verification.

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


---



## PHASE 1 CLOSURE SUMMARY

> **SUPERSEDED 2026-08-22.** Everything in this section was measured with
> BOTH look-ahead biases active (Part E items 26 and 32), with the CAGR units
> bug (item 28) affecting candidate selection, and with idle yield accruing at
> 69% of its stated rate (item 36). The numbers below are an upper
> bound on the real system's Phase 1 performance, not a result. They are kept
> verbatim rather than deleted, because the *decision* they justified (stop
> iterating on the backtest, get to live infrastructure) is still the right
> call — arguably more so now, since the defect that most needed finding was
> found by reconciling live against backtest, which is exactly what Phase 2 is
> for and what no amount of further backtest tuning would have surfaced.

**Final honest numbers (5-seed post-fix batch, current code)**:
- Chained CAGR: mean 14.17%, median 14.82%, std 1.86% (range 11.07%-15.93%)
- Chained Max DD: mean -29.96%, std 2.37% (range -33.82% to -28.04%)
- Avg Sniper trades/window: ~63-73 (up from original ~10-15/year baseline,
  short of the 80-150 target but a large, validated improvement)
- 0 of 8 total seeds tested (across both pre- and post-fix code) came in
  under the 20% chained DD ceiling

**Decision**: close Phase 1 here. CAGR is near but not clearly above the 15%
floor; chained DD is meaningfully above even the loosened 20% fallback
threshold. By the deploy-worthiness bar set earlier in this project ("DD of
~25% is fine if results are this good, else prefer 20%"), this doesn't yet
clear it — but further backtest iteration was assessed as having diminishing
returns (targeted fixes worked exactly as designed at the trade level, but the
real driver of chained DD — multi-year loss clustering reproducible across
every seed — looks structural, not something another round of parameter
patches would resolve). Consistent with the project's own stated priority
(don't over-perfect the backtest; get to live infrastructure and paper
trading), the decision was made to proceed to Phase 2 with these numbers
documented honestly, and the known weak spots (2018-style breadth divergence,
2024-2025-style multi-year clustering) carried forward as explicit things to
watch for in live data — which will be a more honest test of whether they're
real recurring problems than further backtest engineering.

## Validated facts about the current deployment file
- 6,455,483 rows (post gap-fill), 2010-01-04 to 2026-07-31, full history intact
- 0 duplicate (DATE, SYMBOL) rows
- BB_Enter_Today: healthy signal counts across all 15 years, no dead years
- Regime_Label BULL/BEAR splits track real Nifty history correctly across the
  full period, including now-recovered 2017-2022
- MR quarantine (Bull-regime large-cap-only restriction): 0 violations (as of
  last explicit check, pre-dating the final round of fixes — see Part D)
