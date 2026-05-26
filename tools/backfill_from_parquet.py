"""
Backfill scraped_observations from data/markets.parquet (HuggingFace dump).

The parquet contains 1,222 resolved "{ticker}-up-or-down-on-{date}" markets
from Oct 2025 → May 2026.  This script:
  1. Extracts those rows and parses ticker + date from the slug
  2. Fetches gap_pct for each (ticker, date) from yfinance in batches
  3. Inserts into scraped_observations using INSERT OR IGNORE

No Gamma API calls needed — all outcome data is already in the parquet.

Usage:
    python tools/backfill_from_parquet.py            # dry-run (no DB writes)
    python tools/backfill_from_parquet.py --commit   # write to DB
    python tools/backfill_from_parquet.py --commit --ticker NVDA  # single ticker
"""

import argparse
import ast
import json
import re
import sys
import time
from datetime import date as dt_date, datetime as dt, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from database.db import _conn

PARQUET_PATH = Path(__file__).parent.parent / "data" / "markets.parquet"

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

TICKER_MAP = {
    "spx": "SPX", "nvda": "NVDA", "tsla": "TSLA", "aapl": "AAPL",
    "amzn": "AMZN", "googl": "GOOGL", "meta": "META", "msft": "MSFT", "nflx": "NFLX",
}

YAHOO_MAP = {
    "SPX": "^GSPC", "NVDA": "NVDA", "TSLA": "TSLA", "AAPL": "AAPL",
    "AMZN": "AMZN", "GOOGL": "GOOGL", "META": "META", "MSFT": "MSFT", "NFLX": "NFLX",
}

SLUG_PAT = re.compile(
    r"^(spx|nvda|tsla|aapl|amzn|googl|meta|msft|nflx)-up-or-down-on-"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"-(\d{1,2})-(\d{4})$"
)


def parse_slug(slug: str) -> tuple[str | None, dt_date | None]:
    m = SLUG_PAT.match(slug)
    if not m:
        return None, None
    raw_ticker, month_name, day, year = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
    return TICKER_MAP[raw_ticker], dt_date(year, MONTH_MAP[month_name], day)


def parse_outcome(outcome_prices) -> bool | None:
    """['1', '0'] → True (close up), ['0', '1'] → False (close down).

    outcome_prices is stored as Python repr e.g. "['1', '0']" (not JSON).
    Use ast.literal_eval to handle single-quoted strings.
    """
    try:
        if isinstance(outcome_prices, str):
            prices = ast.literal_eval(outcome_prices)
        else:
            prices = outcome_prices
        if isinstance(prices, list) and len(prices) >= 2:
            yes_p = float(prices[0])
            no_p = float(prices[1])
            if yes_p > 0.5:
                return True   # YES won = closed up
            if no_p > 0.5:
                return False  # NO won = closed down
    except (TypeError, ValueError, SyntaxError):
        pass
    return None


def load_parquet_observations(only_ticker: str | None = None) -> pd.DataFrame:
    """Return a DataFrame of (ticker, date, close_up) from the parquet."""
    df = pd.read_parquet(PARQUET_PATH)

    tickers_pat = "|".join(f"^{t}-up-or-down-on-" for t in TICKER_MAP)
    mask = df["slug"].str.match(tickers_pat, na=False) & (df["closed"] == 1)
    target = df[mask].copy()

    rows = []
    for _, row in target.iterrows():
        ticker, d = parse_slug(row["slug"])
        if ticker is None or d is None:
            continue
        if only_ticker and ticker != only_ticker:
            continue
        close_up = parse_outcome(row["outcome_prices"])
        if close_up is None:
            continue
        rows.append({"ticker": ticker, "date": d, "close_up": close_up})

    return pd.DataFrame(rows)


def fetch_gaps_for_ticker(ticker: str, dates: list[dt_date]) -> dict[dt_date, float]:
    """Bulk-fetch all gap_pct for one ticker across multiple dates via yfinance."""
    if not dates:
        return {}

    yahoo = YAHOO_MAP[ticker]
    min_date = min(dates) - timedelta(days=14)
    max_date = max(dates) + timedelta(days=2)

    try:
        stock = yf.Ticker(yahoo)
        hist = stock.history(start=min_date, end=max_date)
        if hist.empty:
            return {}
    except Exception as e:
        print(f"  [WARN] yfinance error for {ticker}: {e}")
        return {}

    # Build date → (open, prev_close) map
    hist.index = hist.index.normalize()
    closes = hist["Close"].to_dict()
    opens = hist["Open"].to_dict()

    sorted_dates = sorted(closes.keys())
    gaps: dict[dt_date, float] = {}

    for i, ts in enumerate(sorted_dates):
        d = ts.date() if hasattr(ts, "date") else ts
        if i == 0:
            continue
        prev_ts = sorted_dates[i - 1]
        prev_close = closes[prev_ts]
        today_open = opens[ts]
        if prev_close and today_open:
            gap_pct = (today_open - prev_close) / prev_close
            gaps[d] = gap_pct

    return gaps


def store_observations(rows: list[dict], commit: bool):
    """Insert rows into scraped_observations. Skips existing (INSERT OR IGNORE)."""
    if not rows:
        return 0
    conn = _conn()
    inserted = 0
    now = dt.now(timezone.utc).isoformat()
    try:
        for r in rows:
            cur = conn.execute("""
                INSERT OR IGNORE INTO scraped_observations
                    (date, ticker, gap_pct, close_up, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (r["date"].isoformat(), r["ticker"], r["gap_pct"],
                  1 if r["close_up"] else 0, now))
            inserted += cur.rowcount
        if commit:
            conn.commit()
        else:
            conn.rollback()
    finally:
        conn.close()
    return inserted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="Write to DB (default: dry-run)")
    parser.add_argument("--ticker", default=None, help="Only process one ticker (e.g. NVDA)")
    args = parser.parse_args()

    print(f"Loading parquet: {PARQUET_PATH}")
    obs_df = load_parquet_observations(only_ticker=args.ticker)
    print(f"  Parquet resolved markets: {len(obs_df)} rows")
    if obs_df.empty:
        print("Nothing to process.")
        return

    # Check what's already in DB to avoid redundant yfinance calls
    conn = _conn()
    existing = set()
    try:
        cur = conn.execute("SELECT date, ticker FROM scraped_observations")
        existing = {(r[0], r[1]) for r in cur.fetchall()}
    finally:
        conn.close()
    print(f"  Already in DB: {len(existing)} rows")

    new_obs = obs_df[~obs_df.apply(lambda r: (r["date"].isoformat(), r["ticker"]) in existing, axis=1)]
    print(f"  New rows to fetch gap for: {len(new_obs)}")

    if new_obs.empty:
        print("DB already up to date.")
        return

    # Fetch gaps per ticker (one bulk yfinance call per ticker)
    all_rows = []
    tickers_needed = new_obs["ticker"].unique()
    for ticker in sorted(tickers_needed):
        ticker_rows = new_obs[new_obs["ticker"] == ticker]
        dates = ticker_rows["date"].tolist()
        print(f"  Fetching {len(dates)} gaps for {ticker} via yfinance...")
        gaps = fetch_gaps_for_ticker(ticker, dates)

        found = 0
        for _, row in ticker_rows.iterrows():
            gap = gaps.get(row["date"])
            if gap is None:
                print(f"    [SKIP] {ticker} {row['date']}: no gap data")
                continue
            all_rows.append({
                "ticker":   ticker,
                "date":     row["date"],
                "gap_pct":  gap,
                "close_up": row["close_up"],
            })
            found += 1
        print(f"    → {found}/{len(dates)} gaps resolved")
        time.sleep(0.5)

    print(f"\nReady to insert: {len(all_rows)} observations")

    if not args.commit:
        print("\n[DRY RUN] Pass --commit to write to DB.")
        # Print sample
        for r in sorted(all_rows, key=lambda x: (x["ticker"], x["date"]))[:10]:
            direction = "UP" if r["close_up"] else "DOWN"
            print(f"  {r['date']} {r['ticker']:6s}  gap={r['gap_pct']*10000:+.0f} bps  close={direction}")
        if len(all_rows) > 10:
            print(f"  ... and {len(all_rows)-10} more")
        return

    inserted = store_observations(all_rows, commit=True)
    print(f"\nInserted {inserted} new rows into scraped_observations.")

    # Show final counts
    conn = _conn()
    try:
        cur = conn.execute("""
            SELECT ticker, COUNT(*) as n, MIN(date) as first, MAX(date) as last
            FROM scraped_observations
            GROUP BY ticker ORDER BY ticker
        """)
        print("\nFinal counts per ticker:")
        print(f"  {'Ticker':8s}  {'N':>5s}  {'First':12s}  {'Last':12s}")
        for r in cur.fetchall():
            print(f"  {r[0]:8s}  {r[1]:>5d}  {r[2]:12s}  {r[3]:12s}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
