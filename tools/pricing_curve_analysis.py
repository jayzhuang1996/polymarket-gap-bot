"""
Step 2b: Pricing Curve Analysis — Intraday Scalping Focus

Takes the pricing curve analysis further:

1. WIDE BUCKET: 75-100¢ combined → win rate by time window
2. SHORT-TERM: probability YES moves higher in next N minutes
3. TREND: directional bias by time of day (does YES trend up intraday?)

Usage: python tools/pricing_curve_analysis.py
"""

import pandas as pd
import ast
import numpy as np
from pathlib import Path

DATA_DIR = Path("data")

# Time windows — ordered by time-of-day (ET)
# (label, min_minutes_before_close, max_minutes_before_close)
# Close = 4pm ET = 20:00 UTC. Open = 9:30am ET = 13:30 UTC.
TIME_WINDOWS = [
    ("9:30am",   385, 395),   # market open
    ("10:00am",  355, 365),
    ("11:00am",  295, 305),
    ("12:00pm",  235, 245),
    ("1:00pm",   175, 185),
    ("2:00pm",   115, 125),
    ("2:30pm",   85,  95),
    ("3:00pm",   55,  65),
    ("3:15pm",   40,  50),
    ("3:30pm",   25,  35),
    ("3:45pm",   12,  18),
    ("3:55pm",   3,   7),
]

# For short-term analysis: look forward N minutes
FORWARD_WINDOWS = [15, 30, 60]

# Wide bucket merging everything 75¢+
WIDE_PRICE_BUCKETS = [0, 20, 40, 50, 60, 70, 75, 85, 100]
WIDE_PRICE_LABELS = [
    "0-20¢", "20-40¢", "40-50¢", "50-60¢",
    "60-70¢", "70-75¢", "75-85¢", "85-100¢",
]

# Fine price buckets for the full table
FULL_PRICE_BUCKETS = [0, 10, 20, 30, 40, 50, 60, 70, 75, 80, 85, 90, 95, 100]
FULL_PRICE_LABELS = [f"{lo}-{hi}¢" for lo, hi in
                     zip(FULL_PRICE_BUCKETS[:-1], FULL_PRICE_BUCKETS[1:])]


def load_spx_markets():
    mdf = pd.read_parquet(DATA_DIR / "markets.parquet")
    spx_mask = mdf["question"].str.contains(
        r"\(SPX\)\s+Up\s+or\s+Down\s+on", na=False)
    resolved = mdf[spx_mask & (mdf["closed"] == 1)].copy()
    return resolved


def parse_outcome(outcome_str):
    try:
        prices = ast.literal_eval(outcome_str)
        return 1 if float(prices[0]) == 1.0 else 0
    except (ValueError, SyntaxError, IndexError):
        return None


def get_vwap(trades_df):
    total = trades_df["usd_amount"].sum()
    if total == 0:
        return None
    return (trades_df["price"] * trades_df["usd_amount"]).sum() / total


def compute_window_vwap(trades, cid, lo_ts, hi_ts):
    """Compute VWAP for a specific (market, time window)."""
    window = trades[(trades["condition_id"] == cid) &
                    (trades["timestamp"] >= lo_ts) &
                    (trades["timestamp"] <= hi_ts)]
    if len(window) == 0:
        return None, 0, 0
    vwap = get_vwap(window)
    return vwap, len(window), window["usd_amount"].sum()


def short_term_forward_look(trades, cid, entry_ts, price, lookahead_min):
    """Look forward N minutes from entry_ts. Return max price seen."""
    future = trades[(trades["condition_id"] == cid) &
                    (trades["timestamp"] > entry_ts) &
                    (trades["timestamp"] <= entry_ts + lookahead_min * 60)]
    if len(future) == 0:
        return None, None, 0
    max_price = future["price"].max()
    min_price = future["price"].min()
    return max_price, min_price, len(future)


def analyze():
    markets = load_spx_markets()
    print(f"Resolved SPX markets: {len(markets)}")
    trades = pd.read_parquet(DATA_DIR / "spx_trades.parquet")
    print(f"Total SPX trades: {len(trades)}")

    # Build outcome map
    outcome_map = {}
    for _, row in markets.iterrows():
        oc = parse_outcome(row["outcome_prices"])
        if oc is not None:
            outcome_map[row["condition_id"]] = oc
    print(f"Markets with outcomes: {len(outcome_map)}")

    markets["end_ts"] = markets["end_date"].astype("int64") // 1000

    # ═══════════════════════════════════════════════════════════
    # PART 1: HOLD-TO-CLOSE ANALYSIS (original + 75-100¢ wide)
    # ═══════════════════════════════════════════════════════════

    records = []
    for _, mkt in markets.iterrows():
        cid = mkt["condition_id"]
        outcome = outcome_map.get(cid)
        if outcome is None:
            continue
        end_ts = mkt["end_ts"]

        for label, win_min, win_max in TIME_WINDOWS:
            lo, hi = end_ts - win_max * 60, end_ts - win_min * 60
            vwap, n_trades, vol = compute_window_vwap(
                trades, cid, lo, hi)
            if vwap is None:
                continue
            records.append({
                "condition_id": cid,
                "question": mkt["question"],
                "time_window": label,
                "price": round(vwap, 4),
                "outcome_yes": outcome,
                "num_trades": n_trades,
                "volume": round(vol, 2),
            })

    df = pd.DataFrame(records)
    print(f"\nHold-to-close observations: {len(df)}")
    print(f"Overall YES rate: {df['outcome_yes'].mean()*100:.1f}%")

    # WIDE BUCKET SUMMARY (75-100¢ merged)
    df["price_cents"] = (df["price"] * 100).round(0).astype(int)
    df["wide_bucket"] = pd.cut(
        df["price_cents"], bins=WIDE_PRICE_BUCKETS,
        labels=WIDE_PRICE_LABELS, right=False)

    wide_summary = (
        df.groupby(["time_window", "wide_bucket"], observed=True)
        .agg(
            markets=("outcome_yes", "count"),
            yes_wins=("outcome_yes", "sum"),
            win_rate=("outcome_yes", "mean"),
            avg_price=("price", "mean"),
        )
        .reset_index()
    )
    wide_summary["win_rate_pct"] = (wide_summary["win_rate"] * 100).round(1)
    wide_summary["be_pct"] = (wide_summary["avg_price"] * 100).round(1)
    wide_summary["edge_pct"] = (
        wide_summary["win_rate_pct"] - wide_summary["be_pct"]).round(1)

    # Print wide bucket table
    print("\n" + "=" * 110)
    print("WIDE BUCKET TABLE — 75-85¢ and 85-100¢ merged")
    print("=" * 110)
    high_only = wide_summary[
        wide_summary["wide_bucket"].isin(["75-85¢", "85-100¢"])]
    if len(high_only) > 0:
        print(f"{'Time':<10} {'Price':<10} {'Mkts':<6} {'Win%':<7}"
              f"{'BE%':<6} {'Edge':<7}")
        print("-" * 50)
        for _, r in high_only.iterrows():
            edge_s = f"+{r['edge_pct']}" if r['edge_pct'] > 0 else str(r['edge_pct'])
            print(
                f"{r['time_window']:<10} {r['wide_bucket']:<10} "
                f"{r['markets']:<6} {r['win_rate_pct']:<7}"
                f"{r['be_pct']:<6} {edge_s:<7}")
    else:
        print("No 75¢+ data found.")

    # ═══════════════════════════════════════════════════════════
    # PART 2: SHORT-TERM PRICE MOVEMENT ANALYSIS (intraday)
    # ═══════════════════════════════════════════════════════════
    # For each market's trades in a given window, look at what
    # happens in the next N minutes.
    # ═══════════════════════════════════════════════════════════

    print("\n" + "=" * 110)
    print("SHORT-TERM ANALYSIS — probability YES moves higher in N minutes")
    print("(Answering: if I enter at price P at time T, what % chance does")
    print(" price increase in the next 15/30/60 minutes?)")
    print("=" * 110)

    # Strategy: for each market, sort trades, then for each trade,
    # look forward. Sample to keep it fast (bucket by time window).
    forward_records = []

    # Time windows to analyze (focus on stable periods, skip open/last 30)
    SCALP_WINDOWS = [
        ("10:00am",  355, 365),
        ("11:00am",  295, 305),
        ("12:00pm",  235, 245),
        ("1:00pm",   175, 185),
        ("2:00pm",   115, 125),
        ("2:30pm",   85,  95),
        ("3:00pm",   55,  65),
        ("3:15pm",   40,  50),
    ]

    for _, mkt in markets.iterrows():
        cid = mkt["condition_id"]
        end_ts = mkt["end_ts"]
        mkt_trades = trades[trades["condition_id"] == cid]
        if len(mkt_trades) == 0:
            continue
        mkt_trades = mkt_trades.sort_values("timestamp")

        for label, win_min, win_max in SCALP_WINDOWS:
            lo = end_ts - win_max * 60
            hi = end_ts - win_min * 60
            # Trades in this window
            entry_trades = mkt_trades[
                (mkt_trades["timestamp"] >= lo) &
                (mkt_trades["timestamp"] <= hi)]
            if len(entry_trades) == 0:
                continue

            entry_vwap = get_vwap(entry_trades)
            if entry_vwap is None:
                continue

            for fwd_min in FORWARD_WINDOWS:
                fwd_hi = hi + fwd_min * 60
                future_trades = mkt_trades[
                    (mkt_trades["timestamp"] > hi) &
                    (mkt_trades["timestamp"] <= fwd_hi)]
                if len(future_trades) == 0:
                    continue

                fwd_vwap = get_vwap(future_trades)
                max_price = future_trades["price"].max()
                min_price = future_trades["price"].min()

                if fwd_vwap is not None:
                    forward_records.append({
                        "condition_id": cid,
                        "entry_window": label,
                        "entry_price": round(entry_vwap, 4),
                        "lookahead_min": fwd_min,
                        "fwd_vwap": round(fwd_vwap, 4),
                        "max_price": round(max_price, 4),
                        "min_price": round(min_price, 4),
                        "pct_change": round(
                            (fwd_vwap - entry_vwap) / entry_vwap * 100, 2),
                        "max_pct_up": round(
                            (max_price - entry_vwap) / entry_vwap * 100, 2),
                        "entry_trades": len(entry_trades),
                        "fwd_trades": len(future_trades),
                    })

    fdf = pd.DataFrame(forward_records)
    if len(fdf) > 0:
        print(f"\nForward-look observations: {len(fdf)}")

        # Bucket entry price
        fdf["entry_cents"] = (fdf["entry_price"] * 100).round(0).astype(int)
        fdf["price_bucket"] = pd.cut(
            fdf["entry_cents"], bins=FULL_PRICE_BUCKETS,
            labels=FULL_PRICE_LABELS, right=False)

        # For each (entry_window, price_bucket, lookahead_min):
        # compute: % of times price went up, avg gain, max gain
        fwd_summary = (
            fdf.groupby(
                ["entry_window", "price_bucket", "lookahead_min"],
                observed=True)
            .agg(
                observations=("pct_change", "count"),
                pct_up=("pct_change", lambda x: (x > 0).mean()),
                avg_change=("pct_change", "mean"),
                avg_max_up=("max_pct_up", "mean"),
                avg_entry_price=("entry_price", "mean"),
            )
            .reset_index()
        )
        fwd_summary["pct_up_pct"] = (
            fwd_summary["pct_up"] * 100).round(1)
        fwd_summary["avg_change_pct"] = (
            fwd_summary["avg_change"]).round(2)
        fwd_summary["avg_max_up_pct"] = (
            fwd_summary["avg_max_up"]).round(2)

        # Focus on 75¢+ entries
        high_entries = fwd_summary[
            fwd_summary["price_bucket"].isin(
                ["75-80¢", "80-85¢", "85-90¢", "90-95¢", "95-100¢"])]

        for lookahead in FORWARD_WINDOWS:
            print(f"\n── Forward look: {lookahead} min ──")
            subset = high_entries[
                high_entries["lookahead_min"] == lookahead]
            if len(subset) == 0:
                print("  No 75¢+ data in this window.")
                continue

            subset = subset.sort_values("entry_window")
            print(f"{'Time':<10} {'Price':<9} {'Obs':<5} "
                  f"{'% Up':<7} {'Avg Chg':<9} {'Avg Max ↑':<10}")
            print("-" * 50)
            for _, r in subset.iterrows():
                print(
                    f"{r['entry_window']:<10} {r['price_bucket']:<9} "
                    f"{r['observations']:<5} {r['pct_up_pct']:<7}"
                    f"{r['avg_change_pct']:<9} {r['avg_max_up_pct']:<10}%")

        # Also show the overall best windows for any price
        print("\n── BEST SHORT-TERM SETUPS (all prices, 15min lookahead) ──")
        best = fwd_summary[
            (fwd_summary["lookahead_min"] == 15) &
            (fwd_summary["observations"] >= 5)]
        best = best.sort_values("pct_up_pct", ascending=False).head(15)
        print(f"{'Time':<10} {'Price':<9} {'Obs':<5} "
              f"{'% Up':<7} {'Avg Chg':<9} {'Avg Max ↑':<10}")
        print("-" * 50)
        for _, r in best.iterrows():
            print(
                f"{r['entry_window']:<10} {r['price_bucket']:<9} "
                f"{r['observations']:<5} {r['pct_up_pct']:<7}"
                f"{r['avg_change_pct']:<9} {r['avg_max_up_pct']:<10}%")

    # ═══════════════════════════════════════════════════════════
    # PART 3: INTRADAY DIRECTIONAL TREND
    # ═══════════════════════════════════════════════════════════
    # Compute VWAP at each time window for ALL markets.
    # Average across markets to see the typical intraday YES trajectory.
    # This reveals: does YES trend up during the day, and when?
    # ═══════════════════════════════════════════════════════════

    print("\n" + "=" * 110)
    print("INTRADAY TREND — average YES price trajectory across all markets")
    print("(Shows the typical daily pattern: does YES drift up or down?)")
    print("=" * 110)

    # Use the first dataset (df) already computed above
    trend = (
        df.groupby("time_window")
        .agg(
            avg_price=("price", "mean"),
            median_price=("price", "median"),
            markets=("price", "count"),
            yes_rate=("outcome_yes", "mean"),
            volume=("volume", "sum"),
        )
        .reset_index()
    )
    trend["avg_price_cents"] = (trend["avg_price"] * 100).round(1)
    trend["median_price_cents"] = (trend["median_price"] * 100).round(1)
    trend["yes_rate_pct"] = (trend["yes_rate"] * 100).round(1)

    # Sort by time
    to_map = {lbl: i for i, (lbl, _, _) in enumerate(TIME_WINDOWS)}
    trend["_order"] = trend["time_window"].map(to_map)
    trend = trend.sort_values("_order")

    print(f"{'Time':<10} {'Avg YES':<8} {'Median':<8} {'Mkts':<6} "
          f"{'YES Win%':<9} {'Volume':<12} {'Trend':<10}")
    print("-" * 65)
    prev_price = None
    for _, r in trend.iterrows():
        trend_arrow = ""
        if prev_price is not None:
            if r["avg_price_cents"] > prev_price + 1:
                trend_arrow = "  ↗"
            elif r["avg_price_cents"] < prev_price - 1:
                trend_arrow = "  ↘"
            else:
                trend_arrow = "  →"
        prev_price = r["avg_price_cents"]
        print(
            f"{r['time_window']:<10} {r['avg_price_cents']:<8} "
            f"{r['median_price_cents']:<8} {r['markets']:<6} "
            f"{r['yes_rate_pct']:<9} ${r['volume']:>8,.0f}"
            f"{trend_arrow:<10}")

    return df, wide_summary, fdf, fwd_summary, trend


if __name__ == "__main__":
    analyze()
