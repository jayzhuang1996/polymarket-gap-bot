"""
Historical data pipeline — scrapes closed Polymarket daily stock markets via Gamma API.

For each ticker × date:
  1. Try to find the daily market via Gamma slug search
  2. Get gap from yfinance OHLC
  3. Get outcome (close direction) from yfinance
  4. If market exists and resolved, store in our WR table

Usage:
  python tools/scrape_history.py             # Backfill Oct 15 2025 → yesterday
  python tools/scrape_history.py --days 5    # Last 5 days
  python tools/scrape_history.py --date 2026-05-15  # Single date

Note: For bulk historical backfill, prefer tools/backfill_from_parquet.py which
reads from the HuggingFace parquet dump (no API rate limiting).
"""

import argparse
import sys
import json
import time
from datetime import date, timedelta, datetime as dt, timezone

import requests
import yfinance as yf

from database.db import _conn
from database.wr_store import daily_update

GAMMA_API = "https://gamma-api.polymarket.com"

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

SLUG_OVERRIDES = {"^GSPC": "spx"}

TICKERS = [
    ("SPX", "^GSPC"), ("NVDA", "NVDA"), ("TSLA", "TSLA"),
    ("AAPL", "AAPL"), ("AMZN", "AMZN"), ("GOOGL", "GOOGL"),
    ("META", "META"), ("MSFT", "MSFT"), ("NFLX", "NFLX"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────


def slug_for(display_name: str, yahoo_ticker: str, d: date) -> str:
    prefix = SLUG_OVERRIDES.get(yahoo_ticker, yahoo_ticker.lower())
    return f"{prefix}-up-or-down-on-{MONTH_NAMES[d.month - 1]}-{d.day}-{d.year}"


def find_resolved_market(slug: str) -> dict | None:
    """Try to find a resolved market via Gamma slug search."""
    try:
        resp = requests.get(f"{GAMMA_API}/events?slug={slug}", timeout=15)
        if resp.status_code != 200:
            return None
        events = resp.json()
        if not events:
            return None
        markets = events[0].get("markets", [])
        if not markets:
            return None
        mk = markets[0]
        # Resolved outcome → use outcomePrices ([1, 0] = YES won, [0, 1] = NO won)
        outcome = mk.get("outcome")
        if outcome is None:
            raw_prices = mk.get("outcomePrices")
            if raw_prices:
                prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
                if isinstance(prices, list) and len(prices) >= 2:
                    yes_p = float(prices[0]) if prices[0] else 0
                    no_p = float(prices[1]) if len(prices) > 1 and prices[1] else 0
                    if yes_p > 0.5 or no_p > 0.5:  # at least one resolved
                        outcome = "YES" if yes_p > 0.5 else "NO"
        if outcome is None:
            return None  # not resolved yet

        raw = mk.get("clobTokenIds") or "[]"
        ids = json.loads(raw) if isinstance(raw, str) else (raw or [])

        return {
            "slug": slug,
            "question": mk.get("question", ""),
            "outcome": outcome,
            "yes_token": str(ids[0]) if len(ids) > 0 else None,
            "no_token": str(ids[1]) if len(ids) > 1 else None,
            "condition_id": mk.get("conditionId", ""),
        }
    except (requests.RequestException, json.JSONDecodeError):
        return None


def get_yfinance_data(yahoo_ticker: str, d: date) -> dict | None:
    """Get OHLC for a specific date and the previous trading day."""
    try:
        stock = yf.Ticker(yahoo_ticker)
        # Get extra days to ensure we have the previous trading day
        hist = stock.history(start=d - timedelta(days=10), end=d + timedelta(days=1))
        if hist.empty or len(hist) < 2:
            return None

        # The last bar should be date d (if it was a trading day)
        today_bar = hist.iloc[-1]
        today_date = today_bar.name.date() if hasattr(today_bar.name, 'date') else today_bar.name

        if today_date != d:
            # The requested date might not be a trading day
            return None

        prev_bar = hist.iloc[-2]
        prev_close = float(prev_bar["Close"])
        today_open = float(today_bar["Open"])
        today_close = float(today_bar["Close"])

        if prev_close == 0 or today_open == 0:
            return None

        gap_pct = (today_open - prev_close) / prev_close
        close_up = today_close > prev_close

        return {
            "open": today_open,
            "close": today_close,
            "prev_close": prev_close,
            "gap_pct": gap_pct,
            "close_up": close_up,
        }
    except Exception:
        return None


# ── Store ─────────────────────────────────────────────────────────────────────


def _ensure_obs_table():
    """Create scraped_observations table for storing gap+outcome pairs."""
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scraped_observations (
                id          INTEGER PRIMARY KEY,
                date        TEXT    NOT NULL,
                ticker      TEXT    NOT NULL,
                gap_pct     REAL    NOT NULL,
                close_up    INTEGER NOT NULL,
                created_at  TEXT    NOT NULL,
                UNIQUE(date, ticker)
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_ticker ON scraped_observations(ticker);
        """)
        conn.commit()
    finally:
        conn.close()


def store_observation(d: date, display_name: str, gap_pct: float, close_up: bool):
    """Store a single gap+outcome observation."""
    _ensure_obs_table()
    conn = _conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO scraped_observations
                (date, ticker, gap_pct, close_up, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            d.isoformat(), display_name, gap_pct,
            1 if close_up else 0,
            dt.now(timezone.utc).isoformat(),
        ))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ── Main ──────────────────────────────────────────────────────────────────────


def scrape_date(d: date):
    """Scrape one date for all tickers."""
    weekday = d.weekday()
    if weekday >= 5:
        print(f"  {d}: weekend, skipping")
        return 0

    found = 0
    for display_name, yahoo_ticker in TICKERS:
        slug = slug_for(display_name, yahoo_ticker, d)

        # Check if market exists
        market = find_resolved_market(slug)
        if not market:
            continue

        # Get yfinance data
        yd = get_yfinance_data(yahoo_ticker, d)
        if not yd:
            continue

        outcome_str = "UP" if market["outcome"] == "YES" else "DOWN"
        gap_label = f"{yd['gap_pct']*10000:+.0f} bps"
        match = "✓" if (market["outcome"] == "YES") == yd["close_up"] else "✗"
        print(f"  {d} {display_name:6s}: gap={gap_label}, close={outcome_str}, outcome_match={match}")

        store_observation(d, display_name, yd["gap_pct"], yd["close_up"])
        found += 1
        time.sleep(0.3)  # rate limit

    return found


def main():
    parser = argparse.ArgumentParser(description="Scrape historical Polymarket markets")
    parser.add_argument("--days", type=int, default=None, help="Number of days to backfill")
    parser.add_argument("--date", type=str, default=None, help="Single date (YYYY-MM-DD)")
    args = parser.parse_args()

    # Default: Oct 15, 2025 (when Polymarket started listing daily stock markets) → yesterday
    start = date(2025, 10, 15)
    end = date.today() - timedelta(days=1)

    if args.date:
        start = dt.strptime(args.date, "%Y-%m-%d").date()
        end = start
    elif args.days:
        start = date.today() - timedelta(days=args.days)
        end = date.today() - timedelta(days=1)

    total_found = 0
    current = start

    print(f"Scraping {start} → {end} ({TICKERS} tickers)")
    print()

    while current <= end:
        found = scrape_date(current)
        total_found += found
        current += timedelta(days=1)

    print(f"\nDone. {total_found} observations found across {(end - start).days + 1} days.")

    # Recompute WR table from outcomes + scraped data
    if total_found > 0:
        updated = daily_update()
        print(f"WR table updated: {updated} entries.")


if __name__ == "__main__":
    main()
