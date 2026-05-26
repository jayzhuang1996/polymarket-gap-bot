"""
Step 2d: VIX + Opening Gap + First 30min → Correlation Analysis

Checks:
  1. Does VIX level affect win rate / edge size?
  2. Does SPX opening gap predict close direction?
  3. Does first 30min SPX return predict close direction?
  4. Combined model: what's the best single predictor?

Usage: python tools/correlation_analysis.py
"""

import pandas as pd
import ast
import yfinance as yf
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta

DATA_DIR = Path("data")


def get_data():
    """Load all data: SPX markets, trades, SPX daily, VIX daily."""
    mdf = pd.read_parquet(DATA_DIR / "markets.parquet")
    spx_mask = mdf["question"].str.contains(
        r"\(SPX\)\s+Up\s+or\s+Down\s+on", na=False)
    resolved = mdf[spx_mask & (mdf["closed"] == 1)].copy()

    # SPX daily data
    spx = yf.download("^GSPC", start="2025-10-01", end="2026-06-01",
                      progress=False)
    spx.columns = [c[0] for c in spx.columns]
    spx = spx.reset_index()
    spx["date"] = pd.to_datetime(spx["Date"]).dt.date
    spx["prev_close"] = spx["Close"].shift(1)
    spx["return_pct"] = (spx["Close"] / spx["prev_close"] - 1) * 100
    spx["gap_pct"] = (spx["Open"] / spx["prev_close"] - 1) * 100
    spx["first_30min_return"] = (
        spx["Open"].shift(-1) / spx["Open"] - 1
    ) * 100  # approximate: next day open vs today open

    # VIX data
    vix = yf.download("^VIX", start="2025-10-01", end="2026-06-01",
                      progress=False)
    vix.columns = [c[0] for c in vix.columns]

    # Merge SPX and VIX
    combined = spx.copy()
    combined["vix_close"] = vix["Close"].values
    combined["vix_change"] = combined["vix_close"].diff()

    return resolved, combined


def parse_outcome(s):
    try:
        p = ast.literal_eval(s)
        return 1 if float(p[0]) == 1.0 else 0
    except:
        return None


def analyze():
    resolved, spx_data = get_data()
    print(f"SPX data days: {len(spx_data)}")
    print(f"Resolved markets: {len(resolved)}")

    # Map each market to its SPX day
    results = []
    for _, mkt in resolved.iterrows():
        end_dt = mkt["end_date"]
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        outcome = parse_outcome(mkt["outcome_prices"])
        if outcome is None:
            continue

        row = spx_data[spx_data["date"] == end_dt.date()]
        if len(row) == 0:
            continue
        row = row.iloc[0]

        results.append({
            "date": end_dt.date(),
            "outcome_yes": outcome,
            "spx_return": row["return_pct"],
            "spx_gap": row["gap_pct"],
            "vix": row["vix_close"],
        })

    df = pd.DataFrame(results)
    print(f"Matched markets: {len(df)}")
    print(f"UP days: {df['outcome_yes'].sum()}/{len(df)} "
          f"({df['outcome_yes'].mean()*100:.1f}%)")

    # ═══════════════════════════════════════════════════
    # 1. VIX LEVEL vs WIN RATE
    # ═══════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("VIX LEVEL vs SPX DIRECTION")
    print("=" * 70)

    vix_bins = [0, 12, 15, 18, 22, 30, 100]
    vix_labels = ["<12", "12-15", "15-18", "18-22", "22-30", ">30"]
    df["vix_bucket"] = pd.cut(df["vix"], bins=vix_bins, labels=vix_labels)

    vix_summary = (
        df.groupby("vix_bucket", observed=True)
        .agg(
            days=("outcome_yes", "count"),
            up_days=("outcome_yes", "sum"),
            up_pct=("outcome_yes", "mean"),
        )
        .reset_index()
    )
    vix_summary["up_pct"] = (vix_summary["up_pct"] * 100).round(1)
    print(f"{'VIX Range':<12} {'Days':<6} {'Up Days':<8} {'% Up':<7}")
    print("-" * 35)
    for _, r in vix_summary.iterrows():
        print(f"{r['vix_bucket']:<12} {r['days']:<6} "
              f"{r['up_days']:<8} {r['up_pct']:<7}")

    # ═══════════════════════════════════════════════════
    # 2. OPENING GAP vs CLOSE DIRECTION
    # ═══════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("OPENING GAP % vs CLOSE DIRECTION")
    print("=" * 70)

    gap_bins = [-float("inf"), -1, -0.5, -0.25, 0, 0.25, 0.5, 1, float("inf")]
    gap_labels = ["<-1%", "-1 to -0.5%", "-0.5 to -0.25%",
                  "-0.25-0%", "0-0.25%", "0.25-0.5%", "0.5-1%", ">1%"]
    df["gap_bucket"] = pd.cut(
        df["spx_gap"], bins=gap_bins, labels=gap_labels)

    gap_summary = (
        df.groupby("gap_bucket", observed=True)
        .agg(
            days=("outcome_yes", "count"),
            up_days=("outcome_yes", "sum"),
            up_pct=("outcome_yes", "mean"),
        )
        .reset_index()
    )
    gap_summary["up_pct"] = (gap_summary["up_pct"] * 100).round(1)
    print(f"{'Gap Range':<18} {'Days':<6} {'Up Days':<8} {'% Up':<7}")
    print("-" * 40)
    for _, r in gap_summary.iterrows():
        print(f"{r['gap_bucket']:<18} {r['days']:<6} "
              f"{r['up_days']:<8} {r['up_pct']:<7}")

    # ═══════════════════════════════════════════════════
    # 3. VIX + GAP combined signal
    # ═══════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("COMBINED: VIX + GAP DIRECTION → % UP")
    print("=" * 70)

    df["gap_dir"] = (df["spx_gap"] > 0).astype(int)
    df["vix_regime"] = pd.cut(
        df["vix"], bins=[0, 15, 22, 100],
        labels=["Low VIX (<15)", "Med VIX (15-22)", "High VIX (>22)"])

    combined = (
        df.groupby(["vix_regime", "gap_dir"], observed=True)
        .agg(
            days=("outcome_yes", "count"),
            up_days=("outcome_yes", "sum"),
            up_pct=("outcome_yes", "mean"),
        )
        .reset_index()
    )
    combined["up_pct"] = (combined["up_pct"] * 100).round(1)
    print(f"{'VIX Regime':<16} {'Gap Dir':<8} {'Days':<6} "
          f"{'Up Days':<8} {'% Up':<7}")
    print("-" * 50)
    for _, r in combined.iterrows():
        print(f"{r['vix_regime']:<16} "
              f"{'GAP UP' if r['gap_dir'] else 'GAP DOWN':<8} "
              f"{r['days']:<6} {r['up_days']:<8} {r['up_pct']:<7}")

    # ═══════════════════════════════════════════════════
    # 4. VIX CORRELATION
    # ═══════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("VIX CORRELATION METRICS")
    print("=" * 70)
    corr_vix_return = df["vix"].corr(df["spx_return"])
    corr_vix_outcome = df["vix"].corr(df["outcome_yes"])
    corr_gap_outcome = df["spx_gap"].corr(df["outcome_yes"])
    print(f"VIX vs SPX return:         {corr_vix_return:.3f}")
    print(f"VIX vs YES outcome:        {corr_vix_outcome:.3f}")
    print(f"Opening Gap vs outcome:    {corr_gap_outcome:.3f}")

    # ═══════════════════════════════════════════════════
    # 5. SIMPLE PREDICTIVE TABLE
    # ═══════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("PREDICTIVE POWER: if gap > X%, probability close UP")
    print("=" * 70)

    for threshold in [-1.0, -0.5, -0.25, 0, 0.25, 0.5, 1.0]:
        subset = df[df["spx_gap"] > threshold]
        if len(subset) >= 3:
            pct = subset["outcome_yes"].mean() * 100
            print(f"  gap > {threshold:+.2f}% : {pct:.1f}% UP "
                  f"({len(subset)} days)")

    print()
    for threshold in [-1.0, -0.5, -0.25, 0, 0.25, 0.5, 1.0]:
        subset = df[df["spx_gap"] < threshold]
        if len(subset) >= 3:
            pct = subset["outcome_yes"].mean() * 100
            print(f"  gap < {threshold:+.2f}% : {pct:.1f}% UP "
                  f"({len(subset)} days)")

    return df


if __name__ == "__main__":
    analyze()
