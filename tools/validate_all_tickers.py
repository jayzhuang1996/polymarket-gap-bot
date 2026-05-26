"""
Validate gap mispricing across ALL tickers (SPX, NVDA, TSLA, AAPL, AMZN, GOOGL, META, MSFT, NFLX).

Extended analysis with combined statistics and confidence intervals.
"""
import pandas as pd
import ast
import yfinance as yf
import math
from pathlib import Path
from datetime import timezone

DATA_DIR = Path("data")
TICKERS = {
    "SPX": "^GSPC", "NVDA": "NVDA", "TSLA": "TSLA", "AAPL": "AAPL",
    "AMZN": "AMZN", "GOOGL": "GOOGL", "META": "META", "MSFT": "MSFT", "NFLX": "NFLX",
}

TIME_WINDOWS = {
    "9:30am": (385, 395),
    "10:00am": (355, 365),
    "11:00am": (295, 305),
    "12:00pm": (235, 245),
    "2:00pm": (115, 125),
}


def parse_outcome(s):
    try:
        p = ast.literal_eval(s)
        return 1 if float(p[0]) == 1.0 else 0
    except:
        return None


def get_vwap(df):
    if len(df) == 0:
        return None
    total = df["usd_amount"].sum()
    if total == 0:
        return None
    return (df["price"] * df["usd_amount"]).sum() / total


def wilson_ci(n_success, n_total, z=1.96):
    """Wilson score interval for binomial proportion."""
    if n_total == 0:
        return 0, 0
    p = n_success / n_total
    denom = 1 + z**2 / n_total
    centre = (p + z**2 / (2 * n_total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n_total)) / n_total) / denom
    return centre - margin, centre + margin


def analyze_ticker(display_name, yahoo_ticker, mdf, trades):
    print(f"\n{'='*100}")
    print(f"  {display_name} — GAP MISPRICING ANALYSIS")
    print(f"{'='*100}")

    stock = yf.download(yahoo_ticker, start="2025-10-01", end="2026-06-01", progress=False)
    if len(stock.columns) == 0:
        print(f"  WARNING: No data for {yahoo_ticker}")
        return None

    stock.columns = [c[0] for c in stock.columns]
    stock = stock.reset_index()
    stock["date"] = pd.to_datetime(stock["Date"]).dt.date
    stock["prev_close"] = stock["Close"].shift(1)
    stock["gap_pct"] = (stock["Open"] / stock["prev_close"] - 1) * 100
    stock["return_pct"] = (stock["Close"] / stock["prev_close"] - 1) * 100

    print(f"  Period: {stock['date'].min()} to {stock['date'].max()}")
    print(f"  Trading days: {len(stock)}")

    pattern = rf"\({display_name}\)\s+(?:Opens\s+)?Up or Down on"
    mask = mdf["question"].str.contains(pattern, na=False, regex=True)
    resolved = mdf[mask & (mdf["closed"] == 1)].copy()
    print(f"  Resolved markets: {len(resolved)}")

    if len(resolved) == 0:
        return None

    resolved["end_ts"] = resolved["end_date"].astype("int64") // 1_000_000_000

    rows = []
    for _, mkt in resolved.iterrows():
        end_dt = mkt["end_date"]
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        outcome = parse_outcome(mkt["outcome_prices"])
        if outcome is None:
            continue

        stk_row = stock[stock["date"] == end_dt.date()]
        if len(stk_row) == 0:
            continue
        stk_row = stk_row.iloc[0]

        cid = mkt["condition_id"]
        end_ts = mkt["end_ts"]

        for label, (win_min, win_max) in TIME_WINDOWS.items():
            lo = end_ts - win_max * 60
            hi = end_ts - win_min * 60
            window = trades[
                (trades["condition_id"] == cid)
                & (trades["timestamp"] >= lo)
                & (trades["timestamp"] <= hi)
            ]
            if len(window) == 0:
                continue
            vwap = get_vwap(window)
            if vwap is None:
                continue

            rows.append({
                "time": label,
                "ticker": display_name,
                "date": end_dt.date(),
                "outcome_yes": outcome,
                "yes_price": vwap,
                "gap_pct": stk_row["gap_pct"],
                "return_pct": stk_row["return_pct"],
            })

    df = pd.DataFrame(rows)
    print(f"  Observations: {len(df)}")
    if len(df) == 0:
        return None

    # ───────────────────────────────────────────
    # GAP THRESHOLD ANALYSIS
    # ───────────────────────────────────────────
    print(f"\n  {'─'*85}")
    print(f"  GAP THRESHOLDS × YES PRICE AT 9:30am")
    print(f"  {'─'*85}")

    if display_name == "SPX":
        thresholds = [-0.5, 0, 0.3, 0.5, 1.0]
    else:
        thresholds = [-2.0, -1.0, -0.5, 0, 0.5, 1.0, 2.0, 3.0]

    print(f"  {'Threshold':<20} {'Days':<6} {'WR%':<8} {'Avg YES¢':<10} {'Edge%':<8} {'95% CI':<18} {'Avg Gap':<8}")
    print(f"  {'─'*75}")

    for t in thresholds:
        subset = df[(df["gap_pct"] > t) & (df["time"] == "9:30am")]
        if len(subset) < 3:
            continue
        wr = subset["outcome_yes"].mean() * 100
        avg_price = subset["yes_price"].mean() * 100
        edge = wr - avg_price
        avg_gap = subset["gap_pct"].mean()
        n_yes = subset["outcome_yes"].sum()
        lo, hi = wilson_ci(n_yes, len(subset))
        print(f"  {'gap > ' + str(t) + '%':<20} {len(subset):<6} {wr:<8.1f} {avg_price:<10.1f} {edge:<+8.1f} "
              f"[{lo*100:<5.1f}%, {hi*100:>5.1f}%]  {avg_gap:<+8.2f}")

    for t in thresholds:
        subset = df[(df["gap_pct"] < -t) & (df["time"] == "9:30am")]
        if len(subset) < 3 or t == 0:
            continue
        wr = subset["outcome_yes"].mean() * 100
        avg_price = subset["yes_price"].mean() * 100
        edge = wr - avg_price
        avg_gap = subset["gap_pct"].mean()
        n_yes = subset["outcome_yes"].sum()
        lo, hi = wilson_ci(n_yes, len(subset))
        print(f"  {'gap < -' + str(t) + '%':<20} {len(subset):<6} {wr:<8.1f} {avg_price:<10.1f} {edge:<+8.1f} "
              f"[{lo*100:<5.1f}%, {hi*100:>5.1f}%]  {avg_gap:<+8.2f}")

    # ───────────────────────────────────────────
    # EDGE DECAY
    # ───────────────────────────────────────────
    print(f"\n  {'─'*85}")
    print(f"  EDGE DECAY")
    print(f"  {'─'*85}")

    gap_up = df[df["gap_pct"] > 0.5] if display_name == "SPX" else df[df["gap_pct"] > 1.0]
    gap_dn = df[df["gap_pct"] < -0.5] if display_name == "SPX" else df[df["gap_pct"] < -1.0]

    for regime_name, regime_df in [("GAP-UP", gap_up), ("GAP-DN", gap_dn)]:
        print(f"\n    {regime_name}:")
        print(f"    {'Time':<12} {'Obs':<6} {'WR%':<8} {'Avg YES¢':<10} {'Edge%':<8} {'95% CI':<18}")
        print(f"    {'─'*55}")
        for time_label in TIME_WINDOWS:
            subset = regime_df[regime_df["time"] == time_label]
            if len(subset) < 3:
                continue
            wr = subset["outcome_yes"].mean() * 100
            avg_price = subset["yes_price"].mean() * 100
            edge = wr - avg_price
            n_yes = subset["outcome_yes"].sum()
            lo, hi = wilson_ci(n_yes, len(subset))
            print(f"    {time_label:<12} {len(subset):<6} {wr:<8.1f} {avg_price:<10.1f} {edge:<+8.1f} "
                  f"[{lo*100:<5.1f}%, {hi*100:>5.1f}%]")

    return df


def main():
    mdf = pd.read_parquet(DATA_DIR / "markets.parquet", engine="fastparquet")

    all_results = {}
    for display, yahoo in TICKERS.items():
        print(f"\n  Loading {display} trades...")
        trades_fname = "spx_trades" if display == "SPX" else f"{display.lower()}_trades"
        trades_path = DATA_DIR / f"{trades_fname}.parquet"
        if not trades_path.exists():
            print(f"  SKIP: {trades_path} not found")
            continue
        trades = pd.read_parquet(trades_path, engine="fastparquet")
        print(f"  Trades loaded: {len(trades):,}")
        all_results[display] = analyze_ticker(display, yahoo, mdf, trades)

    # ───────────────────────────────────────────
    # COMBINED ALL-ASSET SUMMARY
    # ───────────────────────────────────────────
    print(f"\n{'='*100}")
    print(f"  COMBINED ALL-ASSET GAP MISPRICING")
    print(f"{'='*100}")

    # Combine all observation dataframes
    all_dfs = [df for df in all_results.values() if df is not None and len(df) > 0]
    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        print(f"\n  Total observations across all assets: {len(combined)}")

        print(f"\n  {'─'*85}")
        print(f"  COMBINED — GAP THRESHOLDS AT 9:30am")
        print(f"  {'─'*85}")
        print(f"  {'Threshold':<20} {'Days':<6} {'WR%':<8} {'Avg YES¢':<10} {'Edge%':<8} {'95% CI':<18}")
        print(f"  {'─'*65}")

        thresholds = [-2.0, -1.0, -0.5, 0, 0.5, 1.0, 2.0, 3.0]
        for t in thresholds:
            subset = combined[(combined["gap_pct"] > t) & (combined["time"] == "9:30am")]
            if len(subset) < 3:
                continue
            wr = subset["outcome_yes"].mean() * 100
            avg_price = subset["yes_price"].mean() * 100
            edge = wr - avg_price
            n_yes = subset["outcome_yes"].sum()
            lo, hi = wilson_ci(n_yes, len(subset))
            print(f"  {'gap > ' + str(t) + '%':<20} {len(subset):<6} {wr:<8.1f} {avg_price:<10.1f} {edge:<+8.1f} "
                  f"[{lo*100:<5.1f}%, {hi*100:>5.1f}%]")

        for t in thresholds:
            subset = combined[(combined["gap_pct"] < -t) & (combined["time"] == "9:30am")]
            if len(subset) < 3 or t == 0:
                continue
            wr = subset["outcome_yes"].mean() * 100
            avg_price = subset["yes_price"].mean() * 100
            edge = wr - avg_price
            n_yes = subset["outcome_yes"].sum()
            lo, hi = wilson_ci(n_yes, len(subset))
            print(f"  {'gap < -' + str(t) + '%':<20} {len(subset):<6} {wr:<8.1f} {avg_price:<10.1f} {edge:<+8.1f} "
                  f"[{lo*100:<5.1f}%, {hi*100:>5.1f}%]")

        # Edge decay on combined
        print(f"\n  {'─'*85}")
        print(f"  COMBINED — EDGE DECAY (gap > 1% UP / gap < -1% DOWN)")
        print(f"  {'─'*85}")

        for regime_name, gap_filter, label in [
            ("GAP-UP (>1%)", combined["gap_pct"] > 1.0, "↑ GAP-UP"),
            ("GAP-DN (<-1%)", combined["gap_pct"] < -1.0, "↓ GAP-DN"),
        ]:
            regime_df = combined[gap_filter]
            print(f"\n    {label}:")
            print(f"    {'Time':<12} {'Obs':<6} {'WR%':<8} {'Avg YES¢':<10} {'Edge%':<8} {'95% CI':<18}")
            print(f"    {'─'*55}")
            for time_label in TIME_WINDOWS:
                subset = regime_df[regime_df["time"] == time_label]
                if len(subset) < 3:
                    continue
                wr = subset["outcome_yes"].mean() * 100
                avg_price = subset["yes_price"].mean() * 100
                edge = wr - avg_price
                n_yes = subset["outcome_yes"].sum()
                lo, hi = wilson_ci(n_yes, len(subset))
                print(f"    {time_label:<12} {len(subset):<6} {wr:<8.1f} {avg_price:<10.1f} {edge:<+8.1f} "
                      f"[{lo*100:<5.1f}%, {hi*100:>5.1f}%]")

    # ───────────────────────────────────────────
    # CROSS-ASSET COMPARISON TABLE
    # ───────────────────────────────────────────
    print(f"\n{'='*100}")
    print(f"  CROSS-ASSET MISPRICING SUMMARY")
    print(f"{'='*100}")
    print(f"\n  {'Asset':<8} {'Regime':<14} {'Days':<6} {'WR%':<7} {'YES¢@9:30':<12} {'Edge@9:30':<10} {'YES¢@10':<10} {'Edge@10':<10} {'Avg Gap':<8}")
    print(f"  {'─'*80}")

    for display in TICKERS:
        df = all_results.get(display)
        if df is None or len(df) == 0:
            continue

        for regime_name, gap_filter in [
            ("Gap-Up > 0.5%", df["gap_pct"] > 0.5),
            ("Gap-Dn < -0.5%", df["gap_pct"] < -0.5),
            ("Gap-Up > 1%", df["gap_pct"] > 1.0),
            ("Gap-Dn < -1%", df["gap_pct"] < -1.0),
        ]:
            for time_label in ["9:30am", "10:00am"]:
                subset = df[gap_filter & (df["time"] == time_label)]
                if len(subset) < 3:
                    continue
                break

            subset_930 = df[gap_filter & (df["time"] == "9:30am")]
            subset_10 = df[gap_filter & (df["time"] == "10:00am")]

            n_days = len(subset_930) if len(subset_930) > 0 else len(subset_10)
            if n_days < 3:
                continue

            wr = (subset_930["outcome_yes"].mean() if len(subset_930) > 0
                  else subset_10["outcome_yes"].mean()) * 100

            p930 = subset_930["yes_price"].mean() * 100 if len(subset_930) > 0 else float("nan")
            p10 = subset_10["yes_price"].mean() * 100 if len(subset_10) > 0 else float("nan")
            e930 = wr - p930 if len(subset_930) > 0 else float("nan")
            e10 = wr - p10 if len(subset_10) > 0 else float("nan")
            avg_g = subset_930["gap_pct"].mean() if len(subset_930) > 0 else subset_10["gap_pct"].mean()

            p930_s = f"{p930:.1f}¢" if not pd.isna(p930) else "N/A"
            p10_s = f"{p10:.1f}¢" if not pd.isna(p10) else "N/A"
            e930_s = f"{e930:+.1f}%" if not pd.isna(e930) else "N/A"
            e10_s = f"{e10:+.1f}%" if not pd.isna(e10) else "N/A"

            print(f"  {display:<8} {regime_name:<14} {n_days:<6} {wr:<7.1f} "
                  f"{p930_s:<12} {e930_s:<10} {p10_s:<10} {e10_s:<10} {avg_g:<+8.2f}")

    return all_results


if __name__ == "__main__":
    main()
