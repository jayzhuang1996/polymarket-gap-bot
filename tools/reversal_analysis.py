"""
Intraday Reversal Analysis — gap-UP days where GFR crossed below -1.0

Question: When a gap-UP day fully reverses (stock crosses prev_close), does the
NO contract have a tradeable edge at that moment? Could the bot flip direction
mid-session instead of sticking with the original YES trade?

Data source: data/full_session_2min.csv
  Columns: ticker, date, dow, tbf_min, yes_vwap, gfr, gap_pct, outcome_yes, n_trades

  tbf_min = minutes before 4pm close (390 = 9:30am, 2 = 3:58pm)
  gfr     = gap fill ratio (negative = stock reversed against gap)
             GFR < -1.0 means stock crossed prev_close
  yes_vwap = yes token VWAP at that 2-min bar
  outcome_yes = 1 if YES resolved $1, 0 if NO resolved $1

Methodology:
  1. Filter gap-UP sessions (gap_pct > 0.5%).
  2. For each (ticker, date) session, find the first 2-min bar where GFR < -1.0.
  3. Record: time of crossing, yes_vwap at that bar, outcome (NO won = outcome_yes==0).
  4. NO contract ask ≈ 1 − yes_bid ≈ 1 − yes_vwap (crude but consistent with live logic).
  5. Calculate: NO win rate, average NO ask at crossing, average edge for NO.
  6. Break down by ticker, time-of-day bucket, and gap magnitude.

Usage: python tools/reversal_analysis.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

DATA_DIR = Path("data")
FEE_PCT  = 0.02   # 2% Polymarket settlement fee (matches TRADING_FEE_PCT in config.py)
GAP_MIN  = 0.005  # minimum gap_pct to count as "gap-UP day" (50 bps)


def _time_bucket(tbf_min: int) -> str:
    """Convert tbf_min (minutes before 4pm) to ET time bucket label."""
    # tbf_min = 390 → 9:30am ET
    et_min_from_midnight = 9 * 60 + 30 + (390 - tbf_min)
    h = et_min_from_midnight // 60
    m = et_min_from_midnight % 60
    if (h, m) < (10, 30):
        return "09:30–10:30"
    elif (h, m) < (12, 0):
        return "10:30–12:00"
    elif (h, m) < (13, 30):
        return "12:00–13:30"
    elif (h, m) < (14, 0):
        return "13:30–14:00"
    else:
        return "14:00–close"


def _gap_bucket(gap_pct: float) -> str:
    pct = gap_pct * 100
    if pct < 0.5:
        return "<0.5%"
    elif pct < 1.0:
        return "0.5–1.0%"
    elif pct < 2.0:
        return "1.0–2.0%"
    else:
        return "≥2.0%"


def main():
    df = pd.read_csv(DATA_DIR / "full_session_2min.csv")

    # Only gap-UP sessions with valid GFR
    gap_up = df[(df["gap_pct"] > GAP_MIN) & df["gfr"].notna()].copy()

    total_gap_up_sessions = gap_up.groupby(["ticker", "date"]).ngroups
    print(f"\n{'='*65}")
    print("INTRADAY REVERSAL ANALYSIS — Gap-UP days, GFR < -1.0 crossing")
    print(f"{'='*65}")
    print(f"Total gap-UP sessions (gap_pct > {GAP_MIN*100:.1f}%): {total_gap_up_sessions}")
    print(f"Date range: {gap_up['date'].min()} → {gap_up['date'].max()}")
    print(f"Tickers: {sorted(gap_up['ticker'].unique().tolist())}")

    # Find first crossing of GFR < -1.0 for each session
    reversals = []
    for (ticker, date), grp in gap_up.groupby(["ticker", "date"]):
        grp = grp.sort_values("tbf_min", ascending=False)  # chronological (high→low = early→late)
        below = grp[grp["gfr"] < -1.0]
        if below.empty:
            continue
        # First bar where GFR crossed -1.0
        first = below.iloc[0]
        # Also grab the yes_vwap at the prior bar (1 bar before crossing — the signal moment)
        idx = grp.index.get_loc(first.name)
        if idx > 0:
            prior = grp.iloc[idx - 1]
            no_ask = 1.0 - prior["yes_vwap"]   # approximation; NO ask ≈ 1 − yes_bid ≈ 1 − yes_vwap
        else:
            no_ask = 1.0 - first["yes_vwap"]

        no_ask = max(0.01, min(0.99, no_ask))
        no_win   = 1 - first["outcome_yes"]  # NO wins when outcome_yes == 0
        no_edge  = no_win * (1 - FEE_PCT) - no_ask  # prospective: but since we know outcome, this is hindsight

        # "Would have been profitable?" — use the ask at signal moment
        prospective_edge = (1.0 - FEE_PCT) - no_ask  # if NO wins (best case)
        # Actual edge at the ask:
        expected_edge = no_win * (1 - FEE_PCT) - no_ask

        reversals.append({
            "ticker":      ticker,
            "date":        date,
            "dow":         first["dow"],
            "gap_pct":     first["gap_pct"],
            "gap_bucket":  _gap_bucket(first["gap_pct"]),
            "tbf_min":     first["tbf_min"],
            "time_bucket": _time_bucket(first["tbf_min"]),
            "gfr_at_cross": first["gfr"],
            "no_ask":      round(no_ask, 4),
            "no_win":      int(no_win),
            "outcome_yes": int(first["outcome_yes"]),
        })

    rev = pd.DataFrame(reversals)

    if rev.empty:
        print("\nNo reversal instances found.")
        return

    total_rev = len(rev)
    no_wr     = rev["no_win"].mean()
    avg_ask   = rev["no_ask"].mean()
    # edge = WR × (1 - fee) - ask
    exp_edge  = no_wr * (1 - FEE_PCT) - avg_ask
    unique_sessions = rev.groupby(["ticker", "date"]).ngroups

    print(f"\nReversal crossings (GFR < -1.0 first touch): {total_rev}")
    print(f"Unique sessions with at least one reversal:   {unique_sessions}")
    print(f"  As % of all gap-UP sessions: {unique_sessions / total_gap_up_sessions * 100:.1f}%")

    print(f"\n── Overall NO win rate at GFR -1.0 crossing ──")
    print(f"  NO wins:       {rev['no_win'].sum():>4} / {total_rev}")
    print(f"  NO win rate:   {no_wr*100:.1f}%")
    print(f"  Avg NO ask:    {avg_ask:.3f}  (≈ ${avg_ask:.2f}/contract)")
    print(f"  Expected edge: {exp_edge*100:+.1f}%")
    edge_label = "POSITIVE — tradeable" if exp_edge > 0.03 else (
                 "MARGINAL — thin edge" if exp_edge > 0 else "NEGATIVE — no edge")
    print(f"  Assessment:    {edge_label}")

    # ── By ticker ──────────────────────────────────────────────────────────────
    print(f"\n── By Ticker ──")
    by_ticker = (rev.groupby("ticker")
                   .agg(n=("no_win","count"),
                        no_wr=("no_win","mean"),
                        avg_ask=("no_ask","mean"))
                   .reset_index())
    by_ticker["edge"] = by_ticker["no_wr"] * (1 - FEE_PCT) - by_ticker["avg_ask"]
    print(f"  {'Ticker':<8} {'N':>4}  {'NO WR':>7}  {'Avg Ask':>8}  {'Edge':>8}")
    print(f"  {'-'*8} {'-'*4}  {'-'*7}  {'-'*8}  {'-'*8}")
    for _, r in by_ticker.sort_values("edge", ascending=False).iterrows():
        flag = " ✓" if r["edge"] > 0.03 else ("  " if r["edge"] > 0 else " ✗")
        print(f"  {r['ticker']:<8} {r['n']:>4}  {r['no_wr']*100:>6.1f}%  "
              f"  {r['avg_ask']:>6.3f}   {r['edge']*100:>+6.1f}%{flag}")

    # ── By time-of-day bucket ──────────────────────────────────────────────────
    print(f"\n── By Time-of-Day (when GFR first crosses -1.0) ──")
    bucket_order = ["09:30–10:30", "10:30–12:00", "12:00–13:30", "13:30–14:00", "14:00–close"]
    by_time = (rev.groupby("time_bucket")
                  .agg(n=("no_win","count"),
                       no_wr=("no_win","mean"),
                       avg_ask=("no_ask","mean"))
                  .reindex(bucket_order).dropna().reset_index())
    by_time["edge"] = by_time["no_wr"] * (1 - FEE_PCT) - by_time["avg_ask"]
    print(f"  {'Time (ET)':<16} {'N':>4}  {'NO WR':>7}  {'Avg Ask':>8}  {'Edge':>8}")
    print(f"  {'-'*16} {'-'*4}  {'-'*7}  {'-'*8}  {'-'*8}")
    for _, r in by_time.iterrows():
        flag = " ✓" if r["edge"] > 0.03 else ("  " if r["edge"] > 0 else " ✗")
        print(f"  {r['time_bucket']:<16} {r['n']:>4}  {r['no_wr']*100:>6.1f}%  "
              f"  {r['avg_ask']:>6.3f}   {r['edge']*100:>+6.1f}%{flag}")

    # ── By gap magnitude ───────────────────────────────────────────────────────
    print(f"\n── By Original Gap Size ──")
    gap_order = ["0.5–1.0%", "1.0–2.0%", "≥2.0%"]
    by_gap = (rev.groupby("gap_bucket")
                 .agg(n=("no_win","count"),
                      no_wr=("no_win","mean"),
                      avg_ask=("no_ask","mean"))
                 .reindex(gap_order).dropna().reset_index())
    by_gap["edge"] = by_gap["no_wr"] * (1 - FEE_PCT) - by_gap["avg_ask"]
    print(f"  {'Gap Size':<12} {'N':>4}  {'NO WR':>7}  {'Avg Ask':>8}  {'Edge':>8}")
    print(f"  {'-'*12} {'-'*4}  {'-'*7}  {'-'*8}  {'-'*8}")
    for _, r in by_gap.iterrows():
        flag = " ✓" if r["edge"] > 0.03 else ("  " if r["edge"] > 0 else " ✗")
        print(f"  {r['gap_bucket']:<12} {r['n']:>4}  {r['no_wr']*100:>6.1f}%  "
              f"  {r['avg_ask']:>6.3f}   {r['edge']*100:>+6.1f}%{flag}")

    # ── Reversal depth: GFR at crossing ────────────────────────────────────────
    print(f"\n── GFR Depth at Crossing vs. NO win rate ──")
    rev["gfr_bucket"] = pd.cut(rev["gfr_at_cross"],
                                bins=[-5.0, -2.0, -1.5, -1.0],
                                labels=["< -2.0", "-2.0 to -1.5", "-1.5 to -1.0"])
    by_gfr = (rev.groupby("gfr_bucket")
                 .agg(n=("no_win","count"),
                      no_wr=("no_win","mean"),
                      avg_ask=("no_ask","mean"))
                 .reset_index())
    by_gfr["edge"] = by_gfr["no_wr"] * (1 - FEE_PCT) - by_gfr["avg_ask"]
    print(f"  {'GFR bucket':<16} {'N':>4}  {'NO WR':>7}  {'Avg Ask':>8}  {'Edge':>8}")
    print(f"  {'-'*16} {'-'*4}  {'-'*7}  {'-'*8}  {'-'*8}")
    for _, r in by_gfr.iterrows():
        flag = " ✓" if r["edge"] > 0.03 else ("  " if r["edge"] > 0 else " ✗")
        print(f"  {r['gfr_bucket']:<16} {r['n']:>4}  {r['no_wr']*100:>6.1f}%  "
              f"  {r['avg_ask']:>6.3f}   {r['edge']*100:>+6.1f}%{flag}")

    # ── Quick re-entry check: do gap-UP days that reverse close as NO? ─────────
    print(f"\n── When does GFR < -1.0 first cross? Distribution ──")
    print(f"  Early (09:30–10:30): {(rev['time_bucket']=='09:30–10:30').sum()}")
    print(f"  Mid   (10:30–12:00): {(rev['time_bucket']=='10:30–12:00').sum()}")
    print(f"  Late  (12:00+):      {(rev['time_bucket'].isin(['12:00–13:30','13:30–14:00','14:00–close'])).sum()}")

    # ── Summary verdict ────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print("VERDICT")
    print(f"{'='*65}")
    tradeable_tickers = by_ticker[by_ticker["edge"] > 0.03]["ticker"].tolist()
    tradeable_times   = by_time[by_time["edge"] > 0.03]["time_bucket"].tolist()
    if exp_edge > 0.03:
        print(f"  Overall edge: {exp_edge*100:+.1f}% — POSITIVE edge at GFR crossing.")
        print(f"  Reversal trades look viable historically.")
    elif exp_edge > 0:
        print(f"  Overall edge: {exp_edge*100:+.1f}% — MARGINAL. Edge exists but thin.")
        print(f"  Reversal trades need execution precision (spread, timing).")
    else:
        print(f"  Overall edge: {exp_edge*100:+.1f}% — NEGATIVE overall.")
        print(f"  Market prices in the reversal quickly; NO ask rises to fair value.")

    if tradeable_tickers:
        print(f"\n  Tickers with edge > 3%: {', '.join(tradeable_tickers)}")
    if tradeable_times:
        print(f"  Time windows with edge > 3%: {', '.join(tradeable_times)}")
    if not tradeable_tickers and not tradeable_times:
        print(f"\n  No sub-segment shows >3% edge. Reversal trades NOT recommended.")

    print(f"\n  Key risk: the NO ask estimate (1 − yes_vwap) is an approximation.")
    print(f"  Real NO ask may be higher when GFR reversal panic bid drives YES down.")
    print(f"  Actual execution edge will be lower than these numbers suggest.")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
