"""
Out-of-sample validation with Bonferroni correction and Wilson confidence intervals.

Split:
  In-sample  (IS):  Oct 15 2025 – Mar 31 2026  ← strategy was built on this data
  Out-of-sample (OOS): Apr 01 2026 – present   ← never used for model building

For every (ticker × gap_bucket) cell at the 9:30am entry window:
  1. WR + Wilson 95% CI for IS and OOS separately
  2. Edge@Ask for both (tradeable edge, not VWAP)
  3. One-sided binomial test: H0 = WR ≤ breakeven (i.e. edge ≤ 0)
  4. Bonferroni correction across all tested cells
  5. Verdict per cell: CONFIRMED / SIGNAL / INCONCLUSIVE / FAILED

Verdicts:
  ✅ CONFIRMED    — OOS edge positive AND p < Bonferroni threshold
  ⚠  SIGNAL       — OOS edge positive AND p < 0.05 (not Bonferroni-significant yet)
  —  INCONCLUSIVE — OOS edge positive but p ≥ 0.05 (too few observations to judge)
  ❌ FAILED       — OOS edge zero or negative (strategy does not hold out-of-sample)

Usage: python tools/oos_validation.py
"""

import ast
import sys
from datetime import date, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf
from scipy.stats import binomtest
from statsmodels.stats.proportion import proportion_confint

sys.path.insert(0, ".")

DATA_DIR   = Path("data")
OOS_CUTOFF = date(2026, 4, 1)   # first day of out-of-sample window
FEE        = 0.99               # 1% settlement fee applied at payout
MIN_OBS    = 5                  # minimum observations to report a cell

TICKERS = {
    "SPX":   "^GSPC",
    "NVDA":  "NVDA",
    "TSLA":  "TSLA",
    "AAPL":  "AAPL",
    "AMZN":  "AMZN",
    "GOOGL": "GOOGL",
    "META":  "META",
    "MSFT":  "MSFT",
    "NFLX":  "NFLX",
}

# Four buckets that cover all tradeable gaps (flat gaps excluded)
GAP_BUCKETS = [
    ("dn_strong", "Gap-Dn  > 1%",   lambda g: g <= -1.0),
    ("dn_mod",    "Gap-Dn 0.5-1%",  lambda g: -1.0 < g <= -0.5),
    ("up_mod",    "Gap-Up 0.5-1%",  lambda g:  0.5 <= g < 1.0),
    ("up_strong", "Gap-Up  > 1%",   lambda g:  g >= 1.0),
]

# 9:30am entry window: 385–395 minutes before 4pm close
ENTRY_WIN_MIN, ENTRY_WIN_MAX = 385, 395


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_outcome(s):
    try:
        p = ast.literal_eval(s)
        return 1 if float(p[0]) == 1.0 else 0
    except Exception:
        return None


def get_price_stats(df):
    """Return (vwap, ask_estimate) from a window of trades.

    ask_estimate = vwap + half the observed price range.
    The price range of trades in a window approximates the bid-ask spread;
    half of it is the distance from mid (≈ VWAP) to the ask.
    """
    if len(df) == 0:
        return None, None
    total = df["usd_amount"].sum()
    if total == 0:
        return None, None
    vwap    = (df["price"] * df["usd_amount"]).sum() / total
    spread  = df["price"].max() - df["price"].min()
    ask_est = min(vwap + spread / 2, 0.99)
    return round(vwap, 4), round(ask_est, 4)


def wilson_ci(wins, n, alpha=0.05):
    """Wilson 95% CI as (lo_pct, hi_pct)."""
    if n == 0:
        return float("nan"), float("nan")
    lo, hi = proportion_confint(wins, n, alpha=alpha, method="wilson")
    return lo * 100, hi * 100


# ── Data builder ──────────────────────────────────────────────────────────────

def build_observations(ticker_name, yahoo_sym, mdf, trades):
    """
    One row per resolved market day for this ticker that falls in a
    tradeable gap bucket and has trade data at the 9:30am window.

    Returns DataFrame with columns:
      date, split, gap_pct, bucket_key, bucket_label,
      outcome_yes, yes_vwap, yes_ask
    """
    # Daily stock data — use unadjusted prices for gap calculation
    stock = yf.download(yahoo_sym, start="2025-10-01", end="2026-06-01",
                        progress=False, auto_adjust=False)
    if stock.empty:
        print(f"  WARNING: no stock data for {yahoo_sym}")
        return pd.DataFrame()

    if isinstance(stock.columns, pd.MultiIndex):
        stock.columns = [c[0] for c in stock.columns]
    stock = stock.reset_index()
    stock["date"]       = pd.to_datetime(stock["Date"]).dt.date
    stock["prev_close"] = stock["Close"].shift(1)
    stock["gap_pct"]    = (stock["Open"] / stock["prev_close"] - 1) * 100

    # Resolved markets for this ticker
    pattern  = rf"\({ticker_name}\)\s+Up\s+or\s+Down\s+on"
    mask     = mdf["question"].str.contains(pattern, na=False, regex=True)
    resolved = mdf[mask & (mdf["closed"] == 1)].copy()
    if len(resolved) == 0:
        return pd.DataFrame()

    resolved["end_ts"] = resolved["end_date"].astype("int64") // 1_000_000_000

    rows = []
    for _, mkt in resolved.iterrows():
        end_dt = mkt["end_date"]
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        mkt_date = end_dt.date()
        split    = "OOS" if mkt_date >= OOS_CUTOFF else "IS"

        outcome = parse_outcome(mkt["outcome_prices"])
        if outcome is None:
            continue

        stk = stock[stock["date"] == mkt_date]
        if len(stk) == 0:
            continue
        gap_pct = stk.iloc[0]["gap_pct"]
        if pd.isna(gap_pct):
            continue

        # Classify into a gap bucket
        bucket_key = bucket_label = None
        for bkey, blabel, bfn in GAP_BUCKETS:
            if bfn(gap_pct):
                bucket_key, bucket_label = bkey, blabel
                break
        if bucket_key is None:
            continue   # flat gap — not trading

        # 9:30am trade window
        end_ts = mkt["end_ts"]
        lo     = end_ts - ENTRY_WIN_MAX * 60
        hi     = end_ts - ENTRY_WIN_MIN * 60
        window = trades[
            (trades["condition_id"] == mkt["condition_id"]) &
            (trades["timestamp"] >= lo) &
            (trades["timestamp"] <= hi)
        ]
        vwap, ask_est = get_price_stats(window)
        if vwap is None:
            continue

        rows.append({
            "date":         mkt_date,
            "split":        split,
            "gap_pct":      gap_pct,
            "bucket_key":   bucket_key,
            "bucket_label": bucket_label,
            "outcome_yes":  outcome,
            "yes_vwap":     vwap,
            "yes_ask":      ask_est,
        })

    return pd.DataFrame(rows)


# ── Cell statistics ───────────────────────────────────────────────────────────

def cell_stats(sub):
    """
    Compute stats for one (ticker, bucket, split) cell.

    Returns dict with: n, wins, wr, ci_lo, ci_hi,
                       avg_ask_cents, edge_mid_pct, edge_ask_pct,
                       breakeven_wr, p_val
    Or None if fewer than MIN_OBS rows.
    """
    if sub is None or len(sub) < MIN_OBS:
        return None

    wins = int(sub["outcome_yes"].sum())
    n    = len(sub)
    wr   = wins / n * 100
    ci_lo, ci_hi = wilson_ci(wins, n)

    avg_vwap = sub["yes_vwap"].mean()
    avg_ask  = sub["yes_ask"].mean()
    edge_mid = sub["outcome_yes"].mean() * FEE - avg_vwap
    edge_ask = sub["outcome_yes"].mean() * FEE - avg_ask

    # Breakeven WR: price = WR × FEE → WR_breakeven = avg_ask / FEE
    breakeven_wr = avg_ask / FEE

    # One-sided binomial test: H0 = WR ≤ breakeven (edge ≤ 0 at the ask)
    p_val = binomtest(wins, n, breakeven_wr, alternative="greater").pvalue

    return {
        "n":               n,
        "wins":            wins,
        "wr":              wr,
        "ci_lo":           ci_lo,
        "ci_hi":           ci_hi,
        "avg_ask_cents":   avg_ask * 100,
        "edge_mid_pct":    edge_mid * 100,
        "edge_ask_pct":    edge_ask * 100,
        "breakeven_wr":    breakeven_wr * 100,
        "p_val":           p_val,
    }


def verdict(oos_st, corrected_alpha):
    if oos_st is None:
        return "— NO OOS DATA"
    if oos_st["edge_ask_pct"] <= 0:
        return "❌ FAILED"
    if oos_st["p_val"] < corrected_alpha:
        return "✅ CONFIRMED"
    if oos_st["p_val"] < 0.05:
        return "⚠  SIGNAL"
    return "—  INCONCLUSIVE"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    mdf = pd.read_parquet(DATA_DIR / "markets.parquet")

    # Build observations across all tickers
    all_obs = []
    for ticker, yahoo_sym in TICKERS.items():
        fname = "spx_trades" if ticker == "SPX" else f"{ticker.lower()}_trades"
        path  = DATA_DIR / f"{fname}.parquet"
        if not path.exists():
            print(f"  SKIP {ticker}: {path} not found")
            continue
        print(f"  Loading {ticker}...")
        trades = pd.read_parquet(path)
        obs    = build_observations(ticker, yahoo_sym, mdf, trades)
        if len(obs) > 0:
            obs["ticker"] = ticker
            all_obs.append(obs)

    if not all_obs:
        print("No data loaded. Check that parquet files exist in data/.")
        return

    df     = pd.concat(all_obs, ignore_index=True)
    is_df  = df[df["split"] == "IS"]
    oos_df = df[df["split"] == "OOS"]

    # ── Split summary ──────────────────────────────────────────────────────
    print(f"\n{'='*115}")
    print("  DATA SPLIT")
    print(f"{'='*115}")
    is_days  = is_df["date"].nunique()
    oos_days = oos_df["date"].nunique()
    is_end   = is_df["date"].max() if len(is_df) > 0 else "—"
    oos_end  = oos_df["date"].max() if len(oos_df) > 0 else "—"
    print(f"  In-sample  (Oct 2025 – Mar 2026): {len(is_df):>5} observations  |  {is_days} market-days  |  last: {is_end}")
    print(f"  Out-of-sample (Apr 2026 – {oos_end}): {len(oos_df):>5} observations  |  {oos_days} market-days")

    # ── Bonferroni threshold ───────────────────────────────────────────────
    n_tests = len(TICKERS) * len(GAP_BUCKETS)   # 9 × 4 = 36
    corrected_alpha = 0.05 / n_tests
    print(f"\n  Testing {n_tests} cells (9 tickers × 4 gap buckets)")
    print(f"  Bonferroni corrected α = 0.05 / {n_tests} = {corrected_alpha:.5f}")
    print(f"  A cell needs p < {corrected_alpha:.5f} to be labelled ✅ CONFIRMED")
    print(f"  A cell with p < 0.05 but ≥ {corrected_alpha:.5f} is ⚠ SIGNAL (promising, not conclusive)")

    # ── Main table ─────────────────────────────────────────────────────────
    print(f"\n{'='*115}")
    print("  IN-SAMPLE vs OUT-OF-SAMPLE  —  9:30am entry, Edge measured at ask price")
    print(f"{'='*115}")

    col_h = (f"  {'Ticker':<7} {'Gap Bucket':<16} "
             f"{'IS  n':<6} {'IS  WR [95% CI]':<22} {'IS Edge@Ask':<13}"
             f"{'OOS n':<6} {'OOS WR [95% CI]':<22} {'OOS Edge@Ask':<13}"
             f"{'p-val':<8} Verdict")
    print(col_h)
    print(f"  {'─'*110}")

    results = []
    for ticker in TICKERS:
        for bkey, blabel, _ in GAP_BUCKETS:
            is_sub  = is_df[ (is_df["ticker"]  == ticker) & (is_df["bucket_key"]  == bkey)]
            oos_sub = oos_df[(oos_df["ticker"] == ticker) & (oos_df["bucket_key"] == bkey)]

            is_st  = cell_stats(is_sub)
            oos_st = cell_stats(oos_sub)

            # Skip entirely if neither split has data
            if is_st is None and oos_st is None:
                continue

            def fmt(st):
                if st is None:
                    return f"{'<'+str(MIN_OBS):<6}", f"{'insufficient data':<22}", f"{'N/A':<13}"
                n_s    = f"{st['n']:<6}"
                wr_s   = f"{st['wr']:.1f}% [{st['ci_lo']:.0f}-{st['ci_hi']:.0f}%]"
                edge_s = f"{st['edge_ask_pct']:+.1f}%"
                return n_s, f"{wr_s:<22}", f"{edge_s:<13}"

            is_n,  is_wr,  is_edge  = fmt(is_st)
            oos_n, oos_wr, oos_edge = fmt(oos_st)
            p_s  = f"{oos_st['p_val']:.4f}" if oos_st else "N/A"
            vrd  = verdict(oos_st, corrected_alpha)

            print(f"  {ticker:<7} {blabel:<16} "
                  f"{is_n}{is_wr}{is_edge}"
                  f"{oos_n}{oos_wr}{oos_edge}"
                  f"{p_s:<8} {vrd}")

            results.append({
                "ticker":       ticker,
                "bucket":       blabel,
                "is_n":         is_st["n"]           if is_st  else 0,
                "is_wr":        is_st["wr"]           if is_st  else None,
                "is_edge_ask":  is_st["edge_ask_pct"] if is_st  else None,
                "oos_n":        oos_st["n"]           if oos_st else 0,
                "oos_wr":       oos_st["wr"]          if oos_st else None,
                "oos_edge_ask": oos_st["edge_ask_pct"] if oos_st else None,
                "p_val":        oos_st["p_val"]       if oos_st else None,
                "verdict":      vrd,
            })

    # ── Verdict summary ────────────────────────────────────────────────────
    res_df    = pd.DataFrame(results)
    confirmed = res_df[res_df["verdict"].str.startswith("✅")]
    signal    = res_df[res_df["verdict"].str.startswith("⚠")]
    incon     = res_df[res_df["verdict"].str.startswith("—  INC")]
    failed    = res_df[res_df["verdict"].str.startswith("❌")]
    no_data   = res_df[res_df["verdict"].str.startswith("— NO")]

    print(f"\n{'='*115}")
    print("  VERDICT SUMMARY")
    print(f"{'='*115}")
    print(f"  ✅ CONFIRMED    {len(confirmed):>3}  — trade at full sizing")
    print(f"  ⚠  SIGNAL       {len(signal):>3}  — trade at half sizing; needs more OOS data")
    print(f"  —  INCONCLUSIVE {len(incon):>3}  — paper trade only")
    print(f"  ❌ FAILED        {len(failed):>3}  — remove from strategy")
    print(f"  — No OOS data   {len(no_data):>3}  — accumulate data first")

    if len(confirmed) > 0:
        print(f"\n  ✅ Confirmed cells (trade these):")
        for _, r in confirmed.iterrows():
            print(f"     {r['ticker']:<6} {r['bucket']:<16}  "
                  f"IS={r['is_wr']:.1f}% → OOS={r['oos_wr']:.1f}%  |  OOS Edge@Ask={r['oos_edge_ask']:+.1f}%  |  p={r['p_val']:.5f}")

    if len(signal) > 0:
        print(f"\n  ⚠  Signal cells (half sizing):")
        for _, r in signal.iterrows():
            print(f"     {r['ticker']:<6} {r['bucket']:<16}  "
                  f"IS={r['is_wr']:.1f}% → OOS={r['oos_wr']:.1f}%  |  OOS Edge@Ask={r['oos_edge_ask']:+.1f}%  |  p={r['p_val']:.5f}")

    if len(failed) > 0:
        print(f"\n  ❌ Failed cells (remove from strategy):")
        for _, r in failed.iterrows():
            oos_wr_s = f"{r['oos_wr']:.1f}%" if r["oos_wr"] is not None else "N/A"
            oos_edge_s = f"{r['oos_edge_ask']:+.1f}%" if r["oos_edge_ask"] is not None else "N/A"
            print(f"     {r['ticker']:<6} {r['bucket']:<16}  "
                  f"IS={r['is_wr']:.1f}% → OOS={oos_wr_s}  |  OOS Edge@Ask={oos_edge_s}")

    # ── OOS-only summary for context ───────────────────────────────────────
    print(f"\n{'='*115}")
    print(f"  OOS PERIOD CONTEXT  (Apr 1 – {oos_end}):  {oos_days} trading days")
    print(f"  Small OOS sample is expected. Re-run monthly as data accumulates.")
    print(f"  A SIGNAL today can become CONFIRMED in 4-6 more weeks.")
    print(f"{'='*115}")


if __name__ == "__main__":
    main()
