"""
coiled_alpha_logic.py
----------------------
SCHEMA VERSION: matches actual data_prep.py column names
  DATE, SYMBOL, CLOSE, HIGH, LOW, VOLUME.

Replacement for the old `apply_blue_box_logic` (retail RSI/EMA/Volume stack).

IMPORTANT — pipeline integrity: in the V9 architecture, Turnover_SMA_50 and
Daily_Turnover_Rank were computed inside the old apply_blue_box_logic, and
apply_mean_reversion_logic (which runs immediately after) depends on
Turnover_SMA_50 existing. Since the old function is being deleted entirely,
THIS function now builds those base columns itself, at the very top, before
computing anything else — otherwise the MR sleeve breaks downstream.

Institutional entry logic for the Trend-Following "Sniper" sleeve:

  0. Base turnover/liquidity metrics -> Turnover_SMA_50, Daily_Turnover_Rank,
                                         Is_Liquid (also required by the MR
                                         sleeve downstream)
  1. True Relative Strength  -> only scan SYMBOLs in the top X% of 60-day
                                 performance vs. Nifty 50 (cross-sectional,
                                 computed fresh per DATE across the whole
                                 market, not a rolling per-stock rank)
  2. Volatility Contraction  -> short-term ATR shrinking vs long-term ATR
  3. Liquidity               -> top X% of Turnover_SMA_50 (Is_Liquid)
  4. Trend confirmation      -> closing within X% of the 50-day high
  7. Market_Breadth          -> carried over unchanged from legacy logic;
                                 not part of the entry rewrite, but
                                 required by wfo_engine.py for slot
                                 sizing / MR entry gating

Design / look-ahead notes:

- Every rolling stat is computed per-SYMBOL (groupby('SYMBOL')) so one
  stock's history never leaks into another's window.
- RS_Percentile and Daily_Turnover_Rank are computed per-DATE
  (groupby('DATE')) — "top 10%" = top 10% of the ENTIRE MARKET that day.
- Signal at close(t) -> intended execution at open(t+1), same convention
  as MR_Base_Signal.
- RS is computed two ways:
    RS_Excess = stock_60d_return - nifty_60d_return   <- DEFAULT / recommended
    RS_Ratio  = stock_60d_return / nifty_60d_return   <- legacy, diagnostics only
  RS_Ratio's sign inverts when nifty_60d_return < 0 (i.e. exactly at the
  Bull/Bear regime boundary where correct ranking matters most). Use
  RS_Excess unless you've specifically validated RS_Ratio performs better
  in your WFO.
"""

import numpy as np
import pandas as pd


def apply_coiled_alpha_logic(
    df: pd.DataFrame,
    nifty_df: pd.DataFrame = None,
    rs_lookback: int = 60,
    rs_percentile: float = 0.90,          # top 10% strongest stocks
    atr_short: int = 14,
    atr_long: int = 50,
    high_lookback: int = 50,
    high_proximity: float = 0.15,         # within 15% of 50-day high
    liquidity_percentile: float = 0.85,   # top 15% of turnover
    use_rs_ratio_as_signal: bool = False, # keep False; see caveat above
    price_jump_threshold: float = 0.40,   # corporate-action artifact guard
    min_history_days: int = None,
) -> pd.DataFrame:
    """
    Adds Coiled Alpha diagnostic columns and a final boolean signal
    'BB_Enter_Today' to the input panel dataframe. Also builds
    Turnover_SMA_50 / Daily_Turnover_Rank / Is_Liquid from scratch (these
    are required by the downstream MR sleeve too).

    Parameters
    ----------
    df : full stock panel, long format, columns:
         ['DATE', 'SYMBOL', 'CLOSE', 'HIGH', 'LOW', 'VOLUME', ...]
         May ALREADY contain 'NIFTY_CLOSE' if the macro/index data has been
         merged into the panel upstream (broadcast per DATE across all
         SYMBOLs) — in that case nifty_df is not needed and is ignored.
    nifty_df : optional. Nifty 50 index dataframe, columns
         ['DATE', 'NIFTY_CLOSE'] (matches the `macro` dataframe produced by
         the yfinance ^NSEI extraction step in data_prep.py). Only used if
         'NIFTY_CLOSE' is not already present in df. If neither is
         available, raises ValueError.

    Returns
    -------
    df : new dataframe (input not mutated) with added columns, including
         the final 'BB_Enter_Today' and 'BB_Exhaustion_Today' boolean
         columns, plus 'Target_ATR' for position sizing, and the base
         'Turnover_SMA_50' / 'Daily_Turnover_Rank' / 'Is_Liquid' columns
         the MR sleeve depends on.
    """

    df = df.copy()
    df["DATE"] = pd.to_datetime(df["DATE"])
    df = df.sort_values(["SYMBOL", "DATE"]).reset_index(drop=True)

    if min_history_days is None:
        min_history_days = max(rs_lookback, atr_long, high_lookback) + 5

    # ------------------------------------------------------------------
    # NIFTY_CLOSE resolution — handles two possible upstream states:
    #   (a) 'macro' (with NIFTY_CLOSE) was already merged into df earlier
    #       in the pipeline, broadcast onto every SYMBOL row per DATE
    #       (this appears to be the pattern the rest of the pipeline
    #       uses for Regime_Label / Market_Breadth / VIX_Spike, which
    #       wfo_engine.py reads per-row from the same panel).
    #   (b) 'macro' is still a standalone dataframe at this point and
    #       needs to be merged in here.
    # Either way, we do NOT rely on df's own row order/interleaving of
    # SYMBOLs to pct_change() the Nifty series — we always collapse to
    # one row per DATE first, so the 60-day return calc is correct
    # regardless of how many SYMBOLs are interleaved per date.
    # ------------------------------------------------------------------
    if "NIFTY_CLOSE" not in df.columns:
        if nifty_df is None:
            raise ValueError(
                "NIFTY_CLOSE not found in df and no nifty_df was passed. "
                "Either merge the 'macro' dataframe (DATE, NIFTY_CLOSE, "
                "NIFTY_HIGH, NIFTY_LOW) into df before calling this "
                "function, or pass it as nifty_df=macro."
            )
        nifty_df = nifty_df.copy()
        nifty_df["DATE"] = pd.to_datetime(nifty_df["DATE"])
        nifty_close_map = nifty_df.set_index("DATE")["NIFTY_CLOSE"]
        df["NIFTY_CLOSE"] = df["DATE"].map(nifty_close_map)

    # ------------------------------------------------------------------
    # 0. BASE LIQUIDITY & TURNOVER METRICS
    #    CRITICAL: these used to be computed inside the old
    #    apply_blue_box_logic, right at the top. Since that function is
    #    being deleted entirely, this is now the ONLY place in the
    #    pipeline that produces Turnover_SMA_50 / Daily_Turnover_Rank —
    #    and apply_mean_reversion_logic (which runs after this) depends
    #    on Turnover_SMA_50 existing. If this block is removed, the MR
    #    sleeve breaks. Must run before RS/Vol-Contraction/Trend below.
    # ------------------------------------------------------------------
    if "Turnover" not in df.columns:
        df["Turnover"] = df["CLOSE"] * df["VOLUME"]

    df["Turnover_SMA_50"] = df.groupby("SYMBOL")["Turnover"].transform(
        lambda x: x.rolling(window=50).mean()
    )
    df["Daily_Turnover_Rank"] = df.groupby("DATE")["Turnover_SMA_50"].rank(pct=True)
    df["Is_Liquid"] = df["Daily_Turnover_Rank"] >= liquidity_percentile

    # ------------------------------------------------------------------
    # 1. TRUE RELATIVE STRENGTH
    # ------------------------------------------------------------------

    df["Stock_Ret_60D"] = df.groupby("SYMBOL")["CLOSE"].pct_change(rs_lookback, fill_method=None)

    # ------------------------------------------------------------------
    # DATA INTEGRITY GUARD — corporate action artifacts (splits, reverse
    # splits/consolidations, bonus issues) in unadjusted NSE bhavcopy data
    # can manufacture fake 60-day returns of +10,000% or more, since a
    # 100:1 consolidation (confirmed to have happened on at least one
    # real NSE symbol in this dataset) makes CLOSE jump ~100x overnight
    # with zero real price change. Left unguarded, a single such artifact
    # doesn't just mislabel one stock — it distorts the CROSS-SECTIONAL
    # percentile rank (RS_Percentile) for every other stock competing for
    # that day's top-10% cutoff.
    #
    # This is a STOPGAP, not a substitute for split/bonus-adjusted price
    # data. In back-testing on a recent 3-year slice, ~1.9% of rows were
    # flagged and excluding them changed total signal count by <0.5% —
    # low enough impact to treat this as an acceptable interim guard
    # rather than a blocker, but worth revisiting with properly adjusted
    # OHLC data before trusting absolute (not just directional) results.
    # ------------------------------------------------------------------
    daily_ret = df.groupby("SYMBOL")["CLOSE"].pct_change(fill_method=None)
    suspicious_jump_today = daily_ret.abs() > price_jump_threshold
    df["Contains_Suspicious_Jump"] = (
        suspicious_jump_today.groupby(df["SYMBOL"])
        .transform(lambda s: s.rolling(rs_lookback, min_periods=1).max())
        .astype(bool)
    )

    # Collapse to one row per DATE to compute the Nifty return correctly
    # (df is sorted by SYMBOL, DATE — NOT purely by DATE — so pct_change
    # directly on df['NIFTY_CLOSE'] would be wrong; every SYMBOL row for
    # a given DATE carries the same NIFTY_CLOSE value, so dedup first).
    nifty_unique = (
        df[["DATE", "NIFTY_CLOSE"]]
        .drop_duplicates(subset="DATE")
        .sort_values("DATE")
        .reset_index(drop=True)
    )
    nifty_unique["Nifty_Ret_60D"] = nifty_unique["NIFTY_CLOSE"].pct_change(rs_lookback, fill_method=None)
    nifty_ret_map = nifty_unique.set_index("DATE")["Nifty_Ret_60D"]

    df["Nifty_Ret_60D"] = df["DATE"].map(nifty_ret_map)

    df["RS_Excess"] = df["Stock_Ret_60D"] - df["Nifty_Ret_60D"]

    with np.errstate(divide="ignore", invalid="ignore"):
        df["RS_Ratio"] = np.where(
            df["Nifty_Ret_60D"].abs() > 1e-6,
            df["Stock_Ret_60D"] / df["Nifty_Ret_60D"],
            np.nan,
        )

    rs_signal_col = "RS_Ratio" if use_rs_ratio_as_signal else "RS_Excess"

    # Mask flagged rows OUT of the ranking input entirely (set to NaN)
    # rather than just AND-ing them out of the final signal afterward —
    # this removes them from the percentile denominator so they can't
    # crowd out a real stock's rank position on that day.
    rs_rank_input = df[rs_signal_col].where(~df["Contains_Suspicious_Jump"])

    df["RS_Percentile"] = rs_rank_input.groupby(df["DATE"]).rank(
        pct=True, na_option="keep"
    )
    df["Sniper_Pass_RelativeStrength"] = df["RS_Percentile"] >= rs_percentile

    # ------------------------------------------------------------------
    # 2. VOLATILITY CONTRACTION (the "Coil")
    #    Vectorized True Range (shift + np.maximum), NOT groupby().apply()
    #    with a custom function — with a full 15-year, 1,500+ symbol NSE
    #    universe, groupby().apply() calls a Python function once per
    #    group and is materially slower. This matches the fast pattern
    #    your OLD apply_blue_box_logic already used.
    # ------------------------------------------------------------------
    df["Prev_Close"] = df.groupby("SYMBOL")["CLOSE"].shift(1)

    df["True_Range"] = np.maximum(
        df["HIGH"] - df["LOW"],
        np.maximum(
            (df["HIGH"] - df["Prev_Close"]).abs(),
            (df["LOW"] - df["Prev_Close"]).abs(),
        ),
    )

    df["ATR_Short"] = df.groupby("SYMBOL")["True_Range"].transform(
        lambda s: s.rolling(atr_short, min_periods=atr_short).mean()
    )
    df["ATR_Long"] = df.groupby("SYMBOL")["True_Range"].transform(
        lambda s: s.rolling(atr_long, min_periods=atr_long).mean()
    )

    df["ATR_Contraction_Ratio"] = df["ATR_Short"] / df["ATR_Long"]
    df["Sniper_Pass_VolContraction"] = df["ATR_Contraction_Ratio"] < 1.0

    # ------------------------------------------------------------------
    # 3. LIQUIDITY — uses Is_Liquid computed in section 0 above
    #    (single source of truth shared conceptually with the MR sleeve;
    #    Sniper applies its own top-15% threshold via `liquidity_percentile`,
    #    MR applies its own top-30% threshold on the same underlying
    #    Turnover_SMA_50 / Daily_Turnover_Rank columns)
    # ------------------------------------------------------------------
    df["Sniper_Pass_Liquidity"] = df["Is_Liquid"]

    # ------------------------------------------------------------------
    # 4. TREND CONFIRMATION (within 15% of 50-day high)
    # ------------------------------------------------------------------

    df["High_50D"] = df.groupby("SYMBOL")["HIGH"].transform(
        lambda s: s.rolling(high_lookback, min_periods=high_lookback).max()
    )
    df["Pct_From_High"] = (df["High_50D"] - df["CLOSE"]) / df["High_50D"]
    df["Sniper_Pass_TrendProximity"] = df["Pct_From_High"] <= high_proximity

    # ------------------------------------------------------------------
    # COMBINE INTO FINAL SIGNAL
    # ------------------------------------------------------------------

    df["BB_Enter_Today"] = (
        df["Sniper_Pass_RelativeStrength"]
        & df["Sniper_Pass_VolContraction"]
        & df["Sniper_Pass_Liquidity"]
        & df["Sniper_Pass_TrendProximity"]
    )

    warmup_mask = df.groupby("SYMBOL").cumcount() < min_history_days
    df.loc[warmup_mask, "BB_Enter_Today"] = False

    # ------------------------------------------------------------------
    # 5. Target_ATR — wfo_engine.py reads this exact column name for
    #    stop/target sizing: stop = OPEN - (bb_stop * Target_ATR)
    #                         tgt  = OPEN + (bb_tgt  * Target_ATR)
    #    Using the short-window ATR (same one used for the contraction
    #    check) as the sizing ATR — it's the more "live" volatility read
    #    at time of entry.
    # ------------------------------------------------------------------
    df["Target_ATR"] = df["ATR_Short"]

    # ------------------------------------------------------------------
    # 6. BB_Exhaustion_Today — CARRIED OVER FROM THE LEGACY BLUE-BOX LOGIC
    #    (unchanged from the old data_prep.py; only the entry side of the
    #    sleeve was rewritten, this exit condition is intentionally kept
    #    identical so the WFO is isolating the effect of the new entry
    #    logic, not conflating it with an exit-logic change):
    #
    #        Exhaustion_Flag = (RSI_3 >= 85) & (CLOSE < Prev_Close)
    #
    #    i.e. a hyper-fast 3-period RSI shows a parabolic climax AND
    #    today is a down-day vs. yesterday's close (buyers exhausted,
    #    sellers taking control at the top). The engine only acts on
    #    this when the position is already in profit, so this remains a
    #    take-profit-on-climax exit, not a stop.
    #
    #    RSI_3 uses the same Wilder-style ewm(com=period-1) convention as
    #    the MR sleeve's RSI_2 (com=1) for consistency: com=2 -> period=3.
    #    Prev_Close was already computed once in section 2 above.
    # ------------------------------------------------------------------
    delta = df.groupby("SYMBOL")["CLOSE"].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)

    ema_up_3 = up.groupby(df["SYMBOL"]).transform(
        lambda x: x.ewm(com=2, adjust=False).mean()
    )
    ema_down_3 = down.groupby(df["SYMBOL"]).transform(
        lambda x: x.ewm(com=2, adjust=False).mean()
    )
    df["RSI_3"] = 100 - (100 / (1 + (ema_up_3 / (ema_down_3 + 1e-8))))

    df["BB_Exhaustion_Today"] = (df["RSI_3"] >= 85) & (df["CLOSE"] < df["Prev_Close"])
    df.loc[warmup_mask, "BB_Exhaustion_Today"] = False

    # ------------------------------------------------------------------
    # 7. MARKET_BREADTH — REQUIRED DOWNSTREAM, NOT PART OF THE ENTRY
    #    LOGIC REWRITE.
    #
    #    'Market_Breadth' is in your columns_to_keep list, and
    #    wfo_engine.py reads it every day to set current_breadth, which
    #    gates BOTH the Sniper's max_bb_pos slot count AND the MR entry
    #    condition (current_breadth < 0.50). It is an independent
    #    market-wide health gauge (% of liquid stocks trading above
    #    their own 50-EMA) — NOT one of the retail entry conditions
    #    (RSI/ignition/pullback) being replaced by Coiled Alpha. It has
    #    to keep being produced or the WFO engine's regime-sizing logic
    #    silently breaks (defaults to 0 breadth => 0 Sniper slots, ever).
    #
    #    Unchanged definition from the old apply_blue_box_logic, just
    #    reusing Is_Liquid (already computed in section 0) instead of
    #    recomputing liquidity a second time.
    # ------------------------------------------------------------------
    df["EMA_50"] = df.groupby("SYMBOL")["CLOSE"].transform(
        lambda x: x.ewm(span=50, adjust=False).mean()
    )
    df["Above_50EMA_Liquid"] = (df["CLOSE"] > df["EMA_50"]) & df["Is_Liquid"]
    df["Liquid_Market_Size"] = df.groupby("DATE")["Is_Liquid"].transform("sum")
    df["Uptrend_Count"] = df.groupby("DATE")["Above_50EMA_Liquid"].transform("sum")
    df["Market_Breadth"] = np.where(
        df["Liquid_Market_Size"] > 0,
        df["Uptrend_Count"] / df["Liquid_Market_Size"],
        0,
    )

    return df
