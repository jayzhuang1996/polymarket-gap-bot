"""
End-of-day data collection — runs after 4pm ET market close.

Scrapes resolved Polymarket markets for today:
  1. Fetches ALL individual trades via Core API and appends to per-ticker parquet
  2. Pulls yfinance OHLC for gap calculation
  3. Stores gap+outcome observations in scraped_observations
  4. Recomputes the WR table

NYSE holiday-aware (uses `holidays` package) — skips weekends and market holidays.

Usage:
  python tools/eod_update.py                          # Today only
  python tools/eod_update.py --date 2026-05-21        # Specific date
  python tools/eod_update.py --days 5                 # Last N days
  python tools/eod_update.py --backfill-trades 30     # Backfill trade data for last 30 days
"""

import argparse
import sys
import time
from datetime import date, timedelta, datetime as dt, timezone
from pathlib import Path

import pandas as pd
import requests
from holidays import NYSE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import init_db
from database.wr_store import daily_update, update_stock_priors

# ── Constants ──────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CORE_API = "https://data-api.polymarket.com"

TICKERS = [
    ("SPX", "^GSPC"), ("NVDA", "NVDA"), ("TSLA", "TSLA"),
    ("AAPL", "AAPL"), ("AMZN", "AMZN"), ("GOOGL", "GOOGL"),
    ("META", "META"), ("MSFT", "MSFT"), ("NFLX", "NFLX"),
]

# ── Holiday Detection ──────────────────────────────────────────────────────────

# Cache NYSE calendar per year to avoid repeated construction in backfill loops.
_HOLIDAY_CACHE: dict[int, NYSE] = {}


def _nyse_holidays(year: int) -> NYSE:
    if year not in _HOLIDAY_CACHE:
        _HOLIDAY_CACHE[year] = NYSE(years=year)
    return _HOLIDAY_CACHE[year]


def is_market_closed(d: date) -> tuple[bool, str]:
    """Check if markets are closed on this date.

    Returns (is_closed, reason).
    """
    if d.weekday() >= 5:
        return True, "weekend"
    try:
        holidays_obj = _nyse_holidays(d.year)
        if d in holidays_obj:
            name = holidays_obj.get(d) or "market holiday"
            return True, str(name)
    except Exception:
        pass
    return False, "trading day"


def _et_now() -> dt:
    """Current datetime in ET (naive). US Eastern = UTC-4 (EDT)."""
    return dt.now(timezone.utc) + timedelta(hours=-4)


def should_run(d: date) -> tuple[bool, str]:
    """Check if we should scrape this date. Considers both market closure
    and time-of-day (must be past 4pm ET for today's markets to be resolved)."""
    closed, reason = is_market_closed(d)
    if closed:
        return False, reason
    today = date.today()
    if d == today:
        et = _et_now()
        if et.hour < 16:
            return False, f"market still open ({et.hour}:{et.minute:02d} ET)"
    return True, "ok"


# ── Trade Scraping ─────────────────────────────────────────────────────────────

PARQUET_COLUMNS = ["condition_id", "timestamp", "price", "usd_amount", "maker_direction"]


def fetch_all_trades(condition_id: str, max_pages: int = 100) -> pd.DataFrame:
    """Fetch every trade for a market via the Polymarket Core API.

    Paginates through the /trades endpoint until an empty page or max_pages.
    Returns a DataFrame with the standard 5-column format, or empty DataFrame
    on failure.

    Rate limit: 300ms between pages (generous — Core API has no documented
    rate limit but we don't want to hammer it).
    """
    rows = []
    offset = 0
    limit = 10000

    for _ in range(max_pages):
        try:
            resp = requests.get(
                f"{CORE_API}/trades",
                params={"market": condition_id, "limit": limit, "offset": offset},
                timeout=30,
            )
        except requests.RequestException:
            break  # network error — take what we got

        if resp.status_code != 200:
            break

        page = resp.json()
        if not page or not isinstance(page, list):
            break

        for t in page:
            # Core API field → parquet column mapping
            rows.append({
                "condition_id":   t.get("conditionId", condition_id),
                "timestamp":      int(t.get("timestamp", 0)),
                "price":          float(t.get("price", 0)),
                "usd_amount":     float(t.get("size", 0)),
                "maker_direction": str(t.get("side", "")),
            })

        if len(page) < limit:
            break  # last page
        offset += limit
        time.sleep(0.3)

    return pd.DataFrame(rows, columns=PARQUET_COLUMNS) if rows else pd.DataFrame(columns=PARQUET_COLUMNS)


def _parquet_path(ticker: str) -> Path:
    """Per-ticker parquet file path. SPX trades are in spx_trades.parquet, etc."""
    fname = "spx_trades" if ticker.upper() == "SPX" else f"{ticker.lower()}_trades"
    return DATA_DIR / f"{fname}.parquet"


def append_trades_to_parquet(ticker: str, new_trades: pd.DataFrame) -> int:
    """Append new trades to the per-ticker parquet, deduplicating on
    (condition_id, timestamp, price, usd_amount).

    Returns the number of genuinely new trades appended.
    """
    if new_trades.empty:
        return 0

    path = _parquet_path(ticker)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Dedupe key: (condition_id, timestamp, price, amount) —
    # a trade is uniquely identified by these four fields.
    dedupe_keys = ["condition_id", "timestamp", "price", "usd_amount"]

    if path.exists():
        existing = pd.read_parquet(path)
        # Only count genuinely new trades — ones whose (cid, ts, price, amount)
        # tuple is not already present in the existing file.
        existing_keys = existing[dedupe_keys].drop_duplicates()
        merged = new_trades.merge(
            existing_keys, on=dedupe_keys, how="left", indicator=True,
        )
        genuinely_new = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
        genuinely_new = genuinely_new.drop_duplicates(subset=dedupe_keys)

        if genuinely_new.empty:
            return 0

        combined = pd.concat([existing, genuinely_new], ignore_index=True)
        combined.to_parquet(path, index=False)
        return len(genuinely_new)
    else:
        new_trades.drop_duplicates(subset=dedupe_keys, keep="first", inplace=True)
        new_trades.to_parquet(path, index=False)
        return len(new_trades)


# ── Observation Storage ────────────────────────────────────────────────────────

def _ensure_obs_table():
    """Create scraped_observations table if it doesn't exist."""
    from database.db import _conn
    c = _conn()
    try:
        c.execute("""
            CREATE TABLE IF NOT EXISTS scraped_observations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT    NOT NULL,
                ticker      TEXT    NOT NULL,
                gap_pct     REAL    NOT NULL,
                close_up    INTEGER NOT NULL,
                created_at  TEXT    NOT NULL,
                UNIQUE(date, ticker)
            );
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_ticker ON scraped_observations(ticker);
        """)
        c.commit()
    finally:
        c.close()


def store_observation(d: date, display_name: str, gap_pct: float, close_up: bool):
    """Store a single gap+outcome observation."""
    _ensure_obs_table()
    from database.db import _conn
    c = _conn()
    try:
        c.execute("""
            INSERT INTO scraped_observations
                (date, ticker, gap_pct, close_up, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (date, ticker) DO NOTHING
        """, (
            d.isoformat(), display_name, gap_pct,
            1 if close_up else 0,
            dt.now(timezone.utc).isoformat(),
        ))
        c.commit()
    except Exception:
        pass
    finally:
        c.close()


# ── Core Logic ─────────────────────────────────────────────────────────────────

def eod_update(target_date: date | None = None, skip_trades: bool = False) -> dict:
    """Run end-of-day data collection for a single date.

    Args:
        target_date: Date to scrape. Defaults to today.
        skip_trades: If True, skip trade scraping (only store gap observation).

    Returns:
        Dict with counts: {trades_scraped, observations_stored, errors}
    """
    d = target_date or date.today()
    result = {"trades_scraped": 0, "observations_stored": 0, "errors": 0}

    should, reason = should_run(d)
    if not should:
        print(f"  {d}: SKIP ({reason})")
        return result

    print(f"  {d}: scraping {len(TICKERS)} tickers...")

    for display_name, yahoo_ticker in TICKERS:
        try:
            # ── 1. Find resolved market ──
            from tools.scrape_history import find_resolved_market, get_yfinance_data, slug_for

            slug = slug_for(display_name, yahoo_ticker, d)
            market = find_resolved_market(slug)
            if not market:
                print(f"    {display_name:6s}: no resolved market")
                continue

            # ── 2. Get yfinance data ──
            yd = get_yfinance_data(yahoo_ticker, d)
            if not yd:
                print(f"    {display_name:6s}: no yfinance data")
                result["errors"] += 1
                continue

            # ── 3. Fetch ALL trades (full day's activity) ──
            if not skip_trades and market.get("condition_id"):
                new_trades = fetch_all_trades(market["condition_id"])
                if not new_trades.empty:
                    appended = append_trades_to_parquet(display_name, new_trades)
                    result["trades_scraped"] += appended
                    trade_note = f" (+{appended} trades)" if appended > 0 else ""
                else:
                    trade_note = " (0 trades)"
            else:
                trade_note = ""

            # ── 4. Store gap+outcome observation ──
            outcome_str = "UP" if market["outcome"] == "YES" else "DOWN"
            gap_label = f"{yd['gap_pct']*10000:+.0f} bps"
            match = "✓" if (market["outcome"] == "YES") == yd["close_up"] else "✗"
            print(f"    {display_name:6s}: gap={gap_label}, close={outcome_str} {match}{trade_note}")

            store_observation(d, display_name, yd["gap_pct"], yd["close_up"])
            result["observations_stored"] += 1
            time.sleep(0.3)

        except Exception as e:
            print(f"    {display_name:6s}: ERROR — {e}")
            result["errors"] += 1

    # ── 5. Update WR table ──
    if result["observations_stored"] > 0:
        updated = daily_update()
        print(f"  {d}: {result['observations_stored']} observations stored, "
              f"{result['trades_scraped']} trades scraped, WR updated ({updated} entries)")
    else:
        print(f"  {d}: no new observations")

    # ── 6. Monthly: refresh 5-year stock priors (first trading day of each month) ──
    if d.day <= 3:
        # Could be the first trading day — check if any earlier day this month was a trading day
        earlier_trading_day = any(
            not is_market_closed(d.replace(day=day))[0]
            for day in range(1, d.day)
        )
        if not earlier_trading_day:
            print(f"  {d}: first trading day of month — appending new stock observations...")
            update_stock_priors()

    return result


def main():
    parser = argparse.ArgumentParser(
        description="End-of-day data collection — scrape trades + outcomes + update WR",
    )
    parser.add_argument("--date", type=str, default=None, help="Specific date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=None, help="Last N days to backfill")
    parser.add_argument("--backfill-trades", type=int, default=None, metavar="N",
                        help="Backfill trade data for last N days (skips gap obs, trades only)")
    args = parser.parse_args()

    init_db()  # establishes DB connection; sets _pg_available=False on pooler failure
    print(f"[{dt.now(timezone.utc).isoformat()}] EOD Update")
    print()

    if args.backfill_trades:
        total_trades = 0
        today = date.today()
        for i in range(args.backfill_trades):
            d = today - timedelta(days=i)
            closed, reason = is_market_closed(d)
            if closed:
                print(f"  {d}: SKIP ({reason})")
                continue
            print(f"  {d}: backfilling trades...")
            for display_name, yahoo_ticker in TICKERS:
                from tools.scrape_history import find_resolved_market, slug_for
                slug = slug_for(display_name, yahoo_ticker, d)
                market = find_resolved_market(slug)
                if not market or not market.get("condition_id"):
                    continue
                new_trades = fetch_all_trades(market["condition_id"])
                if not new_trades.empty:
                    n = append_trades_to_parquet(display_name, new_trades)
                    total_trades += n
                    if n > 0:
                        print(f"    {display_name:6s}: +{n} trades")
                time.sleep(0.3)
        print(f"\nTotal: {total_trades} new trades across {args.backfill_trades} days")

    elif args.date:
        target = dt.strptime(args.date, "%Y-%m-%d").date()
        eod_update(target)
    elif args.days:
        total_obs = 0
        total_trades = 0
        for i in range(args.days):
            d = date.today() - timedelta(days=i)
            r = eod_update(d)
            total_obs += r["observations_stored"]
            total_trades += r["trades_scraped"]
        print(f"\nTotal: {total_obs} observations, {total_trades} trades across {args.days} days")
    else:
        eod_update()


if __name__ == "__main__":
    main()
