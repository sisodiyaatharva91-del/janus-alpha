"""
apply_fixes_v2.py — Janus, session 2026-08-22 (second batch)
============================================================
Second batch of fixes, written after a code-reading pass over the three
changes dell asked for (idle yield, Google Sheets logs, VIX_Spike). Two of
the four fixes below are defects that pass turned up, not requests.

Same contract as apply_fixes.py: exact-string replacement with assertions, so
a silent partial patch is impossible. Idempotent — each fix detects its own
marker and skips. Nothing is applied by default and there is no --all.

  --macro-lag    coiled_alpha_logic.py + data_prep_updated.py + live_pipeline.py
                 FINDING #32. apply_fixes.py --fix1 lagged the four PER-STOCK
                 Sniper decision inputs but left the four MARKET-WIDE macro
                 gates (Market_Breadth, Regime_Label, VIX_Spike,
                 Systemic_Panic) reading bar t's own close while the Sniper
                 fills at OPEN(t). fix1 was therefore incomplete.
                 Also collapses the DUPLICATED macro block (it existed
                 separately in data_prep and live_pipeline) into one shared
                 compute_macro_regime(), which is what fixes VIX_Spike in
                 live: it was hardcoded False there.
                 AFFECTS BACKTEST AND LIVE. Needs a WFO re-run.

  --idle-yield   wfo_engine_updated.py + live_pipeline.py
                 Two things. (a) UNITS BUG: the engine divides the annual rate
                 by 365 but accrues only on trading days, so all of Phase 1
                 ran at 252/365 of the stated rate — the "6.0" was really
                 4.23%/yr effective. Divisor becomes 252 so the number means
                 what it says. (b) Sets the rate to 4.0 and adds matching
                 accrual to live, which credited nothing at all (finding #29).
                 AFFECTS BACKTEST AND LIVE.

  --run-guard    live_pipeline.py
                 FINDING #33. state['last_run_date'] is written every run and
                 never read, so there is no guard against re-processing the
                 same bhavcopy. Exits cleanly instead.
                 AFFECTS LIVE ONLY. Apply this BEFORE --idle-yield goes live,
                 because without it a re-run double-accrues yield.

  --sheets       live_pipeline.py
                 dell's request: surface state['closed_trades_log'] (already
                 populated, never written out) as a Trade_Log tab, and enrich
                 Open_Positions / Equity_Summary. Presentation only — cannot
                 change a single trade.
                 AFFECTS LIVE REPORTING ONLY.

Usage:
    python apply_fixes_v2.py --run-guard --sheets
    python apply_fixes_v2.py --macro-lag --idle-yield
    python apply_fixes_v2.py --macro-lag --dir /path/to/janus-alpha
    python apply_fixes_v2.py --sheets --out /tmp/dryrun    # writes copies, touches nothing

ORDER RELATIVE TO apply_fixes.py
    Run apply_fixes.py FIRST, then this script. Either order now produces a
    working tree, but they are NOT byte-identical and the reason is worth
    knowing:

      - Cosmetic, harmless: the `lag_macro_gates` docstring paragraph and the
        parameter itself land in a different position within
        apply_coiled_alpha_logic's signature depending on which script ran
        first. Same behaviour either way.

      - NOT cosmetic, now fixed: apply_fixes.py's --fix5 used to guard itself
        with `if 'TRADING_DAYS_PER_YEAR' in src`. This script's --idle-yield
        introduces a module-level constant of exactly that name into the same
        file, so running v2 first made fix5 announce "already applied,
        skipping" and silently leave the CAGR units bug live -- which also
        silently corrupts parameter SELECTION, not just a printed number.
        Reproduced and fixed 2026-08-22 by narrowing fix5's sentinel to a
        banner unique to its own edit. If you are using an older copy of
        apply_fixes.py, check that line before trusting a v2-first run.

    The lesson generalises: an idempotency sentinel must be unique to the edit
    that writes it, not merely present in the file afterwards. Every sentinel
    in this script was audited against that rule on 2026-08-22.

    Applying fix1 and --macro-lag together is the sensible grouping: both are
    look-ahead fixes and both invalidate the same numbers, so they should share
    one WFO re-run rather than forcing two.
"""

import argparse
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--dir', default='.', help='repo directory containing the files')
ap.add_argument('--out', default=None,
                help='dry run: write patched copies into this directory instead '
                     'of editing in place')
ap.add_argument('--macro-lag', action='store_true',
                help='finding #32: lag the market-wide macro gates + share one macro impl')
ap.add_argument('--idle-yield', action='store_true',
                help='idle yield units bug + 4%%/yr in both engine and live')
ap.add_argument('--run-guard', action='store_true',
                help='finding #33: refuse to re-process an already-processed date')
ap.add_argument('--sheets', action='store_true',
                help='Google Sheets trade log + richer open positions')
ap.add_argument('--live-params', action='store_true',
                help='finding #34: generate_live_params.py carries a stale copy of '
                     'the engine and never got the idle-yield or CAGR units fixes')
args = ap.parse_args()

if not (args.macro_lag or args.idle_yield or args.run_guard or args.sheets
        or args.live_params):
    ap.error('pick at least one of --macro-lag / --idle-yield / --run-guard / '
             '--sheets / --live-params (there is no --all on purpose)')

if args.out:
    os.makedirs(args.out, exist_ok=True)

_cache = {}


def load(name):
    """Read a file, preferring an already-patched in-memory copy so that two
    flags editing the SAME file compose correctly in one invocation."""
    if name in _cache:
        return name, _cache[name]
    p = os.path.join(args.dir, name)
    if not os.path.exists(p):
        sys.exit(f"ERROR: {p} not found. Use --dir to point at the repo.")
    return name, open(p, encoding='utf-8').read()


def save(name, src):
    _cache[name] = src
    target = os.path.join(args.out if args.out else args.dir, name)
    open(target, 'w', encoding='utf-8').write(src)


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ERROR [{label}]: anchor matched {n} times, expected exactly 1. "
                 f"The file has drifted from the version this patch was written "
                 f"against -- reconcile by hand rather than forcing it.")
    return src.replace(old, new, 1)


def replace_between(src, start, end, new, label):
    """Replace everything from the start of `start` up to (not including)
    `end`. Used where the span to replace is long enough that transcribing it
    byte-exactly into this script would itself be a source of error."""
    for marker, which in ((start, 'start'), (end, 'end')):
        n = src.count(marker)
        if n != 1:
            sys.exit(f"ERROR [{label}]: {which} marker matched {n} times, "
                     f"expected exactly 1.")
    i = src.index(start)
    j = src.index(end)
    if j <= i:
        sys.exit(f"ERROR [{label}]: end marker appears before start marker.")
    return src[:i] + new + src[j:]


applied = []
skipped = []


# =====================================================================
# MACRO-LAG -- finding #32
# =====================================================================
if args.macro_lag:

    # -----------------------------------------------------------------
    # 1/4  coiled_alpha_logic.py -- the shared macro implementation
    # -----------------------------------------------------------------
    name, src = load('coiled_alpha_logic.py')
    if 'def compute_macro_regime(' in src:
        skipped.append('macro-lag  coiled_alpha_logic.py  (already applied)')
    else:
        MACRO_FN = '''def compute_macro_regime(nifty_df, lag_macro_gates: bool = True):
    """THE single implementation of the market-wide macro gates.

    Both data_prep_updated.py (backtest) and live_pipeline.py (live) call this,
    so they cannot drift apart. Before 2026-08-22 each file carried its own
    copy and they HAD drifted: live hardcoded `VIX_Spike = False` because it
    never fetched Nifty's High/Low, which made the live pipeline silently more
    permissive on Sniper entries during real volatility spikes than the
    backtest that validated its parameters. A duplicated block is not a style
    problem, it is a divergence waiting to happen.

    Columns added:

      Regime_Label     'BULL' if Nifty > its own 200-SMA else 'BEAR'  [LAGGED]
      VIX_Spike        Nifty ATR(10) > 1.75x its own 50-day baseline  [LAGGED]
      Systemic_Panic   Nifty daily return under a regime-dependent
                       threshold (-0.50% in BULL, -1.50% in BEAR)     [NOT lagged]

    plus Regime_Label_Today / VIX_Spike_Today, unlagged, diagnostics only.

    WHY TWO OF THE THREE ARE LAGGED AND ONE IS NOT
        The Sniper sleeve fills at OPEN(t), so every input to that decision
        has to be knowable before the open — i.e. as of close(t-1).
        Regime_Label and VIX_Spike gate the Sniper (they set max_bb_pos and
        the bb/mr capital split), so on bar t they must carry close(t-1)
        values. Using bar t's own close to authorise a fill at bar t's own
        open is look-ahead, and it biases in the flattering direction: more
        slots and more capital exactly on days that turn out strong, zero
        slots exactly on days that turn out volatile.

        Systemic_Panic is deliberately NOT lagged. It gates the MR sleeve
        only, and MR fills at CLOSE(t) — a market-on-close order placed after
        observing the day, which is implementable and internally consistent.
        Lagging it would make a capitulation sleeve a full day late on a 1-3
        day bounce.

        Market_Breadth is the fourth gate. It is built from the stock panel
        rather than from Nifty, so it lives in apply_coiled_alpha_logic and is
        lagged there, in section 7b, for exactly this reason.

    A NOTE ON THE PANIC THRESHOLD
        panic_thresholds is derived from the SAME-BAR regime label on purpose
        (it is computed before Regime_Label is lagged below — do not reorder).
        MR may use close(t) information, so its own gate should be internally
        same-bar throughout.

    NAMING WARNING
        'VIX_Spike' is NOT India VIX. It is a realised-volatility proxy built
        from Nifty's own true range. The name is kept because the V9 parquet,
        the stored WFO result CSVs and live_params.json all use it, and
        renaming it would invalidate those artifacts for no behavioural gain.
        Read it as 'Nifty_ATR_Expansion'.
    """
    if nifty_df is None:
        raise ValueError(
            "compute_macro_regime got None -- the Nifty fetch failed upstream. "
            "Do not continue with a default regime; the whole allocation "
            "depends on this."
        )

    m = nifty_df.copy()
    m["DATE"] = pd.to_datetime(m["DATE"]).dt.normalize()
    m = m.sort_values("DATE").reset_index(drop=True)

    missing = [c for c in ("NIFTY_CLOSE", "NIFTY_HIGH", "NIFTY_LOW")
               if c not in m.columns]
    if missing:
        raise ValueError(
            "compute_macro_regime requires " + str(missing) + " in order to "
            "compute VIX_Spike from Nifty's true range. Do NOT work around "
            "this by defaulting VIX_Spike to False -- that exact shortcut is "
            "what made live diverge from the backtest until 2026-08-22. "
            "Fetch Nifty's High and Low columns instead."
        )

    # --- Regime: Nifty against its own 200-SMA -----------------------
    m["NIFTY_SMA_200"] = m["NIFTY_CLOSE"].rolling(window=200).mean()
    m["Regime_Label"] = np.where(
        m["NIFTY_CLOSE"] > m["NIFTY_SMA_200"], "BULL", "BEAR"
    )
    m["Prev_Close"] = m["NIFTY_CLOSE"].shift(1)

    # --- VIX_Spike: Nifty ATR(10) against its own 50-day baseline ----
    m["TR"] = np.maximum(
        m["NIFTY_HIGH"] - m["NIFTY_LOW"],
        np.maximum(
            (m["NIFTY_HIGH"] - m["Prev_Close"]).abs(),
            (m["NIFTY_LOW"] - m["Prev_Close"]).abs(),
        ),
    )
    m["ATR_10"] = m["TR"].rolling(window=10).mean()
    m["ATR_Baseline_50"] = m["ATR_10"].rolling(window=50).mean()
    m["VIX_Spike"] = (m["ATR_10"] > (m["ATR_Baseline_50"] * 1.75)).astype(bool)

    # --- Systemic_Panic: MR's trigger. Same-bar, see docstring. ------
    panic_thresholds = np.where(m["Regime_Label"] == "BULL", -0.0050, -0.0150)
    m["Nifty_Daily_Return"] = (
        (m["NIFTY_CLOSE"] - m["Prev_Close"]) / m["Prev_Close"]
    )
    m["Systemic_Panic"] = (m["Nifty_Daily_Return"] < panic_thresholds).astype(bool)

    # --- unlagged copies for diagnostics -----------------------------
    m["Regime_Label_Today"] = m["Regime_Label"]
    m["VIX_Spike_Today"] = m["VIX_Spike"]

    if lag_macro_gates:
        # One row of this frame is one Nifty trading session, so a positional
        # shift(1) IS "the previous trading session" -- no calendar logic
        # needed. fill_value=False on the bool column rather than a bare
        # shift(): bool(float('nan')) is True in Python, so a NaN left on row 0
        # would be read by `if vix_spike_today:` as a REAL volatility spike and
        # would zero out the Sniper's slots on the first bar of the panel.
        m["Regime_Label"] = m["Regime_Label"].shift(1)
        m["VIX_Spike"] = m["VIX_Spike"].shift(1, fill_value=False).astype(bool)

        assert m["VIX_Spike"].dtype == bool, "VIX_Spike must stay bool after lagging"
        assert not m["VIX_Spike"].isna().any(), "NaN leaked into VIX_Spike"
        assert m["Systemic_Panic"].dtype == bool, "Systemic_Panic must stay bool"

    return m


'''
        src = sub(src, 'def apply_coiled_alpha_logic(',
                  MACRO_FN + 'def apply_coiled_alpha_logic(',
                  'macro-lag compute_macro_regime')

        # Inserted ABOVE price_jump_threshold on purpose. apply_fixes.py --fix1
        # anchors on a three-line span (price_jump_threshold + min_history_days
        # + the closing paren), so adding a parameter inside that span would
        # break fix1's anchor and make the two scripts order-dependent. This
        # position leaves fix1's anchor untouched, so the two can be applied in
        # either order.
        src = sub(src,
                  '    use_rs_ratio_as_signal: bool = False, '
                  '# keep False; see caveat above\n'
                  '    price_jump_threshold: float = 0.40,   '
                  '# corporate-action artifact guard',
                  '    use_rs_ratio_as_signal: bool = False, '
                  '# keep False; see caveat above\n'
                  '    lag_macro_gates: bool = True,         '
                  '# see section 7b; keep True\n'
                  '    price_jump_threshold: float = 0.40,   '
                  '# corporate-action artifact guard',
                  'macro-lag signature')

        src = sub(src, '    nifty_df : optional. Nifty 50 index dataframe, columns',
                  '''    lag_macro_gates : keep True. Lags Market_Breadth by one trading DATE
         (section 7b), enforcing that the Sniper's market-wide gate is as of
         the previous close, since the Sniper fills at this bar's OPEN. Set
         False ONLY to reproduce the pre-2026-08-22 contaminated numbers for
         an A/B impact measurement.
    nifty_df : optional. Nifty 50 index dataframe, columns''',
                  'macro-lag param doc')

        src = sub(src, '''    df["Market_Breadth"] = np.where(
        df["Liquid_Market_Size"] > 0,
        df["Uptrend_Count"] / df["Liquid_Market_Size"],
        0,
    )

    return df''', '''    df["Market_Breadth"] = np.where(
        df["Liquid_Market_Size"] > 0,
        df["Uptrend_Count"] / df["Liquid_Market_Size"],
        0,
    )

    # ------------------------------------------------------------------
    # 7b. MACRO DECISION-TIMING LAG — Market_Breadth
    #
    #     Market_Breadth is the single most load-bearing macro gate in the
    #     system. In wfo_engine.py / live_pipeline.py it sets BOTH:
    #
    #       max_bb_pos     6 slots if >0.65, 3 if >=0.50, else 1
    #       the bb/mr split  0.80/0.20, 0.60/0.40, or 0.35/0.65 in BULL
    #
    #     so a single tier change swings Sniper capital by more than 2x. It
    #     was computed from THIS bar's closes and consumed to authorise
    #     Sniper entries that fill at THIS bar's OPEN — look-ahead, and in
    #     the flattering direction (most capital on days that turn out
    #     strong). apply_fixes.py --fix1 lagged the per-stock decision
    #     inputs and missed this one, so fix1 alone was not sufficient.
    #
    #     LAGGED BY DATE, NOT BY SYMBOL. This is the one place where the
    #     groupby("SYMBOL").shift(1) pattern used in section 5b would be
    #     WRONG: breadth is a market-wide scalar, identical for every symbol
    #     on a date. Shifting within SYMBOL would hand a stock that did not
    #     trade yesterday a breadth reading from a different (older) date
    #     than its neighbours got, so different stocks would be gated on
    #     different days' breadth on the same bar. Mapping a date-indexed
    #     shifted series keeps one breadth value per date for everyone.
    #
    #     The first date in the panel gets 0.0 (no prior session exists),
    #     which reads as "worst tier" — 1 Sniper slot, 0.35 allocation in
    #     BULL. That is the conservative direction, and the min_history_days
    #     warmup gate means no entry can fire there anyway.
    # ------------------------------------------------------------------
    df["Market_Breadth_Today"] = df["Market_Breadth"]   # unlagged, diagnostics only

    if lag_macro_gates:
        _breadth_by_date = df.groupby("DATE")["Market_Breadth"].first().sort_index()
        df["Market_Breadth"] = (
            df["DATE"].map(_breadth_by_date.shift(1)).astype(float).fillna(0.0)
        )

        assert not df["Market_Breadth"].isna().any(), \\
            "NaN leaked into Market_Breadth"
        assert df.groupby("DATE")["Market_Breadth"].nunique().max() <= 1, \\
            "Market_Breadth is no longer constant within a DATE"

    return df''', 'macro-lag breadth')

        save(name, src)
        applied.append('macro-lag  coiled_alpha_logic.py  '
                       '(compute_macro_regime + breadth lag)')

    # -----------------------------------------------------------------
    # 2/4  data_prep_updated.py -- call the shared implementation
    # -----------------------------------------------------------------
    name, src = load('data_prep_updated.py')
    if 'compute_macro_regime' in src:
        skipped.append('macro-lag  data_prep_updated.py  (already applied)')
    else:
        src = sub(src,
                  'from coiled_alpha_logic import apply_coiled_alpha_logic  '
                  '# the new Sniper entry logic',
                  'from coiled_alpha_logic import (\n'
                  '    apply_coiled_alpha_logic,   # the new Sniper entry logic\n'
                  '    compute_macro_regime,       # the SHARED macro gates -- '
                  'live_pipeline.py calls\n'
                  '                                # the same function, so the two '
                  'cannot drift\n'
                  ')',
                  'macro-lag data_prep import')

        src = replace_between(
            src,
            "    macro['NIFTY_SMA_200'] = macro['NIFTY_CLOSE'].rolling(window=200).mean()",
            "else:\n    print(\"Warning: Could not fetch Nifty data.",
            '''    # The macro gates now come from the ONE shared implementation in
    # coiled_alpha_logic.py, so the backtest and the live pipeline cannot
    # diverge (they had: live hardcoded VIX_Spike = False).
    #
    # Regime_Label and VIX_Spike come back LAGGED one trading session because
    # the Sniper fills at OPEN(t) and may therefore only use close(t-1).
    # Systemic_Panic comes back UNLAGGED because MR fills at CLOSE(t).
    # See compute_macro_regime's docstring for the full argument.
    macro = compute_macro_regime(macro)

''',
            'macro-lag data_prep macro block')

        save(name, src)
        applied.append('macro-lag  data_prep_updated.py  (uses shared macro impl)')

    # -----------------------------------------------------------------
    # 3/4  live_pipeline.py -- fetch High/Low, call the shared impl
    # -----------------------------------------------------------------
    name, src = load('live_pipeline.py')
    if 'compute_macro_regime' in src:
        skipped.append('macro-lag  live_pipeline.py  (already applied)')
    else:
        src = sub(src,
                  'from coiled_alpha_logic import apply_coiled_alpha_logic',
                  'from coiled_alpha_logic import (\n'
                  '    apply_coiled_alpha_logic,\n'
                  '    compute_macro_regime,       # SHARED with data_prep_updated.py '
                  '-- do not\n'
                  '                                # reimplement the macro gates here '
                  'again\n'
                  ')',
                  'macro-lag live import')

        src = replace_between(
            src,
            "    if isinstance(nifty.columns, pd.MultiIndex):\n"
            "        close_col = nifty['Close'].iloc[:, 0]",
            "def update_master_data():",
            '''    if isinstance(nifty.columns, pd.MultiIndex):
        close_col = nifty['Close'].iloc[:, 0]
        high_col = nifty['High'].iloc[:, 0]
        low_col = nifty['Low'].iloc[:, 0]
    else:
        close_col = nifty['Close']
        high_col = nifty['High']
        low_col = nifty['Low']

    # NIFTY_HIGH / NIFTY_LOW are REQUIRED, not optional. compute_macro_regime
    # needs Nifty's own true range for VIX_Spike. Until 2026-08-22 this
    # function returned CLOSE only and the caller set VIX_Spike = False, so
    # live never blocked Sniper entries on a volatility spike while the
    # backtest did. yfinance was already downloading High and Low; they were
    # simply being thrown away.
    macro = pd.DataFrame({
        'DATE': close_col.index,
        'NIFTY_CLOSE': close_col.values,
        'NIFTY_HIGH': high_col.values,
        'NIFTY_LOW': low_col.values,
    })
    macro['DATE'] = pd.to_datetime(macro['DATE']).dt.tz_localize(None).dt.normalize()
    return macro


''',
            'macro-lag live nifty fetch')

        src = replace_between(
            src,
            "    macro = macro.sort_values('DATE').reset_index(drop=True)",
            "    signals_df = signals_df.merge(",
            '''    # ONE shared macro implementation, see coiled_alpha_logic.py. This
    # replaces a hand-copied block that had drifted from the backtest's
    # version: VIX_Spike used to be hardcoded False here.
    #
    # Regime_Label and VIX_Spike come back LAGGED one trading session (the
    # Sniper fills at OPEN, so it may only use the previous close);
    # Systemic_Panic comes back unlagged (MR fills at CLOSE).
    macro = compute_macro_regime(macro)

''',
            'macro-lag live macro block')

        save(name, src)
        applied.append('macro-lag  live_pipeline.py  '
                       '(real VIX_Spike + shared macro impl)')

    # -----------------------------------------------------------------
    # 4/4  wfo_engine_updated.py -- documentation only.
    #      The engine needs NO code change: it reads Market_Breadth /
    #      Regime_Label / VIX_Spike straight off the row, and those columns
    #      now arrive lagged. Leaving the engine untouched is deliberate --
    #      run_headless_simulation is duplicated across several files, so
    #      every hand-edit there is a live/backtest drift risk.
    # -----------------------------------------------------------------
    name, src = load('wfo_engine_updated.py')
    if 'MACRO GATES ARRIVE PRE-LAGGED' in src:
        skipped.append('macro-lag  wfo_engine_updated.py  (already applied)')
    else:
        src = sub(src,
                  "        current_breadth = todays_rows[0]['Market_Breadth'] "
                  "if todays_rows else 0",
                  "        # MACRO GATES ARRIVE PRE-LAGGED (since 2026-08-22, finding #32).\n"
                  "        # Market_Breadth, Regime_Label and VIX_Spike on this row are as of\n"
                  "        # the PREVIOUS trading session, because the Sniper block below fills\n"
                  "        # at this row's OPEN and may not use this row's own close. The lag\n"
                  "        # lives in coiled_alpha_logic.py (sections 7b and\n"
                  "        # compute_macro_regime), NOT here -- do not add a second shift.\n"
                  "        # Systemic_Panic is deliberately still same-bar: MR fills at CLOSE.\n"
                  "        current_breadth = todays_rows[0]['Market_Breadth'] "
                  "if todays_rows else 0",
                  'macro-lag engine note')
        save(name, src)
        applied.append('macro-lag  wfo_engine_updated.py  (comment only, no logic change)')


# =====================================================================
# IDLE-YIELD -- units bug + 4%/yr in both engine and live
# =====================================================================
if args.idle_yield:

    # -----------------------------------------------------------------
    # 1/2  wfo_engine_updated.py
    # -----------------------------------------------------------------
    name, src = load('wfo_engine_updated.py')
    if 'IDLE_YIELD_PCT' in src:
        skipped.append('idle-yield  wfo_engine_updated.py  (already applied)')
    else:
        src = sub(src, 'MAX_GAP_LOSS_PCT = 0.03',
                  '''# Idle yield on uninvested sleeve cash. Both numbers below are load-bearing
# and were wrong together until 2026-08-22.
#
# THE UNITS BUG: run_headless_simulation accrues yield once per element of
# calendar_dates, and calendar_dates is built from the panel's DATE column --
# i.e. TRADING days, ~252 a year, not 365. Dividing an annual rate by 365 and
# then accruing it only 252 times delivers 252/365 = 69% of the stated rate.
# Every Phase 1 number was produced with idle_yield = 6.0 meaning an effective
# 4.23%/yr. Dividing by TRADING_DAYS_PER_YEAR makes the parameter mean what it
# says, so this constant is now honest rather than nominal.
#
# THE RATE: 4.0 is dell's chosen assumption (2026-08-22), replacing 6.0. It is
# also very close to what the old code was ACTUALLY delivering, so this change
# should barely move the headline -- see the note in ENGINEERING_CHANGELOG.md.
#
# REALITY CHECK, because this is modelled income and not a trade: 4%/yr on
# idle cash is only real if idle cash is genuinely swept into a liquid or
# overnight fund. If it sits in an un-swept broker ledger earning nothing, this
# constant should be 0.0 and every CAGR here is overstated by roughly the
# average idle fraction times 4%.
TRADING_DAYS_PER_YEAR = 252
IDLE_YIELD_PCT = 4.0

MAX_GAP_LOSS_PCT = 0.03''', 'idle-yield engine constants')

        src = sub(src, "    daily_yield_rate = (p['idle_yield'] / 100) / 365",
                  "    # / TRADING_DAYS_PER_YEAR, not / 365: this rate is applied once per\n"
                  "    # element of calendar_dates, and those are TRADING days. See the\n"
                  "    # IDLE_YIELD_PCT comment at the top of this file.\n"
                  "    daily_yield_rate = (p['idle_yield'] / 100) / TRADING_DAYS_PER_YEAR",
                  'idle-yield engine rate')

        src = sub(src, "'idle_yield': 6.0,", "'idle_yield': IDLE_YIELD_PCT,",
                  'idle-yield engine constant use')
        save(name, src)
        applied.append('idle-yield  wfo_engine_updated.py  (252-day basis, 4.0%)')

    # -----------------------------------------------------------------
    # 2/2  live_pipeline.py -- live credited NO yield at all (finding #29)
    # -----------------------------------------------------------------
    name, src = load('live_pipeline.py')
    if 'def accrue_idle_yield(' in src:
        skipped.append('idle-yield  live_pipeline.py  (already applied)')
    else:
        src = sub(src, 'SLIPPAGE_TAX_PCT = 0.15',
                  '''SLIPPAGE_TAX_PCT = 0.15

# Idle yield on uninvested sleeve cash. MUST match wfo_engine_updated.py, or
# live equity drifts from the backtest that validated these parameters for a
# reason that has nothing to do with trading. Until 2026-08-22 the backtest
# credited yield and live credited NONE (finding #29), so live was structurally
# behind by roughly the idle fraction times the rate, every single day.
IDLE_YIELD_PCT = 4.0           # keep equal to wfo_engine_updated.IDLE_YIELD_PCT
TRADING_DAYS_PER_YEAR = 252    # keep equal to wfo_engine_updated.TRADING_DAYS_PER_YEAR
MAX_YIELD_CATCHUP_DAYS = 25    # refuse to credit more than this in one run''',
                  'idle-yield live constants')

        YIELD_FNS = '''def trading_days_since(window_df, last_date_str, target_date):
    """How many NSE trading sessions fall in (last_run_date, target_date].

    Counted from the bhavcopy panel itself rather than from a hardcoded holiday
    calendar, so it stays correct through NSE's irregular holidays without
    anything to maintain. Returns 1 when there is no last_run_date (a fresh or
    just-reset state file), which is the normal single-session case.

    This exists because a missed run must not silently skip yield. GitHub
    Actions outages happen, and the backtest accrues on every trading session
    with no concept of a missed one -- so live has to catch up to stay at
    parity.
    """
    if not last_date_str:
        return 1
    try:
        last = pd.to_datetime(last_date_str).normalize()
        this = pd.to_datetime(target_date).normalize()
    except Exception as e:
        print(f"WARNING: could not parse dates for the yield catch-up ({e}); "
              f"crediting a single session.")
        return 1
    dates = pd.to_datetime(pd.Series(window_df['DATE'].unique())).dt.normalize()
    return int(((dates > last) & (dates <= this)).sum())


def accrue_idle_yield(state, window_df, target_date):
    """Credit idle yield on uninvested sleeve cash, matching the backtest.

    Called from main() BEFORE the allocation rebalance and before exits, which
    is the order run_headless_simulation uses (yield -> rebalance -> exits ->
    entries). Order matters: yield raises cash, cash feeds the rebalance base,
    and the rebalance base sizes the day's entries.

    Compounds over n sessions with (1 + r)**n - 1 rather than n * r, because
    the engine adds each day's yield to cash before the next day's accrual, so
    its cash compounds too. For a single session the two are identical; they
    only differ on a catch-up.
    """
    n_days = trading_days_since(window_df, state.get('last_run_date', ''), target_date)

    if n_days <= 0:
        print("Idle yield: 0 new trading sessions, nothing accrued.")
        return 0.0

    if n_days > MAX_YIELD_CATCHUP_DAYS:
        # Loud, not silent. A number this large means the state file is stale
        # or corrupt, and quietly crediting a year of yield in one run would
        # be a far worse outcome than an obviously wrong-looking report.
        print(f"WARNING: idle yield asked to cover {n_days} trading sessions, "
              f"which is more than MAX_YIELD_CATCHUP_DAYS={MAX_YIELD_CATCHUP_DAYS}. "
              f"Capping. Check state['last_run_date'] -- this usually means the "
              f"pipeline has not run for a long time or the state file is stale.")
        n_days = MAX_YIELD_CATCHUP_DAYS

    factor = (1 + (IDLE_YIELD_PCT / 100) / TRADING_DAYS_PER_YEAR) ** n_days - 1
    bb_yield = max(0.0, state['bb_cash']) * factor
    mr_yield = max(0.0, state['mr_cash']) * factor

    state['bb_cash'] += bb_yield
    state['bb_equity'] += bb_yield
    state['mr_cash'] += mr_yield
    state['mr_equity'] += mr_yield

    print(f"Idle yield: {n_days} session(s) at {IDLE_YIELD_PCT}%/yr -> "
          f"Sniper +{bb_yield:,.2f}, MR +{mr_yield:,.2f}")
    return bb_yield + mr_yield


'''
        src = sub(src, 'def load_state():', YIELD_FNS + 'def load_state():',
                  'idle-yield live functions')

        src = sub(src, '    state = load_state()',
                  '    state = load_state()\n\n'
                  '    # Yield first, matching the engine order (yield -> rebalance ->\n'
                  '    # exits -> entries). This is a no-op unless --run-guard is also\n'
                  '    # applied: without the duplicate-run guard, a second run on the\n'
                  '    # same bhavcopy would accrue a second time.\n'
                  '    accrue_idle_yield(state, window_df, target_date)',
                  'idle-yield live call')
        save(name, src)
        applied.append('idle-yield  live_pipeline.py  (4.0%/yr accrual added)')


# =====================================================================
# RUN-GUARD -- finding #33
# =====================================================================
if args.run_guard:
    name, src = load('live_pipeline.py')
    if 'def is_new_trading_date(' in src:
        skipped.append('run-guard  live_pipeline.py  (already applied)')
    else:
        GUARD_FN = '''def is_new_trading_date(target_date):
    """True if target_date is genuinely newer than the last processed session.

    FINDING #33 (2026-08-22). state['last_run_date'] was written on every run
    and never read, so nothing stopped the pipeline re-processing a bhavcopy it
    had already processed. That happens in practice: the schedule is Mon-Fri,
    so every NSE holiday makes find_latest_available_bhavcopy fall back to the
    previous session, and any manual workflow_dispatch or Actions retry does
    the same.

    What a duplicate run did to the state file:
      * every MR position aged an extra session -- evaluate_exits does
        `pos['trading_days'] += 1` unconditionally, so a position hit its time
        stop early. On an mr_time of 5 sessions, one duplicate run is a 20%
        distortion of the holding period, biased toward premature exits.
      * equity_curve_log gained a second row for the same date, quietly
        corrupting any drawdown or CAGR computed from it later.
      * any Sniper slot left unfilled could fill against the SAME bar's prices
        on the second pass.
      * and once idle yield exists in live, it accrues twice.

    FAILS OPEN, deliberately: if the state file cannot be read or its date
    cannot be parsed, this returns True with a loud warning rather than
    blocking. A silent permanent halt is a worse failure mode for a scheduled
    job than one duplicated session, and last_run_date is written by this same
    code in a known format, so a parse failure is close to impossible.

    Override with JANUS_FORCE_RERUN=1 -- intended for replaying a session after
    fixing a bug, and it is on the caller to reset the state file first.
    """
    force = os.environ.get('JANUS_FORCE_RERUN', '') == '1'

    try:
        last_raw = load_state().get('last_run_date', '')
    except Exception as e:
        print(f"WARNING: could not read state for the duplicate-run guard ({e}); "
              f"proceeding without it.")
        return True

    if not last_raw:
        return True   # fresh or freshly reset state file

    try:
        last = pd.to_datetime(last_raw).normalize()
        this = pd.to_datetime(target_date).normalize()
    except Exception as e:
        print(f"WARNING: could not parse last_run_date={last_raw!r} ({e}); "
              f"proceeding without the guard.")
        return True

    if this > last:
        return True

    if force:
        print(f"JANUS_FORCE_RERUN=1: re-processing {this.date()} even though "
              f"last_run_date is {last.date()}. State was NOT reset for you -- "
              f"MR holding periods and the equity curve will double-count.")
        return True

    print(f"\\nAlready processed {this.date()} (last_run_date={last.date()}). "
          f"Nothing to do.\\n"
          f"This is the EXPECTED path on an NSE holiday: the schedule runs "
          f"Mon-Fri, no new bhavcopy was published, so the newest available one "
          f"is the session already in the state file.\\n"
          f"Exiting without touching state. Set JANUS_FORCE_RERUN=1 to override.")
    return False


'''
        src = sub(src, 'def load_state():', GUARD_FN + 'def load_state():',
                  'run-guard function')

        src = sub(src,
                  '    print(f"Processing data for actual trading date: '
                  '{target_date.date()}")',
                  '    print(f"Processing data for actual trading date: '
                  '{target_date.date()}")\n\n'
                  '    # --- DUPLICATE-RUN GUARD (finding #33) ---\n'
                  '    # Placed as early as target_date is known, so a holiday run also\n'
                  '    # skips the expensive signal computation. update_master_data above\n'
                  '    # is safe to have already run: it dedupes on (DATE, SYMBOL).\n'
                  '    if not is_new_trading_date(target_date):\n'
                  '        return',
                  'run-guard call')
        save(name, src)
        applied.append('run-guard  live_pipeline.py  (refuses duplicate sessions)')


# =====================================================================
# SHEETS -- trade log + richer open positions
# =====================================================================
if args.sheets:
    name, src = load('live_pipeline.py')
    if 'def build_sheet_payloads(' in src:
        skipped.append('sheets  live_pipeline.py  (already applied)')
    else:
        SHEETS = '''def _sheet_cell(v):
    """Coerce one value into something gspread can actually serialise.

    EVERY cell must pass through this. Two distinct things break the mirror,
    both found by test_sheets_payload.py on 2026-08-22:

      NaN / Infinity -- JSON has neither, so gspread raises mid-write. That
        fails DIRTY: some tabs have already been overwritten, so the sheet is
        left half-updated and the traceback is about serialisation rather than
        about the position that produced the NaN.

      numpy scalars -- np.float64 happens to subclass float, so an
        isinstance(v, float) check catches it, but np.int64 does NOT subclass
        int and sails straight through to `TypeError: Object of type int64 is
        not JSON serializable`. Share counts and prices arrive as numpy types
        whenever they came from a DataFrame row rather than from the JSON state
        file, so this is the normal path, not an exotic one.

    Hence .item() on anything numpy-shaped BEFORE the float checks, rather
    than trusting isinstance against Python's builtins.
    """
    if v is None or v == '':
        return ''
    if hasattr(v, 'item') and not isinstance(v, (str, bytes)):
        try:
            v = v.item()          # np.int64/np.float64/np.bool_ -> Python scalar
        except (ValueError, AttributeError):
            return str(v)         # 0-d arrays and friends: stringify, never crash
    if isinstance(v, float):
        if v != v or v in (float('inf'), float('-inf')):   # NaN / +-inf
            return ''
        return round(v, 2)
    if isinstance(v, (int, bool, str)):
        return v
    return str(v)                 # Timestamps, Decimals, anything unexpected


def _num(v, default=0.0):
    """A numeric value safe to do ARITHMETIC with -- distinct from _sheet_cell,
    which produces a value safe to DISPLAY.

    The idiom this replaces, `x = d.get('k') or 0`, is wrong for exactly the
    reason the VIX_Spike lag was wrong: bool(float('nan')) is True, so `nan or
    0` evaluates to nan rather than 0. The NaN then propagates through
    Market_Value, Unrealized_PnL, and -- worst of all -- the Cum_PnL
    accumulator, where one bad trade turns every later row into NaN.
    """
    if v is None or v == '':
        return default
    if hasattr(v, 'item') and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float('inf'), float('-inf')):
        return default
    return v if isinstance(v, int) else f


def _sessions_held(state, entry_date):
    """Trading sessions a position has been held, derived from
    equity_curve_log (the pipeline appends exactly one row per processed
    session, so counting rows counts sessions).

    Counts sessions STRICTLY AFTER entry_date. That choice makes this equal to
    the MR sleeve's own `trading_days` counter -- the number its time stop
    actually fires on -- instead of being off by one against it, and it gives
    Sniper positions the same meaning even though they carry no counter of
    their own. That missing counter is why Days_Held was blank for every
    Sniper row in the sheet before 2026-08-22.
    """
    log = state.get('equity_curve_log') or []
    if not log or not entry_date:
        return ''
    entry = str(entry_date)[:10]
    return len({str(e.get('date', ''))[:10] for e in log
                if str(e.get('date', ''))[:10] > entry})


def build_sheet_payloads(state, today_lookup=None, context=None):
    """state -> the exact row lists written to each tab.

    Split out from update_sheet_mirror as a pure function so it can be tested
    without gspread installed, without credentials and without network: the
    formatting is where the bugs live, not in the API call.
    """
    today_lookup = today_lookup or {}
    context = context or {}

    # ---------------------------- Open_Positions ----------------------
    open_rows = [['Sleeve', 'Symbol', 'Entry_Date', 'Sessions_Held', 'Shares',
                  'Entry_Price', 'Last_Close', 'Stop_Price', 'Target_Price',
                  'Pct_To_Stop', 'Pct_To_Target', 'Cost', 'Market_Value',
                  'Unrealized_PnL', 'Unrealized_Pct']]

    def _position_row(sleeve, sym, pos):
        # _num, not `or 0`: bool(float('nan')) is True in Python, so
        # `pos.get('shares') or 0` HANDS BACK THE NaN instead of replacing it,
        # and a NaN share count then propagates into Market_Value, Unrealized
        # and the JSON write. Same trap as the VIX_Spike lag.
        shares = _num(pos.get('shares'))
        entry_px = pos.get('entry_price')
        cost = pos.get('net_cost')
        if cost in (None, ''):
            cost = shares * entry_px if (shares and entry_px) else None

        last = (today_lookup.get(sym) or {}).get('CLOSE')
        stop = pos.get('stop_price', '')      # MR carries neither
        target = pos.get('target_price', '')

        mv = shares * last if (last and shares) else None
        unreal = mv - cost if (mv is not None and cost) else None
        unreal_pct = unreal / cost * 100 if (unreal is not None and cost) else None
        pct_stop = (last - stop) / last * 100 if (last and stop not in (None, '')) else None
        pct_target = (target - last) / last * 100 if (last and target not in (None, '')) else None

        return [sleeve, sym, _sheet_cell(pos.get('entry_date', '')),
                _sessions_held(state, pos.get('entry_date', '')),
                _sheet_cell(shares), _sheet_cell(entry_px), _sheet_cell(last),
                _sheet_cell(stop), _sheet_cell(target),
                _sheet_cell(pct_stop), _sheet_cell(pct_target),
                _sheet_cell(cost), _sheet_cell(mv),
                _sheet_cell(unreal), _sheet_cell(unreal_pct)]

    for sym, pos in (state.get('active_bb') or {}).items():
        open_rows.append(_position_row('Sniper', sym, pos))
    for sym, pos in (state.get('active_mr') or {}).items():
        open_rows.append(_position_row('MR', sym, pos))

    # ---------------------------- Trade_Log ---------------------------
    # state['closed_trades_log'] has been populated since day one and was
    # never surfaced anywhere -- the whole trade history existed only inside
    # the JSON state file.
    trades = list(state.get('closed_trades_log') or [])
    trades.sort(key=lambda t: (str(t.get('exit_date', '')), str(t.get('symbol', ''))))

    log_rows = [['Exit_Date', 'Sleeve', 'Symbol', 'Entry_Date', 'Shares',
                 'Entry_Price', 'Exit_Price', 'PnL', 'Return_Pct',
                 'Exit_Reason', 'Cum_PnL']]
    body, running = [], 0.0
    for t in trades:
        # _num throughout. A NaN pnl reaching `running` would not just blank one
        # cell -- it would make Cum_PnL NaN for that row and EVERY row after it,
        # because the accumulator itself becomes NaN. Realized PnL, Win Rate and
        # Profit Factor below read the same field.
        pnl = _num(t.get('pnl'))
        running += pnl
        shares = _num(t.get('shares'))
        entry_px = _num(t.get('entry_price'))
        basis = shares * entry_px
        body.append([_sheet_cell(t.get('exit_date', '')), t.get('sleeve', ''),
                     t.get('symbol', ''), _sheet_cell(t.get('entry_date', '')),
                     _sheet_cell(shares),
                     _sheet_cell(entry_px), _sheet_cell(t.get('exit_price')),
                     _sheet_cell(pnl),
                     _sheet_cell(pnl / basis * 100 if basis else None),
                     t.get('exit_reason', ''), _sheet_cell(running)])
    # Newest first so the useful end of the log is visible without scrolling.
    # Cum_PnL was accumulated chronologically, so each row still shows the
    # running total AS OF that trade.
    log_rows.extend(reversed(body))

    # ---------------------------- Equity_Summary -----------------------
    # _num on every pnl read: a NaN would make `> 0` False and `<= 0` False, so
    # the trade would vanish from BOTH gross_profit and gross_loss while still
    # counting in len(trades) -- a silently wrong win rate and profit factor.
    wins = [t for t in trades if _num(t.get('pnl')) > 0]
    gross_profit = sum(_num(t.get('pnl')) for t in wins)
    gross_loss = -sum(_num(t.get('pnl')) for t in trades if _num(t.get('pnl')) <= 0)

    # Open risk: what walking every Sniper stop from here would cost. MR has no
    # stop, so it contributes nothing and this understates total exposure --
    # read it as "Sniper risk to stops", which is what it is called below.
    open_risk = 0.0
    for sym, pos in (state.get('active_bb') or {}).items():
        last = _num((today_lookup.get(sym) or {}).get('CLOSE'))
        stop = _num(pos.get('stop_price'))
        if last and stop:
            open_risk += max(0.0, (last - stop) * _num(pos.get('shares')))

    summary_rows = [
        ['Metric', 'Value'],
        ['Last Updated', context.get('date', state.get('last_run_date', ''))],
        ['Regime', context.get('regime', '')],
        ['Market Breadth', _sheet_cell(context.get('breadth'))],
        ['Vol Spike (Nifty ATR proxy)', str(context.get('vix_spike', ''))],
        ['', ''],
        ['Total Equity', _sheet_cell((state.get('bb_equity') or 0)
                                     + (state.get('mr_equity') or 0))],
        ['Sniper Equity', _sheet_cell(state.get('bb_equity'))],
        ['MR Equity', _sheet_cell(state.get('mr_equity'))],
        ['Sniper Cash', _sheet_cell(state.get('bb_cash'))],
        ['MR Cash', _sheet_cell(state.get('mr_cash'))],
        ['', ''],
        ['Open Positions', len(state.get('active_bb') or {})
                           + len(state.get('active_mr') or {})],
        ['Sniper Risk to Stops', _sheet_cell(open_risk)],
        ['', ''],
        ['Closed Trades', len(trades)],
        ['Realized PnL', _sheet_cell(gross_profit - gross_loss)],
        ['Win Rate %', _sheet_cell(len(wins) / len(trades) * 100 if trades else None)],
        ['Profit Factor', _sheet_cell(gross_profit / gross_loss) if gross_loss > 0
                          else 'n/a (no losing trades yet)'],
    ]

    return {'Open_Positions': open_rows,
            'Trade_Log': log_rows,
            'Equity_Summary': summary_rows}


def update_sheet_mirror(state, today_lookup=None, context=None):
    """Write-only Google Sheets dashboard. Never read back -- state JSON is
    the source of truth. If GCP_SA_JSON isn't configured, silently skip
    (Sheets is a nice-to-have visibility layer, not a dependency).

    Every tab is rewritten in full on every run rather than appended to. That
    keeps the never-read-back invariant absolute: an append needs to know how
    many rows are already there, which means reading the sheet, which is
    exactly the coupling this design rejects. At roughly 100 trades a year the
    full rewrite stays trivially small.
    """
    if not GCP_SA_JSON:
        print("GCP_SA_JSON not configured, skipping Sheets mirror.")
        return

    # Built before the try block on purpose: a formatting bug should surface as
    # a real traceback, not get swallowed by the network-error handler below.
    payloads = build_sheet_payloads(state, today_lookup, context)

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_dict = json.loads(GCP_SA_JSON)
        scopes = ['https://www.googleapis.com/auth/spreadsheets',
                  'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open('Janus Portfolio')

        for tab, rows in payloads.items():
            n_rows = max(len(rows) + 20, 50)
            n_cols = max(len(rows[0]), 2)
            try:
                ws = sh.worksheet(tab)
                # Grow the grid BEFORE writing. add_worksheet's row count is a
                # hard grid limit, not a hint, and ws.clear() does not resize;
                # the old code created these tabs at rows=100, so the write
                # would have started failing once the trade log outgrew that.
                ws.resize(rows=n_rows, cols=n_cols)
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(tab, rows=n_rows, cols=n_cols)
            ws.clear()
            ws.update(rows)
            print(f"  Sheets: {tab} <- {len(rows) - 1} data row(s)")

        print("Sheet mirror updated.")
    except Exception as e:
        print(f"Sheet mirror update FAILED (non-fatal, continuing): {e}")


'''
        src = replace_between(src, 'def update_sheet_mirror(state):',
                              '# ==========================================\n# MAIN',
                              SHEETS, 'sheets function')

        src = sub(src, '    update_sheet_mirror(state)',
                  '''    update_sheet_mirror(state, today_lookup, {
        'date': str(target_date.date()),
        'regime': today_regime,
        'breadth': current_breadth,
        'vix_spike': today_rows[0].get('VIX_Spike', False) if today_rows else False,
    })''', 'sheets call site')
        save(name, src)
        applied.append('sheets  live_pipeline.py  (Trade_Log + enriched tabs)')


# =====================================================================
# FINDING #34 -- generate_live_params.py carries a STALE COPY of the engine
# =====================================================================
# This is the script that writes live_params.json, i.e. the parameters actually
# traded. It contains its own hand-maintained duplicate of
# run_headless_simulation and calculate_fitness, under the comment
#
#     """Identical logic to wfo_engine_updated.py -- kept in sync manually.
#     TODO: extract to a shared module both scripts import, to eliminate the
#     risk of these two copies drifting apart over time."""
#
# The risk that comment names is exactly what happened. Neither apply_fixes.py
# nor the other flags in this script ever touched this file, so as of
# 2026-08-22 it still carried BOTH units bugs after the engine was fixed:
#
#   * daily_yield_rate = (p['idle_yield'] / 100) / 365   <- the idle-yield bug
#   * cagr = (final / initial) ** (365.25 / days)        <- finding #28
#   * 'idle_yield': 6.0 hardcoded                        <- the old rate
#
# The CAGR one is the serious one. test_cagr_units.py TEST 3 demonstrates that
# the inflated CAGR pushes candidates into the norm_sortino = min(s/3, 1.0) cap,
# where the risk-adjusted term stops discriminating and selection falls through
# to profit factor / win rate / trade count. So this is not a cosmetic reporting
# bug in a reporting script -- it changes WHICH PARAMETERS GET TRADED. It was
# fixed in the engine, whose output is historical analysis, and left unfixed in
# the script whose output is the live config. That is the wrong way round.
#
# WHY PATCH THE DUPLICATE INSTEAD OF DELETING IT
# The honest fix is one shared module. I did not do that here, because a
# comment-stripped diff of the two copies (2026-08-22) showed the behavioural
# delta is exactly four things and nothing else:
#     1. the /365 idle-yield divisor            (real bug, fixed below)
#     2. the 365.25/days CAGR exponent          (real bug, fixed below)
#     3. hardcoded 0.03 / 0.20 in gap_safe_shares, where the engine uses
#        MAX_GAP_LOSS_PCT / ASSUMED_WORST_CASE_GAP_PCT. Numerically IDENTICAL
#        today, so this is latent rather than active drift -- but if the engine's
#        constants are ever retuned, live params silently would not follow.
#        Named below so that cannot happen.
#     4. cosmetic line-splitting, plus a total_pnl accumulator the engine
#        computes and never returns (dead code there, absent here).
# Both copies return the same 7-tuple. Given that, swapping in the engine's
# 223-line version wholesale would be a much larger behavioural change than the
# bugs being fixed, on the live config path, for no measured benefit. Patching
# in place is the lower-risk correction; test_engine_copy_parity.py then makes
# "kept in sync manually" a CHECKED invariant instead of a hope, which is the
# part that actually prevents a fourth recurrence.
# =====================================================================
if args.live_params:
    name, src = load('generate_live_params.py')
    # Sentinel unique to THIS edit. Not 'TRADING_DAYS_PER_YEAR' and not
    # 'IDLE_YIELD_PCT' -- see the ORDER section in this file's docstring for why
    # a sentinel that merely ends up present in the file is a bug, not a guard.
    if 'COPY PARITY FIX 2026-08-22' in src:
        skipped.append('live-params  generate_live_params.py  (already applied)')
    else:
        src = sub(src, 'SLIPPAGE_TAX_PCT = 0.15',
                  '''SLIPPAGE_TAX_PCT = 0.15

# COPY PARITY FIX 2026-08-22 -- finding #34.
# These four MUST equal their namesakes in wfo_engine_updated.py. This file
# keeps its own copy of run_headless_simulation and calculate_fitness, and
# those copies had already drifted once: the engine got the idle-yield and CAGR
# units fixes and this file did not, so the params written to live_params.json
# were being SELECTED under different arithmetic than the WFO validated.
# test_engine_copy_parity.py now fails if the two copies diverge again.
TRADING_DAYS_PER_YEAR = 252        # == wfo_engine_updated.TRADING_DAYS_PER_YEAR
IDLE_YIELD_PCT = 4.0               # == wfo_engine_updated.IDLE_YIELD_PCT
MAX_GAP_LOSS_PCT = 0.03            # == wfo_engine_updated.MAX_GAP_LOSS_PCT
ASSUMED_WORST_CASE_GAP_PCT = 0.20  # == wfo_engine_updated.ASSUMED_WORST_CASE_GAP_PCT''',
                  'live-params constants')

        src = sub(src,
                  '''    """Identical logic to wfo_engine_updated.py -- kept in sync manually.
    TODO: extract to a shared module both scripts import, to eliminate the
    risk of these two copies drifting apart over time."""''',
                  '''    """A COPY of wfo_engine_updated.run_headless_simulation.

    Verified equivalent to the engine's version on 2026-08-22 by a
    comment-stripped diff: same 7-tuple return, same logic, differing only in
    line-splitting and in a total_pnl accumulator the engine never returns.

    The previous version of this docstring said "kept in sync manually", and it
    was not: the engine received the idle-yield and CAGR units fixes and this
    copy did not (finding #34). Do NOT trust the claim of equivalence above --
    run test_engine_copy_parity.py, which re-derives it mechanically. If you
    edit either copy, that test tells you immediately; if you finally extract a
    shared module, delete the test along with the duplicate."""''',
                  'live-params docstring')

        src = sub(src, "    daily_yield_rate = (p['idle_yield'] / 100) / 365",
                  "    # / TRADING_DAYS_PER_YEAR, not / 365: applied once per element of\n"
                  "    # calendar_dates, and those are TRADING days.\n"
                  "    daily_yield_rate = (p['idle_yield'] / 100) / TRADING_DAYS_PER_YEAR",
                  'live-params yield rate')

        src = sub(src,
                  "                gap_safe_shares = int((bb_equity * 0.03) / (row['OPEN'] * 0.20))",
                  "                gap_safe_shares = int((bb_equity * MAX_GAP_LOSS_PCT)\n"
                  "                                      / (row['OPEN'] * ASSUMED_WORST_CASE_GAP_PCT))",
                  'live-params gap sizing')

        src = sub(src,
                  "    cagr = ((eq_series.iloc[-1] / eq_series.iloc[0]) ** (365.25 / days) - 1) * 100",
                  "    # `days` counts TRADING days, so annualize on a 252-day year. The old\n"
                  "    # 365.25/days inflated a true 14.17% into 21.18% and, worse, pushed\n"
                  "    # candidates into the norm_sortino cap where selection stops\n"
                  "    # discriminating on risk. See test_cagr_units.py TEST 3.\n"
                  "    years = days / TRADING_DAYS_PER_YEAR\n"
                  "    cagr = (((eq_series.iloc[-1] / eq_series.iloc[0]) ** (1 / years) - 1) * 100\n"
                  "            if years > 0 else 0.0)",
                  'live-params cagr units')

        src = sub(src, "'idle_yield': 6.0,", "'idle_yield': IDLE_YIELD_PCT,",
                  'live-params idle rate')
        save(name, src)
        applied.append('live-params  generate_live_params.py  (252-day yield, CAGR '
                       'units, 4.0%, named gap constants)')


# =====================================================================
print()
if applied:
    print('APPLIED:')
    for a in applied:
        print('  ' + a)
if skipped:
    print('SKIPPED (idempotent):')
    for s in skipped:
        print('  ' + s)
if not applied:
    print('Nothing changed.')
if args.out:
    print(f"\nDRY RUN: patched copies written to {args.out}; "
          f"{args.dir} was not modified.")
print()
