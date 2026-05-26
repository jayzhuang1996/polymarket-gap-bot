"""
Full Session Analysis — 2-minute interval sampling 9:30am–3:58pm.

For every resolved market day across all 9 tickers, samples the YES token VWAP
and (where available) the stock gap-fill-ratio at every 2-minute mark during
the trading session.

Outputs two files:
  data/full_session_2min.csv          — raw observations, one row per (market × time_interval)
  data/settlement_probability.csv     — conditional P($1 | time_bucket, price_bucket, gfr_bucket)

The settlement probability table directly answers operational questions:
  "Token is at 85¢ at 2:30pm with gfr +0.5 — should I hold to settlement?"
  "Token is at 70¢ at 3pm with gfr neutral — sell or hold?"

GFR note:
  yfinance intraday (5-min bars) only goes back ~60 days. For older markets the
  gfr column is None and those rows are included in the price-only table but
  excluded from the gfr-conditioned table. All 150+ days contribute to the
  time × price table regardless.

Day-of-week:
  Thursday historically shows ~82% gap-fill rate vs ~65% Monday. The output
  includes a day-of-week breakdown to validate this for Polymarket specifically.

Usage:  python tools/full_session_analysis.py
"""

import ast
import sys
from datetime import timezone, timedelta, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, ".")

DATA_DIR     = Path("data")
OUT_RAW      = DATA_DIR / "full_session_2min.csv"
OUT_PROB     = DATA_DIR / "settlement_probability.csv"

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

# 2-minute intervals: minutes before 4pm close
# 390 min before close = 9:30am ET.  2 min before close = 3:58pm.
INTERVALS_BEFORE_CLOSE = list(range(390, 0, -2))   # 195 intervals

# ── Bucket definitions ────────────────────────────────────────────────────────

# Time-of-day buckets (minutes before 4pm close)
TIME_BUCKETS = [
    ("09:30–10:00",  390, 360),
    ("10:00–10:30",  360, 330),
    ("10:30–11:00",  330, 300),
    ("11:00–12:00",  300, 240),
    ("12:00–13:00",  240, 180),
    ("13:00–14:00",  180, 120),
    ("14:00–14:30",  120,  90),
    ("14:30–15:00",   90,  60),
    ("15:00–16:00",   60,   0),
]

# YES token price buckets (cents)
PRICE_BUCKETS = [
    ("40–50¢",  0.40, 0.50),
    ("50–60¢",  0.50, 0.60),
    ("60–70¢",  0.60, 0.70),
    ("70–80¢",  0.70, 0.80),
    ("80–90¢",  0.80, 0.90),
    ("90–100¢", 0.90, 1.00),
]

# GFR buckets
GFR_BUCKETS = [
    ("< −0.5",  -99,  -0.5),
    ("−0.5–0",  -0.5,  0.0),
    ("0–0.5",    0.0,  0.5),
    ("> 0.5",    0.5,  99),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_outcome(s):
    try:
        p = ast.literal_eval(s)
        return 1 if float(p[0]) == 1.0 else 0
    except Exception:
        return None


def get_vwap(df):
    if len(df) == 0:
        return None
    total = df["usd_amount"].sum()
    return (df["price"] * df["usd_amount"]).sum() / total if total > 0 else None


def bucket_label(value, buckets):
    """Return the label for the bucket containing value."""
    for label, lo, hi in buckets:
        if lo <= value < hi:
            return label
    return None


def tbf_to_time_label(tbf):
    """Convert minutes-before-close to ET clock label (approximate)."""
    close_h, close_m = 16, 0
    total_min_from_midnight = close_h * 60 + close_m - tbf
    h = total_min_from_midnight // 60
    m = total_min_from_midnight % 60
    return f"{h:02d}:{m:02d} ET"


def get_intraday_5m(yahoo_sym, mkt_date):
    """Fetch 5-minute bars for a specific date via yfinance. Returns None if unavailable."""
    try:
        import pytz
        eastern = pytz.timezone("US/Eastern")
        raw = yf.download(yahoo_sym, period="60d", interval="5m",
                          progress=False, auto_adjust=False)
        if raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]
        raw.index = (raw.index.tz_convert(eastern) if raw.index.tz
                     else raw.index.tz_localize("UTC").tz_convert(eastern))
        day = raw[raw.index.date == mkt_date]
        return day if len(day) >= 20 else None
    except Exception:
        return None


# ── Main collection ───────────────────────────────────────────────────────────

def collect_ticker(ticker_name, yahoo_sym, mdf, trades):
    """Collect 2-minute observations for one ticker across all resolved markets."""
    # Daily stock data for open/prev_close
    stock = yf.download(yahoo_sym, start="2025-10-01", end="2026-06-01",
                        progress=False, auto_adjust=False)
    if stock.empty:
        return []
    if isinstance(stock.columns, pd.MultiIndex):
        stock.columns = [c[0] for c in stock.columns]
    stock = stock.reset_index()
    stock["date"]       = pd.to_datetime(stock["Date"]).dt.date
    stock["prev_close"] = stock["Close"].shift(1)
    stock["open_price"] = stock["Open"]

    pattern  = rf"\({ticker_name}\)\s+Up\s+or\s+Down\s+on"
    mask     = mdf["question"].str.contains(pattern, na=False, regex=True)
    resolved = mdf[mask & (mdf["closed"] == 1)].copy()
    if len(resolved) == 0:
        return []

    resolved["end_ts"] = resolved["end_date"].astype("int64") // 1_000_000_000

    rows = []
    intraday_cache = {}   # mkt_date → DataFrame or None (avoid repeated downloads)

    for _, mkt in resolved.iterrows():
        end_dt = mkt["end_date"]
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        mkt_date = end_dt.date()

        outcome = parse_outcome(mkt["outcome_prices"])
        if outcome is None:
            continue

        stk = stock[stock["date"] == mkt_date]
        if len(stk) == 0:
            continue
        open_p  = float(stk.iloc[0]["open_price"])
        prev_p  = float(stk.iloc[0]["prev_close"])
        if pd.isna(prev_p) or prev_p == 0 or open_p == 0:
            continue

        gap_pct     = (open_p - prev_p) / prev_p * 100
        gap_dollars = open_p - prev_p
        dow         = end_dt.weekday()   # 0=Mon, 4=Fri
        dow_name    = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][dow]
        end_ts      = mkt["end_ts"]
        cid         = mkt["condition_id"]

        # Fetch intraday 5-min data (cached per date to avoid repeated downloads)
        if mkt_date not in intraday_cache:
            intraday_cache[mkt_date] = get_intraday_5m(yahoo_sym, mkt_date)
        intraday = intraday_cache[mkt_date]

        # Sample at every 2-minute interval
        for tbf in INTERVALS_BEFORE_CLOSE:
            target_ts = end_ts - tbf * 60
            lo = target_ts - 60   # ±1 minute window
            hi = target_ts + 60

            window = trades[
                (trades["condition_id"] == cid) &
                (trades["timestamp"] >= lo) &
                (trades["timestamp"] <= hi)
            ]
            yes_vwap = get_vwap(window)
            if yes_vwap is None:
                continue   # no trades in this 2-min window, skip

            # Stock gfr at this time (if intraday data available)
            gfr = None
            if intraday is not None and abs(gap_dollars) > 0.001:
                target_time_str = tbf_to_time_label(tbf)  # "HH:MM ET"
                h_str, rest = target_time_str.split(":")
                m_str = rest[:2]
                h, m = int(h_str), int(m_str)
                bars_before = intraday[
                    (intraday.index.hour < h) |
                    ((intraday.index.hour == h) & (intraday.index.minute <= m))
                ]
                if len(bars_before) > 0:
                    stock_price = float(bars_before.iloc[-1]["Close"])
                    gfr = (stock_price - open_p) / gap_dollars
                    gfr = max(-5.0, min(5.0, gfr))

            rows.append({
                "ticker":      ticker_name,
                "date":        mkt_date,
                "dow":         dow_name,
                "tbf_min":     tbf,               # minutes before 4pm close
                "yes_vwap":    round(yes_vwap, 4),
                "gfr":         round(gfr, 3) if gfr is not None else None,
                "gap_pct":     round(gap_pct, 3),
                "outcome_yes": outcome,
                "n_trades":    len(window),
            })

    return rows


# ── Aggregation ───────────────────────────────────────────────────────────────

def build_probability_table(df):
    """Build P(settle YES=$1 | time_bucket, price_bucket, gfr_bucket) table."""
    results = []

    for t_label, t_hi, t_lo in TIME_BUCKETS:
        t_sub = df[(df["tbf_min"] <= t_hi) & (df["tbf_min"] > t_lo)]
        if len(t_sub) == 0:
            continue

        for p_label, p_lo, p_hi in PRICE_BUCKETS:
            p_sub = t_sub[(t_sub["yes_vwap"] >= p_lo) & (t_sub["yes_vwap"] < p_hi)]
            if len(p_sub) < 3:
                continue

            # Overall (no gfr condition)
            n, wins = len(p_sub), p_sub["outcome_yes"].sum()
            results.append({
                "time_bucket":  t_label,
                "price_bucket": p_label,
                "gfr_bucket":   "ALL",
                "n_obs":        n,
                "p_settle_yes": round(wins / n * 100, 1),
                "implied_prob": round((p_lo + p_hi) / 2 * 100, 1),
                "edge_vs_market": round((wins / n - (p_lo + p_hi) / 2) * 100, 1),
            })

            # GFR-conditioned (only rows where gfr is available)
            g_avail = p_sub.dropna(subset=["gfr"])
            for g_label, g_lo, g_hi in GFR_BUCKETS:
                g_sub = g_avail[(g_avail["gfr"] >= g_lo) & (g_avail["gfr"] < g_hi)]
                if len(g_sub) < 3:
                    continue
                ng, wg = len(g_sub), g_sub["outcome_yes"].sum()
                results.append({
                    "time_bucket":    t_label,
                    "price_bucket":   p_label,
                    "gfr_bucket":     g_label,
                    "n_obs":          ng,
                    "p_settle_yes":   round(wg / ng * 100, 1),
                    "implied_prob":   round((p_lo + p_hi) / 2 * 100, 1),
                    "edge_vs_market": round((wg / ng - (p_lo + p_hi) / 2) * 100, 1),
                })

    return pd.DataFrame(results)


def build_dow_table(df):
    """Day-of-week breakdown: does Thursday really have higher gap-fill rates?"""
    # For each DOW, compare outcome_yes rate on gap-up vs gap-down days
    rows = []
    for dow in ["Mon","Tue","Wed","Thu","Fri"]:
        sub = df[df["dow"] == dow]
        if len(sub) < 10:
            continue
        gap_up = sub[sub["gap_pct"] > 0.5]
        gap_dn = sub[sub["gap_pct"] < -0.5]
        if len(gap_up) >= 5:
            rows.append({"dow": dow, "direction": "Gap-Up >0.5%",
                         "n": len(gap_up), "p_yes_settle": round(gap_up["outcome_yes"].mean()*100,1)})
        if len(gap_dn) >= 5:
            rows.append({"dow": dow, "direction": "Gap-Dn <-0.5%",
                         "n": len(gap_dn), "p_yes_settle": round(gap_dn["outcome_yes"].mean()*100,1)})
    return pd.DataFrame(rows)


# ── Print key findings ────────────────────────────────────────────────────────

def print_exit_guidance(prob_df):
    """Print the most actionable findings: what to do at 2pm/2:30pm/3pm."""
    KEY_TIMES = ["14:00–14:30", "14:30–15:00", "15:00–16:00"]

    print(f"\n{'='*90}")
    print("  EXIT DECISION GUIDE — P(settle YES=$1) by time, price, and gap fill")
    print(f"  Hold to settlement if P > 88% and gfr is positive.")
    print(f"  Sell now if P ≤ 75% or gfr is negative/flat.")
    print(f"{'='*90}")

    for t_label in KEY_TIMES:
        sub = prob_df[prob_df["time_bucket"] == t_label]
        if len(sub) == 0:
            continue
        print(f"\n  ── {t_label} ──────────────────────────────────────")
        print(f"  {'Price':12} {'GFR':12} {'n':5} {'P($1)':8} {'Market':8} {'Edge':8} {'Action'}")
        print(f"  {'─'*65}")

        sub_sorted = sub.sort_values(["price_bucket","gfr_bucket"])
        for _, r in sub_sorted.iterrows():
            action = ""
            p = r["p_settle_yes"]
            if r["gfr_bucket"] != "ALL":
                if p >= 88 and r["gfr_bucket"] in ("> 0.5","0–0.5"):
                    action = "HOLD → settlement"
                elif p < 75 or r["gfr_bucket"] in ("< −0.5","−0.5–0"):
                    action = "SELL NOW"
                else:
                    action = "monitor"
            print(f"  {r['price_bucket']:12} {r['gfr_bucket']:12} {r['n_obs']:5} "
                  f"{p:6.1f}%  {r['implied_prob']:5.1f}%  {r['edge_vs_market']:+5.1f}%  {action}")


def print_dow_guidance(dow_df):
    print(f"\n{'='*90}")
    print("  DAY-OF-WEEK SETTLEMENT RATES")
    print(f"  (Thursdays historically have higher gap-fill rates for futures ~82% vs 65%)")
    print(f"{'='*90}")
    print(f"\n  {'DOW':6} {'Direction':18} {'n':5} {'P(YES settles $1)':20}")
    print(f"  {'─'*50}")
    for _, r in dow_df.iterrows():
        print(f"  {r['dow']:6} {r['direction']:18} {r['n']:5} {r['p_yes_settle']:5.1f}%")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading markets and trades...")
    mdf = pd.read_parquet(DATA_DIR / "markets.parquet", engine="pyarrow")

    all_rows = []
    for ticker_name, yahoo_sym in TICKERS.items():
        fname = "spx_trades" if ticker_name == "SPX" else f"{ticker_name.lower()}_trades"
        path  = DATA_DIR / f"{fname}.parquet"
        if not path.exists():
            print(f"  SKIP {ticker_name}: {path} not found")
            continue
        print(f"  Collecting {ticker_name}...")
        trades = pd.read_parquet(path, engine="pyarrow")
        rows   = collect_ticker(ticker_name, yahoo_sym, mdf, trades)
        all_rows.extend(rows)
        print(f"    {ticker_name}: {len(rows):,} interval observations")

    if not all_rows:
        print("No data. Check parquet files.")
        return

    df = pd.DataFrame(all_rows)
    df.to_csv(OUT_RAW, index=False)
    print(f"\n  Raw observations saved → {OUT_RAW}  ({len(df):,} rows)")
    print(f"  Market-days covered: {df['date'].nunique()}")
    print(f"  Rows with gfr data:  {df['gfr'].notna().sum():,} ({df['gfr'].notna().mean()*100:.0f}%)")

    # ── Probability table ──────────────────────────────────────────────────
    prob_df = build_probability_table(df)
    prob_df.to_csv(OUT_PROB, index=False)
    print(f"  Settlement probability table saved → {OUT_PROB}  ({len(prob_df)} cells)")

    # ── Day-of-week ────────────────────────────────────────────────────────
    dow_df = build_dow_table(df)

    # ── Print findings ─────────────────────────────────────────────────────
    print_exit_guidance(prob_df)
    print_dow_guidance(dow_df)

    # ── Summary stats ──────────────────────────────────────────────────────
    print(f"\n{'='*90}")
    print("  INTRADAY PRICE PATH — average YES token price by time window")
    print(f"{'='*90}")
    print(f"\n  {'Time':18} {'Avg YES¢':10} {'Median':8} {'n_obs':8} {'Overall P($1)'}")
    print(f"  {'─'*55}")
    for t_label, t_hi, t_lo in TIME_BUCKETS:
        sub = df[(df["tbf_min"] <= t_hi) & (df["tbf_min"] > t_lo)]
        if len(sub) < 5:
            continue
        avg_p   = sub["yes_vwap"].mean() * 100
        med_p   = sub["yes_vwap"].median() * 100
        p_settle = sub["outcome_yes"].mean() * 100
        print(f"  {t_label:18} {avg_p:8.1f}¢  {med_p:6.1f}¢  {len(sub):7,}  {p_settle:.1f}%")

    print(f"\n  Key action thresholds (from probability table):")
    key = prob_df[
        (prob_df["gfr_bucket"] != "ALL") &
        (prob_df["time_bucket"].isin(["14:00–14:30","14:30–15:00","15:00–16:00"])) &
        (prob_df["price_bucket"].isin(["70–80¢","80–90¢","90–100¢"]))
    ].sort_values(["time_bucket","price_bucket","gfr_bucket"])

    if len(key) > 0:
        print(f"\n  {'Time':14} {'Price':12} {'GFR':12} {'P($1)':8} {'n':5}")
        print(f"  {'─'*55}")
        for _, r in key.iterrows():
            flag = " ← HOLD" if r["p_settle_yes"] >= 88 else (" ← SELL" if r["p_settle_yes"] < 70 else "")
            print(f"  {r['time_bucket']:14} {r['price_bucket']:12} {r['gfr_bucket']:12} "
                  f"{r['p_settle_yes']:5.1f}%  {r['n_obs']:4}{flag}")


if __name__ == "__main__":
    main()
