"""
One-time backfill: fetch Twelve Data 5-min intraday bars for the GFR-dark period
(Oct 16 2025 → Feb 26 2026) and patch full_session_2min.csv.

91 trading days × 9 tickers where GFR = NaN because yfinance only holds 60 days
of intraday history. Twelve Data free tier (800 calls/day) covers this in 2 calls
per ticker × 9 tickers = 18 total API calls.

After running this, re-run:
  python tools/calibrate_exit_model.py
  python tools/train_settlement_model.py

Usage:
  python tools/backfill_gfr_twelvedata.py          # fetch + backfill
  python tools/backfill_gfr_twelvedata.py --dry-run # show what would be filled, no writes
"""

import os
import sys
import time
import argparse
import requests
import pandas as pd
import pytz
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, ".")
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY  = os.getenv("TWELVEDATA_API_KEY", "")
DATA_DIR = Path("data")
CACHE_DIR = DATA_DIR / "twelvedata"        # 5-min bar parquet files cached here
CSV_PATH  = DATA_DIR / "full_session_2min.csv"
TD_BASE   = "https://api.twelvedata.com/time_series"
EASTERN   = pytz.timezone("US/Eastern")

# The GFR-dark period: dates where yfinance 60-day window can't reach
GAP_START = "2025-10-15"
GAP_END   = "2026-02-27"

# Twelve Data symbol for each display ticker.
# SPX (S&P 500 index) is locked behind Twelve Data's paid plan.
# SPY (the S&P 500 ETF) is available free and moves in lockstep — GFR is identical.
TD_SYMBOLS = {
    "SPX":   "SPY",   # proxy: SPY tracks SPX with <0.01% tracking error
    "NVDA":  "NVDA",
    "TSLA":  "TSLA",
    "AAPL":  "AAPL",
    "AMZN":  "AMZN",
    "GOOGL": "GOOGL",
    "META":  "META",
    "MSFT":  "MSFT",
    "NFLX":  "NFLX",
}

# Yahoo Finance symbols for daily OHLCV (open/prev_close — no intraday limit on daily)
YAHOO_SYMBOLS = {
    "SPX":   "SPY",    # must match TD_SYMBOLS["SPX"] = "SPY" — both use SPY price scale
    "NVDA":  "NVDA",
    "TSLA":  "TSLA",
    "AAPL":  "AAPL",
    "AMZN":  "AMZN",
    "GOOGL": "GOOGL",
    "META":  "META",
    "MSFT":  "MSFT",
    "NFLX":  "NFLX",
}

# Free tier: 8 requests/minute → sleep 8s between API calls to stay safe
TD_SLEEP_SEC = 8


# ── Twelve Data fetch ─────────────────────────────────────────────────────────

def _fetch_one_page(td_symbol: str, start: str, end: str) -> list[dict]:
    """Single Twelve Data API call. Returns list of bar dicts or [] on error."""
    params = {
        "symbol":     td_symbol,
        "interval":   "5min",
        "start_date": start,
        "end_date":   end,
        "timezone":   "America/New_York",
        "outputsize": 5000,
        "apikey":     API_KEY,
    }
    try:
        r = requests.get(TD_BASE, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"      HTTP error: {e}")
        return []

    if data.get("status") != "ok":
        msg = data.get("message", "unknown error")
        # "no data" is not a failure — some dates have no bars (holiday, etc.)
        if "no data" not in msg.lower():
            print(f"      API error: {msg}")
        return []

    return data.get("values", [])


def fetch_td_5min(ticker: str, td_symbol: str) -> pd.DataFrame | None:
    """
    Fetch 5-min bars for the full GFR-dark period.

    Split into two requests because 91 trading days × 78 bars/day ≈ 7,100 bars,
    which exceeds the 5,000-bar-per-request limit on the free tier.
    Mid-point: Jan 12, 2026 (roughly halves the range).
    """
    mid = "2026-01-12"

    all_rows: list[dict] = []
    for part, (start, end) in enumerate([
        (GAP_START, mid),
        (mid,       GAP_END),
    ], start=1):
        print(f"    part {part}/2: {start} → {end} ...", end=" ", flush=True)
        rows = _fetch_one_page(td_symbol, start, end)
        print(f"{len(rows)} bars")
        all_rows.extend(rows)
        if part < 2:
            time.sleep(TD_SLEEP_SEC)

    if not all_rows:
        return None

    df = pd.DataFrame(all_rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    df["close"] = df["close"].astype(float)
    return df[["close"]]


# ── Daily OHLCV for open/prev_close ──────────────────────────────────────────

def load_daily_stock(ticker: str, yahoo_sym: str) -> pd.DataFrame | None:
    """
    Pull daily OHLCV from yfinance. Daily bars have no 60-day limit, so this
    covers the full Oct 2025 → Feb 2026 period without issue.
    Returns DataFrame with columns: date, open_price, prev_close.
    """
    import yfinance as yf
    stock = yf.download(yahoo_sym, start="2025-10-01", end="2026-06-01",
                        progress=False, auto_adjust=False)
    if stock.empty:
        print(f"    WARNING: no daily data for {ticker} ({yahoo_sym})")
        return None
    if isinstance(stock.columns, pd.MultiIndex):
        stock.columns = [c[0] for c in stock.columns]
    stock = stock.reset_index()
    stock["date"]       = pd.to_datetime(stock["Date"]).dt.date
    stock["prev_close"] = stock["Close"].shift(1)
    stock["open_price"] = stock["Open"]
    return stock[["date", "open_price", "prev_close"]]


# ── GFR backfill ─────────────────────────────────────────────────────────────

def backfill_gfr(df_csv: pd.DataFrame, ticker: str,
                 td_df: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Fill null GFR values for one ticker using cached Twelve Data 5-min bars.

    Logic mirrors full_session_analysis.py:
      gfr = (stock_price_at_time - open_price) / (open_price - prev_close)
      clamped to [-5.0, 5.0]

    Returns (updated_df, n_filled).
    """
    # Localize the Twelve Data index to Eastern (it was fetched as ET-naive strings)
    if td_df.index.tz is None:
        td_df.index = td_df.index.tz_localize(EASTERN)

    mask = (df_csv["ticker"] == ticker) & df_csv["gfr"].isna()
    null_rows = df_csv[mask]
    if len(null_rows) == 0:
        return df_csv, 0

    # Build a date → (open_price, gap_dollars) lookup for fast access
    date_lookup: dict = {}
    for _, row in daily.iterrows():
        d = row["date"]
        op = float(row["open_price"])
        pc = row["prev_close"]
        if pd.isna(pc) or pc == 0 or op == 0:
            continue
        gap = op - float(pc)
        if abs(gap) < 0.001:
            continue
        date_lookup[d] = (op, gap)

    filled = 0
    for idx, row in null_rows.iterrows():
        row_date = pd.Timestamp(row["date"]).date()
        if row_date not in date_lookup:
            continue
        open_p, gap_dollars = date_lookup[row_date]

        # Convert tbf_min (minutes before 4pm close) → ET clock time
        tbf = int(row["tbf_min"])
        target_min = 16 * 60 - tbf          # minutes from midnight
        h, m = divmod(target_min, 60)
        target_dt = (pd.Timestamp(row_date)
                     .tz_localize(EASTERN)
                     .replace(hour=h, minute=m, second=0))

        # Last 5-min bar at or before the target time on that date
        day_bars = td_df[td_df.index.date == row_date]
        bars_at_or_before = day_bars[day_bars.index <= target_dt]
        if len(bars_at_or_before) == 0:
            continue

        stock_price = float(bars_at_or_before.iloc[-1]["close"])
        gfr = (stock_price - open_p) / gap_dollars
        gfr = round(max(-5.0, min(5.0, gfr)), 3)

        df_csv.at[idx, "gfr"] = gfr
        filled += 1

    return df_csv, filled


# ── Main ──────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False) -> None:
    if not API_KEY:
        print("ERROR: TWELVEDATA_API_KEY not set. Add it to .env and retry.")
        sys.exit(1)

    CACHE_DIR.mkdir(exist_ok=True)

    print(f"Loading {CSV_PATH} ...")
    df_csv = pd.read_csv(CSV_PATH)
    null_before = int(df_csv["gfr"].isna().sum())
    print(f"  Total rows: {len(df_csv):,}  |  Null GFR: {null_before:,} ({null_before/len(df_csv)*100:.1f}%)")

    if dry_run:
        print("\n[DRY RUN] Would fetch Twelve Data and fill the above rows.")
        print("  Tickers:", list(TD_SYMBOLS.keys()))
        print("  Period:", GAP_START, "→", GAP_END)
        print("  API calls needed: ~18 (2 per ticker)")
        return

    print(f"\nFetching daily OHLCV from yfinance (no 60-day limit on daily bars) ...")
    daily_cache: dict[str, pd.DataFrame] = {}
    for ticker, yahoo_sym in YAHOO_SYMBOLS.items():
        daily = load_daily_stock(ticker, yahoo_sym)
        if daily is not None:
            daily_cache[ticker] = daily
            print(f"  {ticker}: {len(daily)} daily rows")

    print(f"\nFetching 5-min intraday from Twelve Data ...")
    total_filled = 0
    for ticker, td_sym in TD_SYMBOLS.items():
        cache_path = CACHE_DIR / f"{ticker}_5min.parquet"

        if cache_path.exists():
            td_df = pd.read_parquet(cache_path)
            print(f"  {ticker}: loaded {len(td_df)} bars from cache ({cache_path.name})")
        else:
            print(f"  {ticker} (Twelve Data symbol: {td_sym})")
            td_df = fetch_td_5min(ticker, td_sym)
            if td_df is None:
                print(f"    SKIP — no data returned for {td_sym}")
                continue
            td_df.to_parquet(cache_path)
            print(f"    cached {len(td_df)} bars → {cache_path.name}")
            # Pause between tickers to respect free-tier rate limit
            time.sleep(TD_SLEEP_SEC)

        daily = daily_cache.get(ticker)
        if daily is None:
            print(f"    SKIP — no daily data for {ticker}")
            continue

        df_csv, n_filled = backfill_gfr(df_csv, ticker, td_df, daily)
        print(f"    filled {n_filled:,} GFR values for {ticker}")
        total_filled += n_filled

    null_after = int(df_csv["gfr"].isna().sum())
    print(f"\nBackfill complete.")
    print(f"  Before: {null_before:,} null  →  After: {null_after:,} null")
    print(f"  Filled: {total_filled:,} rows  ({total_filled/len(df_csv)*100:.1f}% of dataset)")

    if total_filled > 0:
        df_csv.to_csv(CSV_PATH, index=False)
        print(f"  Saved → {CSV_PATH}")
        print("\nNext steps:")
        print("  python tools/calibrate_exit_model.py")
        print("  python tools/train_settlement_model.py")
    else:
        print("  Nothing filled — CSV not modified.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be fetched without making API calls")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
