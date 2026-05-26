"""
Backtest sell fractions — grid search over GFR exit fractions.

Simulates the full exit ladder on all qualifying sessions in
data/full_session_2min.csv and finds the fraction combinations
that maximize risk-adjusted P&L.

Parameters optimized:
    F_gfr_shallow  fraction to sell when gfr first drops below -0.5
    F_gfr_deep     fraction to sell when gfr first drops below -0.8

Optimized separately for YES (gap-up) and NO (gap-down) trades,
because the data shows very different win rates after a GFR trigger:
    gfr < -0.5: YES WR=18% vs NO WR=43% — optimal fractions differ

Fixed parameters (kept at server.py current values):
    Time exits at 2pm / 2:30pm / 3pm with price+gfr conditions
    TRADING_FEE_PCT = 0.01

Usage:
    python tools/backtest_sell_fractions.py
    python tools/backtest_sell_fractions.py --plot
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

DATA_CSV = Path("data/full_session_2min.csv")
FEE = 0.01   # 1% Polymarket fee

# Entry window: 9:35am–12pm ET (tbf_min 240–385)
ENTRY_TBF_MAX = 385
ENTRY_TBF_MIN = 240

# Time exit thresholds (tbf_min)
TBF_2PM   = 120   # 2:00pm ET
TBF_230PM =  90   # 2:30pm ET
TBF_3PM   =  60   # 3:00pm ET

# GFR thresholds (must match config.py TICKER_GFR_EXIT_SHALLOW/DEEP)
GFR_SHALLOW = -0.5
GFR_DEEP    = -0.8

# Price threshold for time exits (hold if token ≥ this)
TIME_EXIT_HOLD_PRICE = 0.85

# Per-ticker gap thresholds from config
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import TICKER_GAP_THRESHOLD
except ImportError:
    TICKER_GAP_THRESHOLD = {t: 0.005 for t in
        ["SPX","NVDA","TSLA","AAPL","AMZN","GOOGL","META","MSFT","NFLX"]}


# ── Simulation ────────────────────────────────────────────────────────────────

def simulate_session(
    rows: pd.DataFrame,
    f_shallow: float,
    f_deep: float,
) -> float | None:
    """
    Simulate one session (ticker × date) with given GFR exit fractions.

    rows: session rows sorted chronologically (tbf_min descending).
    Returns P&L as fraction of entry cost, or None if session not tradeable.
    """
    gap_pct   = rows["gap_pct"].iloc[0]
    ticker    = rows["ticker"].iloc[0]
    threshold = TICKER_GAP_THRESHOLD.get(ticker, 0.005)

    if abs(gap_pct) < threshold:
        return None

    gap_up = gap_pct > 0
    outcome_yes = int(rows["outcome_yes"].iloc[0])
    win = (gap_up and outcome_yes == 1) or (not gap_up and outcome_yes == 0)

    # Find entry row — first row in entry window
    entry_rows = rows[(rows["tbf_min"] >= ENTRY_TBF_MIN) &
                      (rows["tbf_min"] <= ENTRY_TBF_MAX)]
    if len(entry_rows) == 0:
        return None

    entry_row   = entry_rows.iloc[0]
    yes_vwap_0  = float(entry_row["yes_vwap"])
    entry_price = yes_vwap_0 if gap_up else (1.0 - yes_vwap_0)

    if entry_price <= 0.01 or entry_price >= 0.99:
        return None

    # Walk forward from entry row onward
    post_entry = rows[rows["tbf_min"] <= entry_row["tbf_min"]].copy()
    post_entry["gfr"] = post_entry["gfr"].fillna(0.0)

    held = 1.0          # fraction of original position still held
    revenue = 0.0       # accumulated sale proceeds per $1 invested
    payout = 1.0 - FEE

    fired_shallow = False
    fired_deep    = False
    fired_2pm     = False
    fired_230pm   = False

    for _, row in post_entry.iterrows():
        tbf  = row["tbf_min"]
        gfr  = row["gfr"]
        yv   = float(row["yes_vwap"])
        tok  = yv if gap_up else (1.0 - yv)

        # ── GFR deep exit ──────────────────────────────────────────────
        if not fired_deep and gfr < GFR_DEEP:
            sell = held * f_deep
            revenue += sell * tok * payout / entry_price
            held    -= sell
            fired_deep = True

        # ── GFR shallow exit ───────────────────────────────────────────
        if not fired_shallow and gfr < GFR_SHALLOW:
            sell = held * f_shallow
            revenue += sell * tok * payout / entry_price
            held    -= sell
            fired_shallow = True

        # ── 2pm time exit ──────────────────────────────────────────────
        if not fired_2pm and tbf <= TBF_2PM:
            hold = tok >= TIME_EXIT_HOLD_PRICE and gfr >= 0.5
            if not hold:
                revenue += held * tok * payout / entry_price
                held = 0.0
            fired_2pm = True

        # ── 2:30pm time exit ───────────────────────────────────────────
        if not fired_230pm and tbf <= TBF_230PM:
            hold = tok >= TIME_EXIT_HOLD_PRICE and gfr >= 0.2
            if not hold:
                revenue += held * tok * payout / entry_price
                held = 0.0
            fired_230pm = True

        # ── 3pm hard exit ──────────────────────────────────────────────
        if tbf <= TBF_3PM:
            revenue += held * tok * payout / entry_price
            held = 0.0
            break

        if held <= 0.001:
            break

    # Settlement for any remaining holding
    if held > 0.001:
        settlement = payout if win else 0.0
        revenue += held * settlement / entry_price

    return revenue - 1.0  # P&L as fraction of cost


def run_grid(
    df: pd.DataFrame,
    f_shallow_grid: list[float],
    f_deep_grid: list[float],
    direction: str = "both",
) -> pd.DataFrame:
    """
    Run full grid search.

    direction: "yes" | "no" | "both"
    Returns DataFrame with columns: f_shallow, f_deep, mean_pnl, sharpe, n_trades.
    """
    if direction == "yes":
        df = df[df["gap_pct"] > 0]
    elif direction == "no":
        df = df[df["gap_pct"] < 0]

    sessions = df.sort_values("tbf_min", ascending=False).groupby(
        ["ticker", "date"], sort=False
    )

    results = []
    for f_s, f_d in product(f_shallow_grid, f_deep_grid):
        pnls = []
        for _, grp in sessions:
            pnl = simulate_session(grp, f_shallow=f_s, f_deep=f_d)
            if pnl is not None:
                pnls.append(pnl)
        arr = np.array(pnls)
        mean = arr.mean()
        std  = arr.std()
        sharpe = mean / std if std > 0 else 0.0
        results.append({
            "f_shallow": f_s,
            "f_deep":    f_d,
            "mean_pnl":  round(mean, 5),
            "sharpe":    round(sharpe, 4),
            "win_rate":  round((arr > 0).mean(), 3),
            "n":         len(arr),
        })

    return pd.DataFrame(results)


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_heatmap(results: pd.DataFrame, metric: str, title: str) -> None:
    pivot = results.pivot(index="f_shallow", columns="f_deep", values=metric)
    pivot.index   = [f"shallow={v:.0%}" for v in pivot.index]
    pivot.columns = [f"deep={v:.0%}"    for v in pivot.columns]

    print(f"\n{title} — {metric}")
    print(pivot.to_string(float_format=lambda x: f"{x:+.4f}"))


def print_best(results: pd.DataFrame, label: str) -> tuple[float, float]:
    best = results.loc[results["mean_pnl"].idxmax()]
    print(f"\n  Best {label}:")
    print(f"    f_shallow = {best['f_shallow']:.0%}   f_deep = {best['f_deep']:.0%}")
    print(f"    mean P&L  = {best['mean_pnl']:+.4f} ({best['mean_pnl']*100:+.2f}¢ per $1)")
    print(f"    Sharpe    = {best['sharpe']:+.4f}")
    print(f"    Win rate  = {best['win_rate']:.1%}   n = {best['n']}")
    return float(best["f_shallow"]), float(best["f_deep"])


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()

    print(f"Loading {DATA_CSV} …")
    df = pd.read_csv(DATA_CSV)
    print(f"  {len(df):,} rows, {df.groupby(['ticker','date']).ngroups} sessions")

    # ── Baseline: current server.py fractions ─────────────────────────
    print("\n── Baseline (current server.py) ─────────────────────────────────")
    for direction, label in [("yes", "YES/gap-up"), ("no", "NO/gap-down"), ("both", "ALL")]:
        sub = df.copy()
        if direction == "yes":
            sub = sub[sub["gap_pct"] > 0]
        elif direction == "no":
            sub = sub[sub["gap_pct"] < 0]
        sessions = sub.sort_values("tbf_min", ascending=False).groupby(
            ["ticker", "date"], sort=False
        )
        pnls = [simulate_session(grp, f_shallow=0.60, f_deep=0.90)
                for _, grp in sessions]
        pnls = [p for p in pnls if p is not None]
        arr  = np.array(pnls)
        print(f"  {label:14s}: mean P&L={arr.mean():+.4f}  "
              f"Sharpe={arr.mean()/arr.std():+.4f}  win_rate={( arr>0).mean():.1%}  n={len(arr)}")

    # ── Grid search ───────────────────────────────────────────────────
    F_SHALLOW_GRID = [0.0, 0.20, 0.40, 0.60, 0.80, 1.00]
    F_DEEP_GRID    = [0.0, 0.40, 0.60, 0.80, 1.00]

    print("\n── Grid Search ──────────────────────────────────────────────────")

    best_fracs: dict[str, tuple[float, float]] = {}
    for direction, label in [("yes", "YES/gap-up"), ("no", "NO/gap-down"), ("both", "ALL")]:
        print(f"\n  [{label}]")
        res = run_grid(df, F_SHALLOW_GRID, F_DEEP_GRID, direction=direction)
        print_heatmap(res, "mean_pnl", label)
        fs, fd = print_best(res, label)
        best_fracs[direction] = (fs, fd)

    # ── Comparison summary ────────────────────────────────────────────
    print("\n── Recommendation ───────────────────────────────────────────────")
    print("  Direction    Current fractions        Optimal fractions")
    print("  " + "-"*60)
    current = {"yes": (0.60, 0.90), "no": (0.60, 0.90), "both": (0.60, 0.90)}
    labels  = {"yes": "YES/gap-up", "no": "NO/gap-down", "both": "COMBINED"}
    for k in ["yes", "no", "both"]:
        c_s, c_d = current[k]
        o_s, o_d = best_fracs[k]
        print(f"  {labels[k]:14s}: shallow={c_s:.0%}/deep={c_d:.0%}  →  "
              f"shallow={o_s:.0%}/deep={o_d:.0%}"
              f"{'  ← NO CHANGE' if (c_s,c_d)==(o_s,o_d) else '  ← UPDATE'}")

    print()
    print("  Note: fractions are multiplicative in server.py.")
    print("  If BOTH triggers fire in one session:")
    o_s, o_d = best_fracs["both"]
    remaining = (1 - o_d) * (1 - o_s)
    print(f"    deep fires first → sell {o_d:.0%}, hold {1-o_d:.0%}")
    print(f"    shallow fires next → sell {o_s:.0%} of remaining")
    print(f"    total held at settlement: {remaining:.0%}")

    # ── Optional plot ─────────────────────────────────────────────────
    if args.plot:
        try:
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(1, 3, figsize=(15, 4))
            for ax, (direction, label) in zip(
                axes, [("yes","YES/gap-up"), ("no","NO/gap-down"), ("both","ALL")]
            ):
                res = run_grid(df, F_SHALLOW_GRID, F_DEEP_GRID, direction=direction)
                pivot = res.pivot(index="f_shallow", columns="f_deep", values="mean_pnl")
                im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn")
                ax.set_xticks(range(len(pivot.columns)))
                ax.set_xticklabels([f"{v:.0%}" for v in pivot.columns])
                ax.set_yticks(range(len(pivot.index)))
                ax.set_yticklabels([f"{v:.0%}" for v in pivot.index])
                ax.set_xlabel("f_deep")
                ax.set_ylabel("f_shallow")
                ax.set_title(f"Mean P&L — {label}")
                plt.colorbar(im, ax=ax)
                # mark best
                best_idx = pivot.values.argmax()
                r, c = divmod(best_idx, len(pivot.columns))
                ax.add_patch(plt.Rectangle((c-0.5, r-0.5), 1, 1, fill=False,
                                           edgecolor="blue", lw=3))
            plt.tight_layout()
            plt.show()
        except ImportError:
            print("matplotlib not available — skipping plot")


if __name__ == "__main__":
    main()
