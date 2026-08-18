# Janus — Phase 2 Live Pipeline Setup Guide

Repo: `janus-alpha`. Adapted from your prior GitHub Actions + Telegram + Sheets
template, with the deviations explained inline (data source, state
management, entry automation).

## 1. System Architecture

```
[ Scheduled Trigger: Mon-Fri @ 14:13 UTC / ~7:43 PM IST ]
                      │
                      ▼
        [ GitHub Actions Runner (Ubuntu) ]
                      │
  ┌───────────────────┴───────────────────┐
  ▼                                       ▼
[ Module 1: Data Updater ]      [ state/paper_portfolio_state.json ]
- Fetches TODAY's NSE bhavcopy    (SOURCE OF TRUTH -- not Sheets)
  (same source as backtest,       - bb_cash / bb_equity / mr_cash / mr_equity
   NOT yfinance, to avoid a       - active_bb{} / active_mr{} positions
   live/backtest data mismatch)   - closed_trades_log[] / equity_curve_log[]
- Appends to master raw parquet
  │
  ▼
[ Module 2: Quantitative Engine ]
- Imports coiled_alpha_logic.py DIRECTLY (production code, not
  reimplemented) -- guarantees live signals match what was backtested
- Computes Regime_Label / Market_Breadth / VIX_Spike / Systemic_Panic
- Computes MR_Base_Signal
  │
  ▼
[ Module 3: Portfolio & Exit/Entry Evaluator ]
- Reads live_params.json (from generate_live_params.py -- a FINAL FIT
  with no held-out test year, NOT any historical WFO window's params)
- Evaluates exits: ATR stop/target, BB_Exhaustion_Today, SMA_5 cross,
  4-day time-stop-loss, mr_time cap -- identical logic to the backtest
- Evaluates entries: breadth-gated slots, breadth-gated allocation,
  RS-sorted candidates, gap-safe sizing -- identical logic to the backtest
- Updates state JSON directly (fully automated, no human confirmation --
  intentional for paper trading phase; revisit before real capital)
  │
  ▼
[ Telegram Bot API ] ──► Daily report (regime, trades, equity)
  │
  ▼
[ Google Sheets ] ──► WRITE-ONLY human dashboard, regenerated from state
  │                    each run. NEVER read back by the pipeline.
  ▼
[ Git Auto-Commit ] ──► Commits updated state JSON + master parquet
```

## 2. What's different from your template, and why

| Your template | This build | Why |
|---|---|---|
| yfinance for stock OHLCV | NSE bhavcopy (same as backtest) | Avoid a data-source mismatch between what was validated and what runs live |
| Simple EMA breadth strategy | Imports `coiled_alpha_logic.py` directly | Reuses production code -- zero risk of a "similar but not identical" reimplementation bug |
| Google Sheets = source of truth | JSON state file = source of truth, Sheets = write-only mirror | Your own checklist flagged the exact fragility this avoids (`ValueError: could not convert string to float`) |
| (not specified) | Fully automated entries, no human confirmation | Paper trading = no real capital at risk; this phase should test the pipeline running fully unattended, which is the actual thing Phase 2 needs to prove out |
| Single-sleeve position schema | Dual-sleeve (Sniper + MR), stop/target/regime-at-entry tracked per position | Our system has two independent capital pools and richer per-position state |

## 3. External Services Setup

### A. Telegram Bot (same as your template)
1. Message `@BotFather`, run `/newbot`, save the HTTP API Token.
2. Message `@userinfobot` to get your numeric Chat ID.

### B. Google Cloud (Sheets API — for the dashboard mirror only, optional)
1. Create a GCP project, enable Google Drive API + Google Sheets API.
2. Create a Service Account (IAM & Admin > Service Accounts), download the JSON key.
3. Create a Google Sheet named **`Coiled Alpha Portfolio`** (the pipeline creates
   the `Open_Positions` and `Equity_Summary` tabs itself on first run if missing).
4. Share the Sheet (Editor access) with the service account's `client_email`.

### C. GitHub Repository Secrets
Settings > Secrets and variables > Actions:

| Secret | Value |
|---|---|
| `TELEGRAM_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Numeric chat ID from @userinfobot |
| `GCP_SA_JSON` | Entire service account JSON, pasted as raw text (optional — pipeline degrades gracefully without it, just skips the Sheets mirror) |

### D. GitHub Repository Permissions
Settings > Actions > General > Workflow permissions > **Read and write permissions**
(required for the auto-commit step).

## 4. File Structure

```
├── .github/workflows/daily_pipeline.yml
├── coiled_alpha_logic.py          # production signal logic (Phase 1)
├── live_pipeline.py                # main daily execution script
├── generate_live_params.py         # run periodically, NOT daily -- see below
├── init_state.py                   # run ONCE to bootstrap paper portfolio
├── requirements.txt
├── NSE_EQ_Master_Raw.parquet       # append-only raw OHLCV (git-committed)
├── live_params.json                # output of generate_live_params.py
└── state/
    └── paper_portfolio_state.json  # SOURCE OF TRUTH (git-committed daily)
```

## 5. One-Time Initialization Steps (in order)

1. **Copy your validated raw data**: `cp NSE_EQ_2015_Fast.parquet NSE_EQ_Master_Raw.parquet`
   (post-gap-fix version — see Phase 1 changelog Part A #10).
2. **Copy `coiled_alpha_logic.py`** into the repo root (it's imported directly).
3. **Run `python init_state.py`** to create `state/paper_portfolio_state.json`
   with your starting paper capital.
4. **Run `python generate_live_params.py`** to produce the initial `live_params.json`
   (this is the "final fit" — a real live trading decision, review its output
   before trusting it, don't just run it blind).
5. Commit all of the above to the repo.
6. Set up the three GitHub Secrets (Section 3C).
7. Manually trigger the workflow once via `workflow_dispatch` (Actions tab)
   to confirm it runs clean before letting the schedule take over.

## 6. Re-optimization Cadence

**Do not run `generate_live_params.py` more than quarterly, and lean toward
annual.** Per the Phase 1 cadence analysis: selected parameters swing 21-28%
window-to-window even on an annual cadence, and a meaningful chunk of that
swing is confirmed random-search noise (seed-to-seed variance), not genuine
signal about what changed in the market. Re-fitting monthly would mean
re-drawing from that same noisy process more often — very likely chasing
noise, not adapting to anything real. Annual is the recommended default;
quarterly is a defensible hedge against genuine regime shifts if you want one.

## 7. Known Gaps / TODO Before Trusting This Beyond Early Paper Trading

- **`VIX_Spike` is hardcoded `False`** in the live pipeline — the lean Nifty
  fetch only pulls `NIFTY_CLOSE`, not `NIFTY_HIGH`/`NIFTY_LOW`, which the
  real VIX_Spike calc needs. This means the live pipeline is currently MORE
  permissive on Sniper entries during real volatility spikes than the
  backtest was. Fix before trusting results beyond early testing: fetch
  NIFTY_HIGH/NIFTY_LOW too (same as `data_prep_updated.py`) and compute it
  properly.
- **Holiday handling is naive**: a failed bhavcopy fetch currently raises an
  error rather than distinguishing "genuine market holiday" from "real fetch
  failure." Check the run log manually on any skipped day until this is
  hardened (an NSE holiday calendar check would fix this properly).
- **`run_headless_simulation` logic is duplicated** across
  `wfo_engine_updated.py`, `run_multi_seed.py`, `generate_live_params.py`, and
  (in adapted form) `live_pipeline.py`. Currently kept in sync manually — a
  real risk of drift over time. Worth extracting to a shared module before
  this system has been running long enough that nobody remembers to update
  all four copies together.
- **Corporate-action guard, MR quarantine, and the other Phase 1 "worth
  re-verifying" checklist items** still apply here too — the live pipeline
  inherits every open item from `PHASE1_CHECKLIST.md`.
