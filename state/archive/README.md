# Archived paper-trading state

Files here are PRE-FIX state snapshots, kept as evidence of what the pipeline did, NOT as performance data.

Reset after the 2026-08-22 audit. The prior state was produced under findings #26 (Sniper look-ahead in entry price, stop distance and position size), #27 (exits ordered before the allocation rebalance), #33 (no duplicate-session guard) and a 6%/365 idle-yield basis. Its equity curve is not comparable with anything recorded after this point.

Do not splice their `equity_curve_log` onto the current one: entry timing, rebalance order and the idle-yield basis all differ across the reset boundary.
