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


# ── Supabase Sync ──────────────────────────────────────────────────────────────

def _sync_sqlite_to_supabase(d: date) -> None:
    """Push today's SQLite rows to Supabase as a best-effort EOD mirror.

    Safe to call even when Supabase is unavailable — any failure is logged
    and silently swallowed so the rest of eod_update continues.

    Tables synced: scan_log, decisions, outcomes.
    Uses INSERT ... ON CONFLICT DO NOTHING so re-runs are idempotent.
    Only runs when DATABASE_URL is set AND SQLite is the current backend
    (i.e. _pg_available is False, meaning we wrote to SQLite during the day).
    """
    import os
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return  # no Supabase configured

    from database.db import _pg_available, get_scan_log, get_decisions_by_date, get_outcomes_for_date
    if _pg_available:
        return  # already writing to Supabase directly — nothing to sync

    date_str = d.isoformat()
    scan      = get_scan_log(date_str)
    decisions = get_decisions_by_date(date_str)
    outcomes  = get_outcomes_for_date(date_str)

    if not scan and not decisions and not outcomes:
        return  # nothing to sync

    try:
        import psycopg2
        if "sslmode" not in db_url:
            db_url = db_url + ("&" if "?" in db_url else "?") + "sslmode=require"
        pg = psycopg2.connect(db_url)
        cur = pg.cursor()

        # scan_log — idempotent upsert on (date, ticker, scanned_at)
        for row in scan:
            cur.execute("""
                INSERT INTO scan_log
                    (date, scanned_at, ticker, et_time, gap_bps, yes_ask, yes_bid,
                     adj_wr, edge, gfr, gfr_velocity, settlement_p_win, signal, vix_change)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (
                row["date"], row["scanned_at"], row["ticker"], row.get("et_time"),
                row.get("gap_bps"), row.get("yes_ask"), row.get("yes_bid"),
                row.get("adj_wr"), row.get("edge"), row.get("gfr"),
                row.get("gfr_velocity"), row.get("settlement_p_win"),
                row.get("signal"), row.get("vix_change"),
            ))

        # decisions — idempotent on (date, ticker, created_at)
        for row in decisions:
            cur.execute("""
                INSERT INTO decisions
                    (date, ticker, slug, gap_bps, yes_bid, yes_ask, spread_bps,
                     entry_side, entry_price, position_size, decision,
                     expected_edge, book_depth, adj_wr, gfr_at_entry,
                     spread_at_entry, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (
                row["date"], row["ticker"], row.get("slug"),
                row.get("gap_bps"), row.get("yes_bid"), row.get("yes_ask"),
                row.get("spread_bps"), row.get("entry_side"), row.get("entry_price"),
                row.get("position_size"), row["decision"], row.get("expected_edge"),
                row.get("book_depth"), row.get("adj_wr"), row.get("gfr_at_entry"),
                row.get("spread_at_entry"), row["created_at"],
            ))

        # outcomes
        for row in outcomes:
            cur.execute("""
                INSERT INTO outcomes
                    (decision_id, date, ticker, resolved_yes, pnl_usd,
                     closed_at, exit_price, exit_type)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (
                row["decision_id"], row["date"], row["ticker"],
                row.get("resolved_yes"), row.get("pnl_usd"),
                row.get("closed_at"), row.get("exit_price"),
                row.get("exit_type", "resolve"),
            ))

        pg.commit()
        cur.close()
        pg.close()
        print(f"  Supabase sync: {len(scan)} scan rows, "
              f"{len(decisions)} decisions, {len(outcomes)} outcomes")
    except Exception as e:
        print(f"  Supabase sync skipped ({e})")


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

    # ── 5b. Sync today's SQLite rows → Supabase (best-effort mirror) ──────────
    _sync_sqlite_to_supabase(d)

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
