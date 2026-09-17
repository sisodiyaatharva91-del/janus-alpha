# Getting Started: GitHub Desktop + Applying the Audit Fixes

This guide assumes you have never used git on your PC before. Every step has a
screenshot-level description. If something looks different from what's described,
stop and paste me a screenshot — don't guess.

---

## PART 1 — Install GitHub Desktop (one-time, 5 min)

1. Open your browser. Go to: **https://desktop.github.com**
2. Click the big **"Download for Windows (64bit)"** button.
3. Run the installer (`GitHubDesktopSetup-x64.exe`). Accept defaults.
4. When it opens, click **"Sign in to GitHub.com"**.
5. Your browser opens a GitHub login page. Sign in with your normal GitHub
   account (the one that owns `janus-alpha`).
6. It asks "Configure Git" — your name and email. Use whatever you want;
   this shows up in commit messages. Click **Continue**.
7. You'll land on the "Let's get started" screen. Done.

---

## PART 2 — Clone your repo to your PC (one-time, 2 min)

"Clone" means: download your entire repo to a folder on your PC so you can
work on it locally.

1. In GitHub Desktop, click **"Clone a repository from the Internet…"**
   (or go to **File → Clone repository**).
2. You'll see a list of your GitHub repos. Find and click **`janus-alpha`**.
   - If you don't see it, click the **URL** tab and type:
     `https://github.com/YOUR_USERNAME/janus-alpha`
     (replace `YOUR_USERNAME` with your actual GitHub username).
3. **Local path**: this is where the repo will live on your PC. The default
   is usually `C:\Users\dell\Documents\GitHub\janus-alpha`. That's fine.
   Remember this path — you'll need it.
4. Click **Clone**. Wait for it to finish.
5. You should now see the repo open in GitHub Desktop, with "Current branch:
   main" at the top.

**Your repo is now on your PC at:**
`C:\Users\dell\Documents\GitHub\janus-alpha`
(or wherever you chose in step 3).

---

## PART 3 — Create the audit branch (1 min)

A "branch" is a parallel copy of your code. We work on the branch so that
if anything goes wrong, `main` (the one your GitHub Action runs from) is
untouched.

1. In GitHub Desktop, click **"Current branch: main"** at the top.
2. In the dropdown, type: **`audit-fixes-2026-08-22`** in the search/create box.
3. It will say **"Create new branch: audit-fixes-2026-08-22"**. Click that.
4. A dialog asks "Create branch based on main?" — click **Create Branch**.
5. The top now says **"Current branch: audit-fixes-2026-08-22"**. Good.

---

## PART 4 — Copy the audit files into the repo (5 min)

1. Open **File Explorer** on your PC.
2. Navigate to the folder where this Claude session saved the audit files.
   They are in the `janus` subfolder of the outputs this session created.
   (When you downloaded them, you chose a location — find that folder.)
3. Open a **second** File Explorer window. Navigate to your repo:
   `C:\Users\dell\Documents\GitHub\janus-alpha`
4. **Copy (Ctrl+C) all the `.py` and `.md` files** from the audit folder
   into the repo root folder. That means these files should now be at:
   ```
   C:\Users\dell\Documents\GitHub\janus-alpha\apply_fixes.py
   C:\Users\dell\Documents\GitHub\janus-alpha\apply_fixes_v2.py
   C:\Users\dell\Documents\GitHub\janus-alpha\apply_changelog_update.py
   C:\Users\dell\Documents\GitHub\janus-alpha\apply_changelog_update_v2.py
   C:\Users\dell\Documents\GitHub\janus-alpha\apply_changelog_update_v3.py
   C:\Users\dell\Documents\GitHub\janus-alpha\renumber_finding_refs.py
   C:\Users\dell\Documents\GitHub\janus-alpha\reset_paper_state.py
   C:\Users\dell\Documents\GitHub\janus-alpha\measure_lookahead_bias.py
   C:\Users\dell\Documents\GitHub\janus-alpha\make_fake_v9.py
   C:\Users\dell\Documents\GitHub\janus-alpha\run_measure_test.py
   C:\Users\dell\Documents\GitHub\janus-alpha\engine_harness.py
   C:\Users\dell\Documents\GitHub\janus-alpha\test_*.py  (all 13 test files)
   C:\Users\dell\Documents\GitHub\janus-alpha\RUNBOOK_2026-08-22.md
   C:\Users\dell\Documents\GitHub\janus-alpha\NEXT_STEPS_PHASE2.md
   C:\Users\dell\Documents\GitHub\janus-alpha\HANDOFF_PROMPT.md
   C:\Users\dell\Documents\GitHub\janus-alpha\JANUS_FILE_MAP.md
   C:\Users\dell\Documents\GitHub\janus-alpha\ENGINEERING_CHANGELOG_updated.md
   ```
5. Go back to GitHub Desktop. The left panel should now show all these files
   under **"X changed files"** with green `+` icons (meaning new files). If
   you see them — the copy worked.

> **Do NOT commit yet.** We have more steps before the first commit.

---

## PART 5 — Run the patch scripts (10 min)

You need to open a terminal in the repo folder.

### Opening a terminal

In GitHub Desktop: **Repository → Open in Command Prompt** (or PowerShell).
This opens a terminal already `cd`'d into your repo folder.

Alternatively: open **Command Prompt** (search "cmd" in Start), then type:
```cmd
cd C:\Users\dell\Documents\GitHub\janus-alpha
```
(Use whatever path you cloned to in Part 2.)

### Step 5a — Update the changelog (run all three in order)

```cmd
python apply_changelog_update.py    --file ENGINEERING_CHANGELOG.md
python apply_changelog_update_v2.py --file ENGINEERING_CHANGELOG.md
python apply_changelog_update_v3.py --file ENGINEERING_CHANGELOG.md
```

**What to expect:** Each prints the edits it made (e.g. "[1] section heading").
If one says `ERROR`, stop and paste me the full output.

### Step 5b — Order-independence test (MUST run before patching)

```cmd
python test_patch_order_independence.py
```

**What to expect:** Something like `PASS — both orderings produce identical
results`. If it fails, paste me the output.

### Step 5c — Apply code fixes

```cmd
python apply_fixes.py --fix1 --fix3 --fix5
python apply_fixes_v2.py --macro-lag --idle-yield --run-guard --sheets --live-params
```

**What to expect:** Each flag prints what it touched. Roughly 900 lines changed
across five files. If any flag says `ERROR` or `not found`, paste me the output.

### Step 5d — Run the test suite

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

**What to expect:** All 13 print `PASS` or exit silently. If any prints `FAIL`
or an error traceback, stop and paste me that one's full output.

---

## PART 6 — Commit and push (2 min)

Now that everything is applied and tested:

1. Go back to **GitHub Desktop**.
2. The left panel shows all changed files (new files + modified files).
   You should see dozens of files — all the new scripts, the modified
   production files, and the updated changelog.
3. At the bottom left, there's a **"Summary"** text box. Type:
   ```
   Audit 2026-08-22: apply fixes for items 26-41
   ```
4. Optionally add a description:
   ```
   Two-pass audit: 16 items, 14 defects. All fixed and unit-tested.
   See ENGINEERING_CHANGELOG.md Part E and RUNBOOK_2026-08-22.md.
   ```
5. Click **"Commit to audit-fixes-2026-08-22"** (the blue button).
6. Then click **"Publish branch"** (or "Push origin") at the top.
7. Your branch is now on GitHub. You can verify by going to
   `github.com/YOUR_USERNAME/janus-alpha` in your browser — you should see
   a yellow bar saying "audit-fixes-2026-08-22 had recent pushes".

**DO NOT merge to main yet.** The live GitHub Action runs from main. Merging
now would deploy the new engine code but with old live_params.json — exactly
the mismatch item 34 is about. We merge after step 7 (WFO re-run) and step 8
(new live params + state reset).

---

## PART 7 — Refresh the V9 parquet with current data (Colab, 30+ min)

Your parquet is ~1 month stale. Here's how to update it.

### Why this matters

`data_prep_updated.py` downloads historical data and computes all indicators.
The WFO engine reads this parquet. If the parquet is stale, the most-recent
WFO window and the live-params selection both train on data that's a month
short — the parameters won't reflect the latest market regime.

### How to update

1. Open your **Colab notebook** where you previously ran `data_prep_updated.py`.

2. **Before running**, you need the PATCHED version of `data_prep_updated.py`
   (with the `--macro-lag` fix applied). Two options:

   **Option A (recommended):** Pull the patched files from your GitHub branch
   into Colab:
   ```python
   # In a Colab cell — run this ONCE
   !rm -rf janus-alpha  # clean any old clone
   !git clone https://github.com/YOUR_USERNAME/janus-alpha.git
   %cd janus-alpha
   !git checkout audit-fixes-2026-08-22
   ```
   Since the repo is **private**, Colab will ask you to authenticate. The
   easiest way:
   - Go to https://github.com/settings/tokens
   - Click **"Generate new token (classic)"**
   - Give it a name like "colab-temp"
   - Check the **`repo`** scope (full control of private repos)
   - Click **Generate token**
   - Copy the token (starts with `ghp_...`)
   - In Colab, when prompted for password, paste the token (not your
     GitHub password)
   - **Delete this token from GitHub Settings after you're done** — it's a
     security best practice.

   **Option B (simpler but manual):** Upload the patched `data_prep_updated.py`
   and `coiled_alpha_logic.py` to your Colab Drive manually (from the repo
   folder on your PC, after running the patch scripts in Part 5).

3. **Run the data prep:**
   ```python
   !python data_prep_updated.py
   ```
   This will:
   - Download fresh NSE bhavcopy data via yfinance
   - Compute all indicators (including the fixed macro regime)
   - Write a new `NSE_15Y_Deployment_Ready_V9.parquet`

   **Expect:** 20–40 minutes depending on internet speed and Colab tier.
   The output should end with something like "Saved parquet: X rows, Y columns."

4. **Verify the new parquet:**
   ```python
   import pandas as pd
   df = pd.read_parquet('NSE_15Y_Deployment_Ready_V9.parquet')
   print(f"Rows: {len(df):,}")
   print(f"Date range: {df['DATE'].min()} to {df['DATE'].max()}")
   print(f"Symbols: {df['SYMBOL'].nunique()}")
   ```
   **Check:** The max date should be within the last few trading days (not a
   month ago). If it's still old, `yfinance` might be caching — add
   `--force-download` if your script supports it, or delete the cached data
   files first.

---

## PART 8 — Measure bias, then WFO re-run (Colab)

### 8a — Measure the bias FIRST (cheap, ~15 min)

**IMPORTANT:** This must run on the UNPATCHED engine to compare both paths.
But you already patched in Part 5. So:

```python
# Temporarily get the unpatched engine for measurement
!git stash   # saves your patches temporarily
!python measure_lookahead_bias.py --data NSE_15Y_Deployment_Ready_V9.parquet --engine wfo_engine_updated.py
!python measure_lookahead_bias.py --data NSE_15Y_Deployment_Ready_V9.parquet --engine wfo_engine_updated.py --stage2
!git stash pop  # restores your patches
```

Alternatively, if you cloned the audit branch (Option A in Part 7):
```python
# The audit branch IS patched, so check out main temporarily
!git checkout main -- wfo_engine_updated.py coiled_alpha_logic.py
!python measure_lookahead_bias.py --data NSE_15Y_Deployment_Ready_V9.parquet --engine wfo_engine_updated.py --stage2
!git checkout audit-fixes-2026-08-22 -- wfo_engine_updated.py coiled_alpha_logic.py  # restore patched
```

**Paste me the verdict blocks.** I'll tell you whether the re-run is worth it.

### 8b — WFO re-run (expensive, hours)

Only after 8a shows material bias:
```python
!python wfo_engine_updated.py
```

### 8c — Generate new live params

```python
!python generate_live_params.py
```

Copy the new `live_params.json` to your PC (download from Colab or push
from Colab to GitHub).

---

## PART 9 — Reset state and deploy (local, 5 min)

Back on your PC, in the repo terminal:

```cmd
python reset_paper_state.py --dry-run
```
Review the output. If it looks right:
```cmd
python reset_paper_state.py
```

Then commit and push again:
1. GitHub Desktop → type summary: `Reset paper state + new live params`
2. Click **Commit** → **Push origin**

---

## PART 10 — Merge to main and go live

Only after Parts 8 and 9 are done:

1. Go to **github.com/YOUR_USERNAME/janus-alpha** in your browser.
2. You should see a yellow banner: "audit-fixes-2026-08-22 had recent pushes"
   with a **"Compare & pull request"** button. Click it.
3. Title: `Audit 2026-08-22: fixes for items 26-41`
4. Click **"Create pull request"**.
5. Scroll down and click **"Merge pull request"** → **"Confirm merge"**.
6. Your GitHub Action will run on the next trading day. Watch the first
   Telegram report: total equity should be within a rupee of 600,000,
   zero open positions.

---

## Quick decision map

```
                Are you ready to start?
                        |
            +-----------+-----------+
            |                       |
    Yes, let's go           Not yet / confused
            |                       |
    Do Parts 1-6             Ask me what's unclear
    (all local, ~25 min)
            |
    Go to Colab
            |
    Do Part 7 (refresh parquet)
            |
    Do Part 8a (measure bias)
            |
    Paste me the verdict
            |
    I tell you: re-run worth it?
            |
      +-----+-----+
      |           |
    Yes          No
      |           |
   Part 8b-c    Skip to Part 9
      |           |
      +-----+-----+
            |
    Parts 9-10 (deploy)
```

---

*This guide replaces the git-command-line steps in NEXT_STEPS_PHASE2.md with
GitHub Desktop equivalents. The RUNBOOK order is preserved.*
