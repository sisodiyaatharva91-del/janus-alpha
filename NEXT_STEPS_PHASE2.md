# NEXT IMMEDIATE STEPS — Phase 2

Scope: what to do **right now**, in order. The wider path is in `RUNBOOK_2026-08-22.md`; the *why*
behind each fix is in `ENGINEERING_CHANGELOG.md` Part E items 26–41. This file is the short list.

---

## READ FIRST — what I cannot do, so you know what's on you

**I have no access to `janus-alpha`.** No folder is connected to this session and the sandbox has no
outbound network, so I cannot clone, commit, push, or trigger your GitHub Action. Everything below
with a command block is **yours to run**. Paste the output back and I'll read it.

Two things genuinely need you, not me:

- **Local (Windows `cmd`, in your checkout):** steps 1, 2, 4, 5, 6. No parquet needed, no new
  installs needed.
- **Colab (where the V9 parquet already lives):** step 3 (cheap, minutes) and step 7 (the re-run,
  hours). The sandbox has no `pyarrow` and cannot hold a 6.4M-row panel, so this part can only ever
  happen on your side.

If you only have time for a little, **do steps 1–4.** They are cheap, reversible, and they tell you
whether step 7 is even worth paying for.

---

## Step 1 — get the files into the repo (local, 5 min)

The audit output currently lives in this session's folder, not in your repo. Copy the whole set into
your `janus-alpha` checkout root, then:

```cmd
cd path\to\janus-alpha
git checkout -b audit-fixes-2026-08-22
git status
```

**Expect:** a branch created, and `git status` listing the new `.py`/`.md` files as untracked. Do
this on a branch — `apply_fixes.py` has **no `--out` flag**, it edits in place, so the branch is your
only way back.

**Replace the changelog properly.** `ENGINEERING_CHANGELOG_updated.md` is the *output* of three patch
scripts run against your original. Either drop it in as `ENGINEERING_CHANGELOG.md`, or regenerate it
yourself from your real file (safer if yours has drifted):

```cmd
python apply_changelog_update.py    --file ENGINEERING_CHANGELOG.md
python apply_changelog_update_v2.py --file ENGINEERING_CHANGELOG.md
python apply_changelog_update_v3.py --file ENGINEERING_CHANGELOG.md
```

Run them **in that order** — v2 anchors on text v1 writes, v3 on text v2 writes. All three are
idempotent and each hard-exits if an anchor doesn't resolve exactly once, so a mismatch is loud.

---

## Step 2 — order-independence test, BEFORE you patch (local, 1 min)

```cmd
python test_patch_order_independence.py
```

**Expect: pass.** This one *must* run on a pristine tree — it applies both patch scripts itself, in
both orders, and compares fingerprints. **After** step 3 it will fail with `already contains`, and
that is correct behaviour, not a defect. So run it now or never.

---

## Step 3 — measure the bias before paying for the re-run (Colab, ~2 min then ~15 min)

```python
!python measure_lookahead_bias.py --data NSE_EQ_Master_Raw.parquet --engine wfo_engine_updated.py
!python measure_lookahead_bias.py --data NSE_EQ_Master_Raw.parquet --engine wfo_engine_updated.py --stage2
```

**Run this on the UNPATCHED tree.** It lags the inputs itself, in memory, and compares against the
contaminated path — it needs both behaviours available, so patching first destroys the comparison.

**Expect:** three verdict blocks. Stage 1 = how far Sniper entry price / stop distance / position size
move once lagged (item 26). Stage 1b = how often the *macro gates* change tier once lagged (item 32),
in slots and capital share, with a signed spread and a Welch's `t`. Stage 2 = CAGR and MaxDD for both
paths.

**The verdict is one of three words:** `flattering`, `penalising`, or `INDISTINGUISHABLE FROM NOISE`
when `|t| < 2`.

**Do NOT read a small change in mean slots as a small bias.** Lagging shifts capacity *in time*; it
doesn't add or remove capacity on average. The damage lives in the correlation between when capacity
arrives and when returns arrive.

**Decision point.** Material Stage 1 change + Stage 2 CAGR drop over ~1pp → step 7 is worth it. Both
inside the noise floor → the fixes still go in (steps 4–5), but **the re-run drops below "get clean
live data" in priority**, which is where your own stated priority already points.

---

## Step 4 — apply every fix, in one batch (local, 10 min)

```cmd
python apply_fixes.py --fix1 --fix3 --fix5
python apply_fixes_v2.py --macro-lag --idle-yield --run-guard --sheets --live-params
```

**Why one batch, not one at a time.** Item 32 is a *second* look-ahead in the same execution path, so
"apply 26 alone and re-run" gives you a number that is still contaminated — it looks like a result and
isn't one. Everything that changes backtest behaviour (**26, 32, 28, 36**) goes in together, then you
re-run **once**.

**Expect:** each flag prints what it touched. Roughly **900 changed lines across five files** —
`live_pipeline.py` (~524), `coiled_alpha_logic.py` (~262), `wfo_engine_updated.py` (~55),
`generate_live_params.py` (~44), `data_prep_updated.py` (~27). Much of it is comments recording the
timing convention.

**`data_prep_updated.py` changing is CORRECT — don't stop when you see it.** `--macro-lag` routes it
through the one shared `compute_macro_regime()` instead of computing `Regime_Label`, `ATR_10`,
`ATR_Baseline_50`, `VIX_Spike` inline. That de-duplication is the point: it's what makes it
structurally impossible for backtest and live to drift apart again, which is how item 35 (`VIX_Spike`
hardcoded `False` in live) happened. **If a SIXTH file appears in the diff, stop.**

---

## Step 5 — run the suite (local, ~3 min)

```cmd
python test_lookahead.py
python test_fix_verification.py
python test_ordering_fix.py
python test_cagr_units.py
python test_cagr_units_selection.py
python test_macro_lag.py
python test_yield_and_guard.py
python test_sheets_payload.py
python test_engine_copy_parity.py
python test_reset_state.py
python test_macro_gate_measure.py
python test_window_gap_decomposition.py
python test_changelog_consistency.py
```

**Expect all 13 to exit 0.** Confirmed on a fully patched tree here.

**If one fails, read which check failed before re-applying anything.** The patch scripts are
idempotent, so re-running will *not* repair a genuine failure — it prints `already contains` and
exits 0, which looks like a fix and is not one. Paste the failing block to me.

---

## Step 6 — commit this much (local, 2 min)

```cmd
git add -A
git commit -m "Audit 2026-08-22: apply fixes for items 26-41"
git push origin audit-fixes-2026-08-22
```

Stop here if you're out of budget. What's above is the correctness work; what's below is the
re-measurement. **Do not merge to the branch your Action runs from until step 8**, or live will trade
`live_params.json` chosen by the old fitness function under the new engine — precisely the mismatch
item 34 is about.

---

## Step 7 — the WFO re-run (Colab, hours) — only after step 5 is green

```python
!python wfo_engine_updated.py
!python run_multi_seed.py     # if you want the seed-variance spread again
```

**Expect a CAGR below 14.17%.** Both look-aheads gave the Sniper sleeve information it could not have
had at fill time — better entry prices, better stops, better-sized positions, and more slots on
exactly the days that worked out. Removing that removes an advantage.

**Expect item 28 to move parameter *selection*, not just the printed number.** `calculate_fitness()`
annualised with `365.25/days` against a trading-day count, inflating CAGR by ≈1.4494×, which pushed
`norm_sortino = min(sortino/3.0, 1.0)` into its cap and flattened the very differences the ranking
depends on (at daily vol 0.006: true Sortino 2.854 vs inflated 4.273). So **expect different windows
to pick different parameters.**

**Expect the yield change to be small and negative:** effective 4.2291%/yr → 4.0807%, i.e.
−0.1484pp of *gross cash yield*. Treat that as an **upper bound** on the CAGR effect, not the expected
value — yield accrues only on uninvested cash.

**Do NOT expect to reach ~20% CAGR / 15–20% DD.** Pre-audit already missed it at 14.17% / −29.96%,
and corrected numbers will be lower. **If the re-run returns ≥20%, treat it as a bug in the re-run**
and check the patches are actually present in the tree it used.

**Then stop tuning.** Your own call, and the right one: the 14→20 gap will not be closed by re-tuning
a thing that just turned out to be measuring itself wrong.

---

## Step 8 — regenerate live params, reset paper state, deploy (local, 10 min)

```cmd
python generate_live_params.py
git diff live_params.json

python reset_paper_state.py --dry-run
python reset_paper_state.py
```

**`live_params.json` should change.** Byte-identical after step 7 is *suspicious, not reassuring* —
the fitness function changed, so selection should too.

**Reset is step 8, not step 1.** Resetting before the fixed code is deployed just starts accumulating
a second contaminated segment.

**Expect:** old state archived to `state/archive/paper_portfolio_state.<stamp>.contaminated.json`, an
`archive/README.md` explaining the discontinuity, and a clean state with both sleeves at **300,000**
fully in cash, nothing open, `last_run_date = ''`. **Do not seed a date** to tidy it — that either
suppresses the first run or invents a yield catch-up window.

**Watch for `DUPLICATE dates` in the output.** That means item 33 (no duplicate-session guard)
actually bit in practice, not just in principle. Worth noting before the evidence is archived.

Then merge, let the Action run, and check the first Telegram report: **total equity within a rupee or
two of 600,000, zero open positions, one session of idle yield.** Anything else means the pipeline
didn't read the new state file — check that before concluding anything about the fixes.

**Do not expect the first week of live data to validate or invalidate the strategy.** One session a
day, a handful of positions, a 4%/yr cash drag — noise dominates for months. What you're watching for
now is *operational*: does it run, does it report, does it survive a holiday and a publish delay.

---

## Still open after all of this

- **Item 31** (small, deferred): `SETUP_GUIDE.md` §4 path doesn't match what
  `generate_live_params.py` expects. Fix the guide **and** add a loud startup path check, so a wrong
  path fails immediately instead of part-way through a fit.
- **Same-day publish-timing race** (Part E item 24): identified, not fixed, unrelated to this audit.

## What to paste back to me

The output of step 2, step 3's verdict blocks, step 4's file list, and any failing test from step 5.
That's enough for me to tell you whether it worked without guessing.
