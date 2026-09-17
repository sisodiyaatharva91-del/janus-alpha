# JANUS FILE MAP

Every Python file in the repo answered in the same 14-question format.
Last updated: 2026-09-16. Status reflects the **unpatched** repo (before
`RUNBOOK_2026-08-22.md` steps are executed).

**Status key:**
- `RUN` — run this as part of the live daily workflow
- `WFO` — run this when re-optimising parameters (quarterly/annually)
- `ONE-TIME` — run once then commit the output; don't re-run casually
- `AUDIT` — run once as a measurement or diagnostic, then archive
- `TEST` — run only to verify a fix; not part of live workflow
- `HOLD` — do not run until prerequisites are met
- `NEVER` — deleted or superseded; do not run

---

## Pipeline overview (read this first)

```
RAW DATA (NSE bhavcopy + Nifty)
        ↓
  data_prep_updated.py          ← builds the master V9 parquet (one-time + occasional refresh)
        ↓
  [NSE_15Y_Deployment_Ready_V9.parquet]
        ↓
  wfo_engine_updated.py         ← 14-window walk-forward optimisation (WFO cadence)
        ↓
  generate_live_params.py       ← picks CURRENT live parameters from most-recent 3 years (WFO cadence)
        ↓
  [live_params.json]
        ↓
  live_pipeline.py              ← runs every trading day (GitHub Action)
        ↓
  [paper_portfolio_state.json]  [Telegram report]  [Google Sheet]
```

**Support layer (always present, never in the daily path):**
```
coiled_alpha_logic.py     ← imported by data_prep + live_pipeline
engine_harness.py         ← imported by tests + measure_lookahead_bias
```

---

## GROUP A — CORE PRODUCTION FILES
*These run the actual strategy. Touch with care.*

---

### 1. `coiled_alpha_logic.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | The **Sniper sleeve signal generator**. Computes whether a stock is a valid Sniper entry candidate today, and the MR sleeve's liquidity/turnover base columns. |
| 2 | Why does it exist? | Replaced the old `apply_blue_box_logic`. Separates Sniper entry logic from MR logic so each can evolve independently. |
| 3 | Where does it fit? | **Indicators → Signals** layer. Sits between raw OHLCV data and the engine/pipeline that makes trade decisions. |
| 4 | What does it read? | A DataFrame with columns: `DATE, SYMBOL, CLOSE, HIGH, LOW, VOLUME` (plus `Nifty_Close` for RS calculation). |
| 5 | What does it produce? | Adds columns to the DataFrame: `BB_Enter_Today`, `BB_Exhaustion_Today`, `Target_ATR`, `RS_Percentile`, `ATR_Contraction_Ratio`, `Turnover_SMA_50`, `Daily_Turnover_Rank`, `Is_Liquid`, `Market_Breadth`. |
| 6 | Who consumes its output? | `data_prep_updated.py` (for building the parquet) and `live_pipeline.py` (every trading day). Both call `apply_coiled_alpha_logic()` directly. |
| 7 | When do we run it? | **Never run directly.** Always imported and called as a function. |
| 8 | Prerequisites | `pandas`, `numpy`. No external data files needed — takes a DataFrame as input. |
| 9 | Current status | **RUN** (imported daily by `live_pipeline.py`) — **but contains an unfixed look-ahead bug until `apply_fixes.py --fix1` is applied.** |
| 10 | Version/replacement status | This IS the replacement for the old `apply_blue_box_logic`. Current version is the one to use. |
| 11 | Dependencies | None (standalone module). |
| 12 | Important logic | (a) **True Relative Strength** — `RS_Percentile` is cross-sectional, computed per-DATE across all stocks vs Nifty 60-day return; (b) **Volatility Contraction** — `ATR_Contraction_Ratio` = short ATR / long ATR, must be shrinking; (c) **Macro block** — computes `Market_Breadth`, `Regime_Label`, `VIX_Spike`, `Systemic_Panic` (shared with live_pipeline after `--macro-lag` fix). |
| 13 | Risks/problems | **Item 26 (UNFIXED):** Sniper entries fill at `OPEN(t)` but `BB_Enter_Today`, `Target_ATR`, `RS_Percentile`, `ATR_Contraction_Ratio` are derived from `CLOSE(t)` — look-ahead. **Item 32 (UNFIXED):** `Market_Breadth`, `Regime_Label`, `VIX_Spike`, `Systemic_Panic` also read same-bar. Both fixed by `apply_fixes.py --fix1` + `apply_fixes_v2.py --macro-lag`. |
| 14 | Role in final workflow | The **brain of the Sniper sleeve**. Without this, neither the backtest nor live knows which stocks to consider for trend-following entries. |

---

### 2. `data_prep_updated.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | The **master parquet builder**. Downloads historical NSE data, computes all indicators, and writes the V9 parquet that the WFO engine reads. |
| 2 | Why does it exist? | Separates the expensive one-time data preparation from the daily trading logic. You build the parquet once; the engine reads it many times. |
| 3 | Where does it fit? | **Data layer** — the very first step. Everything downstream depends on its output. |
| 4 | What does it read? | Raw NSE bhavcopy files + Nifty data (via `yfinance`). |
| 5 | What does it produce? | `NSE_15Y_Deployment_Ready_V9.parquet` — a 6.4M-row panel with all indicator columns. |
| 6 | Who consumes its output? | `wfo_engine_updated.py` and `generate_live_params.py` (both read the parquet directly). |
| 7 | When do we run it? | **ONE-TIME** to build the initial parquet. Re-run when adding new historical data or after changing indicator logic. **Do not re-run casually** — it downloads and processes 15 years of data. |
| 8 | Prerequisites | `pandas`, `numpy`, `yfinance`, `pyarrow`. Requires internet access. Best run in Colab. |
| 9 | Current status | **HOLD** — after `apply_fixes_v2.py --macro-lag` is applied, re-run this to update the stored parquet. Until then the parquet is slightly stale but usable (the live pipeline re-computes from raw anyway). |
| 10 | Version/replacement status | Current production version. The `_updated` suffix marks it as the replacement for the original `data_prep.py`. |
| 11 | Dependencies | Imports `coiled_alpha_logic.apply_coiled_alpha_logic`. |
| 12 | Important logic | Calls `apply_coiled_alpha_logic()` then `apply_mean_reversion_logic()` in sequence. `apply_mean_reversion_logic` is defined **inside this file** (it computes RSI(2), IBS, Bollinger bands for the MR sleeve). |
| 13 | Risks/problems | After `--macro-lag` fix, the macro block is routed through one shared `compute_macro_regime()` in `coiled_alpha_logic.py`. This is correct and the diff to this file is expected (~27 lines). |
| 14 | Role in final workflow | **Creates the data foundation.** Nothing runs without its parquet. |

---

### 3. `wfo_engine_updated.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | The **walk-forward optimisation engine**. Runs 14 rolling windows, each fitting 1,000 random parameter sets and selecting the best, to produce a validated performance history. |
| 2 | Why does it exist? | Validates that the strategy works across different market periods, not just the period it was designed on. Produces the headline CAGR/MaxDD numbers. |
| 3 | Where does it fit? | **WFO layer** — the most expensive step. Sits after data prep and before live parameter generation. |
| 4 | What does it read? | `NSE_15Y_Deployment_Ready_V9.parquet` (reads at import time — this is why tests cannot import it directly). |
| 5 | What does it produce? | Printed per-window results + chained CAGR/MaxDD summary. No output file from the engine itself; `generate_live_params.py` produces `live_params.json`. |
| 6 | Who consumes its output? | You (the human) read the results. `generate_live_params.py` uses the same logic but for current live params. |
| 7 | When do we run it? | **WFO** — after fixes are applied and tests pass. Quarterly or annual re-run cadence. **Run in Colab** — requires pyarrow and 15-year parquet, hours to complete. |
| 8 | Prerequisites | `pandas`, `numpy`, `pyarrow`, `dateutil`. The V9 parquet on Colab Drive. |
| 9 | Current status | **HOLD** — do not re-run until all 8 fix flags are applied and all 13 tests pass. The current numbers (14.17% CAGR / −29.96% MaxDD) are superseded upper bounds. |
| 10 | Version/replacement status | `_updated` suffix = current production version. Older `wfo_engine.py` (without suffix) is obsolete. |
| 11 | Dependencies | `coiled_alpha_logic.py` (calls `apply_coiled_alpha_logic` + `apply_mean_reversion_logic`). `engine_harness.py` provides the shared test interface to `run_headless_simulation`. |
| 12 | Important logic | **`run_headless_simulation(p, df)`** — the core function: loops over every trading date in order (yield → breadth/regime read → rebalance → exits → entries). **`calculate_fitness()`** — scores each parameter set; the CAGR units bug (item 28) was here. **`RANDOM_SEED = 42`** — fixed seed for reproducibility. |
| 13 | Risks/problems | **Item 26 + 32 (UNFIXED):** look-ahead in both Sniper inputs and macro gates inflates all historical numbers. **Item 28 (UNFIXED):** `calculate_fitness()` used `365.25/days` where `days` is a trading-day count, inflating CAGR by ×1.4494 and saturating the Sortino cap. All three fixed by the patch scripts. |
| 14 | Role in final workflow | **Produces the validated performance history** and proves the strategy edge is not curve-fitting to one period. |

---

### 4. `generate_live_params.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | Picks the **current live trading parameters** — the actual Bull/Bear param sets that `live_pipeline.py` trades with today. |
| 2 | Why does it exist? | The 14 WFO windows each held out a test year; none of them are "current." This script trains on the most recent 3 years (no held-out year, since live performance is the test) and writes the result. |
| 3 | Where does it fit? | **Parameters layer** — runs after the WFO re-run, before deploying. |
| 4 | What does it read? | `NSE_15Y_Deployment_Ready_V9.parquet` |
| 5 | What does it produce? | `live_params.json` — committed to the repo, read by `live_pipeline.py` every day. |
| 6 | Who consumes its output? | `live_pipeline.py` (reads `live_params.json` at startup). |
| 7 | When do we run it? | **ONE-TIME** after each WFO re-run, or quarterly/annually. Also run after applying `--live-params` fix for the first time. |
| 8 | Prerequisites | Same as `wfo_engine_updated.py`. Run in Colab. |
| 9 | Current status | **HOLD** — must apply `apply_fixes_v2.py --live-params` first, then re-run after the WFO re-run completes. Current `live_params.json` was selected by the **old** (broken) fitness function. |
| 10 | Version/replacement status | Current production version. Before the `--live-params` fix it contained a **drifted copy** of `run_headless_simulation` that had missed the idle-yield and CAGR units fixes (item 34). Fixed by `--live-params` flag. |
| 11 | Dependencies | Imports logic from `wfo_engine_updated.py` via `engine_harness.py` (after fix). Pre-fix it had its own embedded copy. |
| 12 | Important logic | Same nested min() selection as the WFO engine: Fit 2yr, Validate 1yr. Re-optimisation cadence: quarterly or annual (monthly is too noisy — seed variance exceeds signal). |
| 13 | Risks/problems | **Item 34 (UNFIXED until --live-params applied):** embedded engine copy had not received idle-yield or CAGR fixes, so live params were selected under different arithmetic than the backtest. |
| 14 | Role in final workflow | **The bridge between the backtest and live trading.** If this is wrong, the live engine is trading with parameters chosen by broken maths. |

---

### 5. `live_pipeline.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | The **daily trading script**. Runs every weekday after NSE close via GitHub Actions. Fetches data, computes signals, evaluates exits and entries, updates state, sends Telegram report, updates Google Sheet. |
| 2 | Why does it exist? | Automates the daily execution. Without it, you'd have to manually run everything at 4pm IST every day. |
| 3 | Where does it fit? | **Live engine layer** — the final step in the daily chain. |
| 4 | What does it read? | `live_params.json`, `state/paper_portfolio_state.json`, NSE bhavcopy (downloaded live), Nifty data (via `yfinance`). |
| 5 | What does it produce? | Updated `state/paper_portfolio_state.json`, Telegram message, Google Sheet update. GitHub Actions commits the state file back to the repo. |
| 6 | Who consumes its output? | You (read the Telegram report). Google Sheet is a mirror for human review. State file is read by the next day's run. |
| 7 | When do we run it? | **RUN** — every trading day (Mon–Fri) via GitHub Actions. Do not trigger manually unless debugging. |
| 8 | Prerequisites | `pandas`, `numpy`, `requests`, `yfinance`, `gspread`, `google-auth`. GitHub Actions secrets: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `GSHEET_CREDENTIALS`. |
| 9 | Current status | **RUN** — but **all fixes must be applied and paper state reset before trusting any output**. Currently trades with look-ahead parameters and a contaminated state file. |
| 10 | Version/replacement status | Current production version. |
| 11 | Dependencies | `coiled_alpha_logic.apply_coiled_alpha_logic`. Reads `live_params.json`. Writes to `state/`. |
| 12 | Important logic | **Execution order (must match the backtest):** yield accrual → breadth/regime read → rebalance → exits → entries. **Idle yield:** `(1 + IDLE_YIELD_PCT/100/TRADING_DAYS_PER_YEAR)^n - 1` compounded over missed sessions. **Duplicate guard:** checks `last_run_date` before processing. **Sheets payload:** trade log + open positions (after `--sheets` fix). |
| 13 | Risks/problems | **Item 27 (UNFIXED):** exits were ordered before rebalance. **Item 29 (UNFIXED):** idle yield credited nothing before fix. **Item 33 (UNFIXED):** no duplicate-session guard. **Item 35 (UNFIXED):** `VIX_Spike` hardcoded `False`. **Item 37 (UNFIXED):** NaN/numpy scalars in Sheets payload would throw at 16:00 IST. All five fixed by the v2 patch flags. |
| 14 | Role in final workflow | **The live system itself.** Every other file exists to support or validate this one. |

---

### 6. `engine_harness.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | A **shared loader** that extracts `run_headless_simulation` from `wfo_engine_updated.py`'s source text so tests can call the real production function without importing the whole engine (which reads the parquet at import time). |
| 2 | Why does it exist? | `wfo_engine_updated.py` runs work at import time (reads the 6.4M-row parquet). Tests can't import it. Before this file, each test hand-copied the globals dict — and when the idle-yield fix added `TRADING_DAYS_PER_YEAR`, all three tests broke simultaneously with a `NameError`. |
| 3 | Where does it fit? | **Test support layer** — not in the live path. |
| 4 | What does it read? | The source code of `wfo_engine_updated.py` (via `open()` + `ast.literal_eval` for constants). |
| 5 | What does it produce? | Returns `(run_sim_function, namespace_dict)` to any caller. |
| 6 | Who consumes its output? | `measure_lookahead_bias.py`, `test_cagr_units.py`, `test_macro_lag.py`, `test_yield_and_guard.py`, `test_engine_copy_parity.py`, `test_ordering_fix.py`. |
| 7 | When do we run it? | **Never run directly.** Always imported. |
| 8 | Prerequisites | `ast`, `pandas`, `numpy`. |
| 9 | Current status | **TEST** — part of the test infrastructure. |
| 10 | Version/replacement status | New file created 2026-08-22 to fix item 22. No prior version. |
| 11 | Dependencies | `wfo_engine_updated.py` (reads its source). |
| 12 | Important logic | Reads engine constants with `ast.literal_eval` (not `exec`, not `import`) — avoids running the parquet-reading code. Constants auto-update when the engine changes them. |
| 13 | Risks/problems | If `wfo_engine_updated.py` uses a constant that isn't a module-level literal (e.g. computed from other values), the harness won't see it. Low risk in practice. |
| 14 | Role in final workflow | **Enables the test suite.** Without it, testing `run_headless_simulation` requires the 6.4M-row parquet. |

---

## GROUP B — MEASUREMENT AND AUDIT SCRIPTS
*Run once to quantify something. Not part of the daily or WFO path.*

---

### 7. `measure_lookahead_bias.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | A **bias measurement script** that quantifies how much the look-ahead bugs (items 26 and 32) actually moved the backtest numbers, cheaply, before committing to a full WFO re-run. |
| 2 | Why does it exist? | A full WFO re-run is ~28,000 simulations and takes hours. This takes minutes and tells you the sign and magnitude first. |
| 3 | Where does it fit? | **Audit layer** — run before the WFO re-run, on the unpatched tree. |
| 4 | What does it read? | `NSE_15Y_Deployment_Ready_V9.parquet` + `wfo_engine_updated.py` (via `engine_harness`). |
| 5 | What does it produce? | Printed report: Stage 1 (entry price/stop/size shift), Stage 1b (macro gate tier change frequency, Welch's t, verdict), Stage 2 (CAGR + MaxDD for both contaminated and clean paths). |
| 6 | Who consumes its output? | You (the human) — read the verdict and decide whether the full re-run is worth it. |
| 7 | When do we run it? | **AUDIT** — run ONCE on the **unpatched** tree (Colab), before applying fixes. After patching, it can no longer produce the comparison (both paths become identical). |
| 8 | Prerequisites | `pandas`, `numpy`, `pyarrow`, `dateutil`. V9 parquet in Colab. |
| 9 | Current status | **RUN NOW** (Colab, unpatched tree) — this is step 3 of the runbook. |
| 10 | Version/replacement status | New file created 2026-08-22. |
| 11 | Dependencies | `engine_harness.py` (loads `run_headless_simulation`). |
| 12 | Important logic | Lags the four Sniper columns in-memory and re-runs the simulation — does NOT modify any files. Stage 1b computes a signed spread with Welch's t: `|t| < 2` → `INDISTINGUISHABLE FROM NOISE`. |
| 13 | Risks/problems | **Must run on the unpatched tree.** Patching first destroys the comparison because both code paths become identical. The fake-data test driver is `run_measure_test.py` + `make_fake_v9.py`. |
| 14 | Role in final workflow | **The decision gate for the WFO re-run.** Step 3 of the RUNBOOK. |

---

### 8. `make_fake_v9.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | Builds a **synthetic panel** with the real V9 schema so `measure_lookahead_bias.py` can be exercised end-to-end in the sandbox (no parquet/pyarrow needed). |
| 2 | Why does it exist? | The sandbox has no pyarrow and no access to the 6.4M-row parquet. Without this, `measure_lookahead_bias.py` could only be `--help`-ed, never actually run. |
| 3 | Where does it fit? | **Test support layer** — sandbox only. Not used in Colab or live. |
| 4 | What does it read? | Nothing (generates synthetic data). |
| 5 | What does it produce? | A `.pkl` (pickle) file by default, or a `.parquet` file if run with a `.parquet` path argument. Same schema as the real V9 panel. |
| 6 | Who consumes its output? | `run_measure_test.py` (consumes the pickle in the sandbox). |
| 7 | When do we run it? | **TEST** — only for sandbox testing of `measure_lookahead_bias.py`. Never in Colab or live. |
| 8 | Prerequisites | `pandas`, `numpy`. No pyarrow needed for default pickle output. |
| 9 | Current status | **TEST** |
| 10 | Version/replacement status | New file created 2026-08-22. |
| 11 | Dependencies | None. |
| 12 | Important logic | Fixture is **100% BULL regime, zero VIX-spike days** — so BEAR branch and `VIX_Spike` kill-switch are untested. Breadth autocorrelation 0.891 (far below the real panel). **Its numbers are not a preview of real results.** |
| 13 | Risks/problems | Synthetic results were quoted (−1.95pp CAGR change) in early drafts as if they were forecasts. They are not. |
| 14 | Role in final workflow | **Sandbox test scaffolding only.** Has no role in production. |

---

### 9. `run_measure_test.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | A **test driver** that runs `measure_lookahead_bias.py` end-to-end in the sandbox by monkey-patching `pd.read_parquet` to read a pickle instead. |
| 2 | Why does it exist? | The sandbox has no pyarrow. This lets the full code path of `measure_lookahead_bias.py` be exercised with a fake file, to verify the script works before handing it to dell for Colab. |
| 3 | Where does it fit? | **Test support layer.** Not in any production path. |
| 4 | What does it read? | Takes the pickle path as `sys.argv[1]` (output of `make_fake_v9.py`). |
| 5 | What does it produce? | The same printed output as `measure_lookahead_bias.py --stage2`. |
| 6 | Who consumes its output? | You (the developer) verify it runs without error. |
| 7 | When do we run it? | **TEST** — only in the sandbox. |
| 8 | Prerequisites | `pandas`, `numpy`. Requires `make_fake_v9.py` to have been run first. |
| 9 | Current status | **TEST** |
| 10 | Version/replacement status | New file 2026-08-22. |
| 11 | Dependencies | `measure_lookahead_bias.py` (runs it via `runpy.run_path`). |
| 12 | Important logic | Single monkey-patch: `pd.read_parquet = lambda *a, **k: pd.read_pickle(fixture)`. Everything else is unmodified. |
| 13 | Risks/problems | None — pure test scaffolding. |
| 14 | Role in final workflow | **No role in production.** Sandbox-only. |

---

## GROUP C — PATCH SCRIPTS
*Apply fixes to the repo files. Run once, in order, on a branch. All idempotent.*

---

### 10. `apply_fixes.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | The **first-pass patch script**. Applies three fixes to production files using exact-string replacement. |
| 2 | Why does it exist? | The sandbox cannot edit repo files directly. This script is the delivery mechanism — run it once in your checkout. |
| 3 | Where does it fit? | **Patch layer** — run in step 4 of the RUNBOOK, before the WFO re-run. |
| 4 | What does it read? | `coiled_alpha_logic.py`, `live_pipeline.py` (in-place). |
| 5 | What does it produce? | Modified versions of those files. |
| 6 | Who consumes its output? | The WFO engine (reads the patched `coiled_alpha_logic.py`) and the live pipeline. |
| 7 | When do we run it? | **ONE-TIME** — on the `audit-fixes-2026-08-22` branch, before the WFO re-run. |
| 8 | Prerequisites | Python 3. Must be run **after** `git checkout -b audit-fixes-2026-08-22`. **No `--out` flag** — edits in place. |
| 9 | Current status | **RUN** (step 4 of RUNBOOK, not yet done). |
| 10 | Version/replacement status | First-pass patch. Flags: `--fix1` (item 26), `--fix3` (item 27), `--fix5` (item 28). |
| 11 | Dependencies | Modifies `coiled_alpha_logic.py`, `live_pipeline.py`, `wfo_engine_updated.py`. |
| 12 | Important logic | Exact-string replacement with a unique sentinel per fix. If the sentinel is already present → `already contains` and exits 0 (idempotent). If the anchor string is not found → exits non-zero (cannot silently half-apply). |
| 13 | Risks/problems | **Must branch first** — no `--out` flag means it edits in place. Running on `main` without a branch means no way back. |
| 14 | Role in final workflow | **Delivers fixes 26, 27, 28 to the repo.** Half the fix payload; `apply_fixes_v2.py` delivers the other half. |

---

### 11. `apply_fixes_v2.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | The **second-pass patch script**. Applies five more fixes (items 32, 29+36, 33, 37, 34) to production files. |
| 2 | Why does it exist? | These fixes were found in a second code-reading pass (after `apply_fixes.py` was already written). Separate script keeps each pass's record clean. |
| 3 | Where does it fit? | **Patch layer** — run immediately after `apply_fixes.py` in step 4. |
| 4 | What does it read? | `coiled_alpha_logic.py`, `data_prep_updated.py`, `live_pipeline.py`, `wfo_engine_updated.py`, `generate_live_params.py` (all in-place, or via `--out` to a copy). |
| 5 | What does it produce? | Modified versions of those five files (~900 changed lines total). |
| 6 | Who consumes its output? | Everything downstream — WFO engine, live pipeline, live params. |
| 7 | When do we run it? | **ONE-TIME** — immediately after `apply_fixes.py` in step 4. |
| 8 | Prerequisites | `apply_fixes.py` must have been run first (anchors for v2 assume v1's changes are present). |
| 9 | Current status | **RUN** (step 4 of RUNBOOK, not yet done). |
| 10 | Version/replacement status | Second-pass patch. Has `--out` flag (unlike v1). Flags: `--macro-lag`, `--idle-yield`, `--run-guard`, `--sheets`, `--live-params`. |
| 11 | Dependencies | Modifies the five production files listed above. |
| 12 | Important logic | `--macro-lag` collapses the duplicated macro block into one shared `compute_macro_regime()` — this is what makes item 35 (`VIX_Spike` hardcoded `False` in live) impossible going forward. `--live-params` replaces the embedded drifted engine copy with a reference to the real one. |
| 13 | Risks/problems | **Apply in one batch with all 5 flags, not one at a time.** Partial application leaves a partially-corrected tree whose numbers are neither old nor new. |
| 14 | Role in final workflow | **Delivers fixes 32, 29+36, 33, 37, 34 to the repo.** Together with `apply_fixes.py`, completes the full audit fix set. |

---

## GROUP D — CHANGELOG PATCH SCRIPTS
*Update `ENGINEERING_CHANGELOG.md`. Run once, in order. All idempotent.*

---

### 12. `apply_changelog_update.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | Adds **Part E items 26–31** to the changelog (first audit pass findings). |
| 2 | Why does it exist? | The sandbox cannot edit repo files directly. Same delivery-mechanism pattern as the code patch scripts. |
| 3 | Where does it fit? | **Record-keeping layer.** Run once when copying audit files into the repo. |
| 4 | What does it read? | `ENGINEERING_CHANGELOG.md` (in-place, or `--file` override). |
| 5 | What does it produce? | Updated `ENGINEERING_CHANGELOG.md` with items 26–31 appended. |
| 6 | Who consumes its output? | You and future contributors reading the changelog. |
| 7 | When do we run it? | **ONE-TIME** — first, before v2 and v3. |
| 8 | Prerequisites | `ENGINEERING_CHANGELOG.md` must exist. Run in order: v1 → v2 → v3. |
| 9 | Current status | **ONE-TIME** (not yet applied to your repo). |
| 10 | Version/replacement status | First-pass changelog patch. Byte-for-byte frozen after writing — do not edit it. |
| 11 | Dependencies | None (text substitution only). |
| 12 | Important logic | Exact-string anchor; hard-exits if the anchor appears ≠ 1 time. |
| 13 | Risks/problems | None. |
| 14 | Role in final workflow | Step 1 of changelog update sequence. |

---

### 13. `apply_changelog_update_v2.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | Adds **Part E items 32–40** (second audit pass findings) and updates the warning block counts. |
| 2 | Why does it exist? | Second pass found more defects after v1 was written. Editing v1 would falsely imply it knew about those defects. |
| 3 | Where does it fit? | **Record-keeping layer.** Run second. |
| 4 | What does it read? | `ENGINEERING_CHANGELOG.md` (post-v1). |
| 5 | What does it produce? | Updated changelog with items 32–40. |
| 6 | Who consumes its output? | You and future contributors. |
| 7 | When do we run it? | **ONE-TIME** — after v1, before v3. |
| 8 | Prerequisites | v1 must have been run first (anchors on text v1 writes). |
| 9 | Current status | **ONE-TIME** (not yet applied to your repo). |
| 10 | Version/replacement status | Second-pass changelog patch. Frozen. |
| 11 | Dependencies | None. |
| 12 | Important logic | Same exact-string pattern. |
| 13 | Risks/problems | None. |
| 14 | Role in final workflow | Step 2 of changelog update sequence. |

---

### 14. `apply_changelog_update_v3.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | Adds **item 41** (dual numbering collision), fixes the item 36 upper-bound wording, and adds three missing files to the inventory. |
| 2 | Why does it exist? | Item 41 was found by `test_changelog_consistency.py` *after* v2 was written. Editing v2 would falsely claim the second pass knew about it. |
| 3 | Where does it fit? | **Record-keeping layer.** Run last (third). |
| 4 | What does it read? | `ENGINEERING_CHANGELOG.md` (post-v2). |
| 5 | What does it produce? | Final updated changelog with items 26–41 complete, all counts correct, and item 36's −0.15pp claim correctly marked as an upper bound. |
| 6 | Who consumes its output? | You and future contributors. |
| 7 | When do we run it? | **ONE-TIME** — after v2. |
| 8 | Prerequisites | v1 and v2 must have been run first. |
| 9 | Current status | **ONE-TIME** (not yet applied to your repo). |
| 10 | Version/replacement status | Third-pass changelog patch. |
| 11 | Dependencies | None. |
| 12 | Important logic | 8 edits in one pass; edit [7] corrects the item 36 paragraph to add compounded figures (4.2291% → 4.0807%) and mark −0.1484pp as an upper bound on CAGR effect. |
| 13 | Risks/problems | None. |
| 14 | Role in final workflow | Step 3 (final) of changelog update sequence. |

---

## GROUP E — ONE-SHOT UTILITY SCRIPTS
*Run once for a specific operational task.*

---

### 15. `renumber_finding_refs.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | Renames all `finding #1/#3/#5` references in prose to `finding #26/#27/#28` (the changelog item numbers), so `#N` means exactly one thing everywhere. |
| 2 | Why does it exist? | Two numbering schemes shared the syntax `#N`. `finding #5` could mean either `--fix5` (item 28) or changelog Part A item 5. This is item 41 of the audit. |
| 3 | Where does it fit? | **One-shot cleanup** — run once when copying audit files into the repo. |
| 4 | What does it read? | Six `.py` files with old-scheme references. |
| 5 | What does it produce? | Renamed references in those six files. |
| 6 | Who consumes its output? | Everyone reading the code. `test_changelog_consistency.py` TEST 3 verifies the result. |
| 7 | When do we run it? | **ONE-TIME** — once on the audit branch. Already run in the sandbox; those files are already renumbered in the versions you received. |
| 8 | Prerequisites | Must be run before `test_changelog_consistency.py` is expected to pass. |
| 9 | Current status | **ONE-TIME** (already done in sandbox copies; will be a no-op if you copy the sandbox files into your repo). |
| 10 | Version/replacement status | New one-shot utility. |
| 11 | Dependencies | None. |
| 12 | Important logic | Surveys all 6 files, asserts counts match `EXPECTED` before writing anything. Closing sweep proves no `finding #N` with N<26 remains. **Flags keep their names** (`--fix1` etc.) — only the prose is renumbered. |
| 13 | Risks/problems | Run it before copying files and it's a no-op; the files in the sandbox are already renumbered. |
| 14 | Role in final workflow | No role in production. One-time housekeeping. |

---

### 16. `reset_paper_state.py`

| # | Question | Answer |
|---|---|---|
| 1 | What is it? | Archives the contaminated paper-trading state and writes a clean one — both sleeves at 300,000 cash, nothing open, `last_run_date = ''`. |
| 2 | Why does it exist? | The existing state was accumulated under look-ahead bugs, wrong exit ordering, wrong yield basis, and no duplicate guard. It cannot be compared with anything produced after the fixes. |
| 3 | Where does it fit? | **Operations layer** — step 8 (not step 1!) of the RUNBOOK. |
| 4 | What does it read? | `state/paper_portfolio_state.json` (existing state), `live_pipeline.py` (to extract required state keys via regex), `wfo_engine_updated.py` (to read `START_CAPITAL`). |
| 5 | What does it produce? | `state/paper_portfolio_state.json` (clean, reset), `state/archive/paper_portfolio_state.<stamp>.contaminated.json` (old state archived), `state/archive/README.md`. |
| 6 | Who consumes its output? | `live_pipeline.py` — reads the clean state on the next scheduled run. |
| 7 | When do we run it? | **ONE-TIME** — step 8 of the RUNBOOK. **After fixes are deployed and live params regenerated. Not before.** |
| 8 | Prerequisites | Fixed `live_pipeline.py` must already be in the repo (so the key-read check is against the correct pipeline). `--dry-run` first to review what will happen. |
| 9 | Current status | **HOLD** — do not run until step 7 of the RUNBOOK is done. Dell's decision: "Reset and restart clean." |
| 10 | Version/replacement status | New file 2026-08-22. |
| 11 | Dependencies | Reads source of `live_pipeline.py` (key extraction via regex). Reads source of `wfo_engine_updated.py` (START_CAPITAL via `ast.literal_eval`). |
| 12 | Important logic | Reads required state keys FROM `live_pipeline.py`'s source — not hardcoded. Refuses to write a state file that's missing any key the pipeline reads. Reads `START_CAPITAL` from the engine rather than hardcoding — so a clean state cannot silently disagree with the backtest. `last_run_date = ''` is deliberate: both consumers treat blank as "fresh start." |
| 13 | Risks/problems | **ORDER MATTERS** — resetting before fixing would just start accumulating a second contaminated segment. Also: do NOT try to "repair" old state by re-pricing entries. Different entries consume different cash, enabling different later entries. Path dependence means there is no local fix. |
| 14 | Role in final workflow | **Starts the clean paper-trading baseline.** Everything before this is the old contaminated record; everything after is the honest one. |

---

## GROUP F — TEST SUITE
*Run on a fully patched tree to confirm all fixes work correctly. All 13 must exit 0.*

---

### 17. `test_lookahead.py`

**What:** Proves item 26 exists (Sniper fills at `OPEN(t)` off `CLOSE(t)` data) and that the fix resolves it.  
**Tests:** Property test over every position the real engine opens — not a rigged fixture.  
**Run when:** Step 5 of the RUNBOOK (on patched tree). **Status: TEST.**

---

### 18. `test_fix_verification.py`

**What:** Blast-radius test — exactly **4 columns change** (the four Sniper inputs), **35 do not**.  
**Tests:** The fix in `coiled_alpha_logic.py` using the patched module itself.  
**Run when:** Step 5. **Status: TEST.**

---

### 19. `test_ordering_fix.py`

**What:** Proves item 27 (exits before rebalance changed position sizing) and validates the fix.  
**Tests:** Shows that old ordering and new ordering produce different trade sizes on the same signal.  
**Run when:** Step 5. **Status: TEST.**

---

### 20. `test_cagr_units.py`

**What:** Tests item 28 — `calculate_fitness()` using `365.25/days` where `days` is a trading-day count inflates CAGR by ×1.4494.  
**Tests:** Feeds a known CAGR curve and checks the engine reports the correct number after the fix.  
**Run when:** Step 5. **Status: TEST.**

---

### 21. `test_cagr_units_selection.py`

**What:** Follow-up to `test_cagr_units.py` — proves the units bug changes **parameter selection**, not just the printed number (because it saturates the Sortino cap, flattening rankings).  
**Tests:** Constructs two candidates with controlled downside deviation; shows the inflated formula picks the wrong one.  
**Run when:** Step 5. **Status: TEST.**

---

### 22. `test_macro_lag.py`

**What:** Proves item 32 — the macro gates were same-bar and changed which tier the engine operated in.  
**Run when:** Step 5. **Status: TEST.**

---

### 23. `test_yield_and_guard.py`

**What:** Tests items 29+36 (idle yield on both sides) and item 33 (duplicate-session guard).  
**Run when:** Step 5. **Status: TEST.**

---

### 24. `test_sheets_payload.py`

**What:** Tests item 37 — NaN/numpy scalar values in the Sheets payload no longer throw `json.dumps` errors.  
**Run when:** Step 5. **Status: TEST.**

---

### 25. `test_engine_copy_parity.py`

**What:** Tests item 34 — proves `generate_live_params.py`'s embedded engine copy now matches `wfo_engine_updated.py` (after `--live-params` fix).  
**Run when:** Step 5. **Status: TEST.**

---

### 26. `test_reset_state.py`

**What:** Proves the state file `reset_paper_state.py` produces is one `live_pipeline.py` can actually run against — no missing keys, correct types, sums to `START_CAPITAL`.  
**Run when:** Step 5. **Status: TEST.**

---

### 27. `test_macro_gate_measure.py`

**What:** Tests `measure_lookahead_bias.py`'s Stage 1b measurement itself against three panels with known answers — verifies sign convention and that `flattering`/`penalising`/`noise` verdicts are correct.  
**Run when:** Step 5. **Status: TEST.**

---

### 28. `test_window_gap_decomposition.py`

**What:** Proves that per-window arithmetic means overstate the true chained CAGR (Jensen's inequality / volatility drag). Validates changelog item 15's correction.  
**Run when:** Step 5. **Status: TEST.**

---

### 29. `test_changelog_consistency.py`

**What:** Asserts that every `finding #N` in every script actually points at a changelog item about the right thing (keyword match, not just existence). Also checks the file inventory in both directions.  
**Run when:** Step 5 (and any time you add a new finding reference). **Status: TEST.**

---

### 30. `test_patch_order_independence.py`

**What:** Proves `apply_fixes.py` and `apply_fixes_v2.py` compose in either order — both orderings produce byte-identical results.  
**⚠️ MUST RUN ON A PRISTINE TREE** — before step 4, not after. After patching it prints `already contains` (correct behaviour, not a defect).  
**Run when:** Step 2 of the RUNBOOK (before applying fixes). **Status: TEST.**

---

## QUICK REFERENCE — STATUS TABLE

| File | Group | Status | Run where | RUNBOOK step |
|---|---|---|---|---|
| `coiled_alpha_logic.py` | Core production | RUN (unfixed) | Colab + local | — |
| `data_prep_updated.py` | Core production | HOLD → re-run after fix | Colab | after step 4 |
| `wfo_engine_updated.py` | Core production | HOLD → re-run after tests | Colab | step 7 |
| `generate_live_params.py` | Core production | HOLD → re-run after WFO | Colab | step 8 |
| `live_pipeline.py` | Core production | RUN (unfixed) | GitHub Action | — |
| `engine_harness.py` | Test support | TEST | local | — |
| `measure_lookahead_bias.py` | Audit | **RUN NOW** (unpatched) | Colab | step 3 |
| `make_fake_v9.py` | Test support | TEST | local sandbox | — |
| `run_measure_test.py` | Test support | TEST | local sandbox | — |
| `apply_fixes.py` | Patch | **RUN** (step 4) | local | step 4 |
| `apply_fixes_v2.py` | Patch | **RUN** (step 4) | local | step 4 |
| `apply_changelog_update.py` | Changelog patch | ONE-TIME | local | step 1 |
| `apply_changelog_update_v2.py` | Changelog patch | ONE-TIME | local | step 1 |
| `apply_changelog_update_v3.py` | Changelog patch | ONE-TIME | local | step 1 |
| `renumber_finding_refs.py` | Utility | ONE-TIME (done in sandbox) | local | step 1 |
| `reset_paper_state.py` | Operations | HOLD → step 8 | local | step 8 |
| `test_lookahead.py` | Test suite | TEST | local | step 5 |
| `test_fix_verification.py` | Test suite | TEST | local | step 5 |
| `test_ordering_fix.py` | Test suite | TEST | local | step 5 |
| `test_cagr_units.py` | Test suite | TEST | local | step 5 |
| `test_cagr_units_selection.py` | Test suite | TEST | local | step 5 |
| `test_macro_lag.py` | Test suite | TEST | local | step 5 |
| `test_yield_and_guard.py` | Test suite | TEST | local | step 5 |
| `test_sheets_payload.py` | Test suite | TEST | local | step 5 |
| `test_engine_copy_parity.py` | Test suite | TEST | local | step 5 |
| `test_reset_state.py` | Test suite | TEST | local | step 5 |
| `test_macro_gate_measure.py` | Test suite | TEST | local | step 5 |
| `test_window_gap_decomposition.py` | Test suite | TEST | local | step 5 |
| `test_changelog_consistency.py` | Test suite | TEST | local | step 5 |
| `test_patch_order_independence.py` | Test suite | TEST (**pristine tree only**) | local | step 2 |

---

## WHAT DOES NOT EXIST YET

These files are in the **`janus-alpha` repo** but are NOT in this sandbox — they are pre-existing files
that were not part of the audit deliverables. You can use them in Colab.

- `run_multi_seed.py` — runs the WFO engine across multiple random seeds to show seed-variance spread
- The raw bhavcopy download scripts (referenced in `SETUP_GUIDE.md`)
- `live_params.json` — the current live parameters file (in your repo, selected by the old broken fitness function; will change after step 8)
- `state/paper_portfolio_state.json` — your live paper state (contaminated; will be reset in step 8)

---
*Generated from source inspection of all 30 Python files. Cross-referenced with `ENGINEERING_CHANGELOG.md` items 26–41 and `RUNBOOK_2026-08-22.md`.*
