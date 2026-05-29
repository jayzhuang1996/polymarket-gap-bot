"""
Win rate store — loads empirical per-ticker WR from DB outcomes or falls back to
hardcoded values (from HF dataset analysis).

After each resolve, daily_update() recomputes WR from the outcomes table.
The data pipeline (tools/scrape_history.py) backfills historical outcomes.
"""

import sqlite3
from datetime import datetime, date, timezone
from typing import Optional

from database.db import _conn, DB_PATH

# ── Hardcoded defaults — 5-year daily OHLC (May 2020 – May 2025, ~1,255 days) ──
# Source: tools pulled via yfinance on May 24 2026. Per-ticker gap threshold
# applied (TICKER_GAP_THRESHOLD). n = 65–413 gap events per ticker/direction.
# Replaced prior Polymarket-only estimates (Oct 2025–May 2026, ~220 days) which
# significantly underestimated gap_up WR for AAPL, MSFT, META, GOOGL, NFLX.
#
# gap_up = True  → WR that stock closes UP (buy YES edge)
# gap_up = False → WR that stock closes DOWN (buy NO edge)
HARDCODED_WR: dict[tuple[str, bool], float] = {
    ("SPX",   True): 0.827, ("SPX",   False): 0.856,
    ("NVDA",  True): 0.785, ("NVDA",  False): 0.731,
    ("TSLA",  True): 0.779, ("TSLA",  False): 0.761,
    ("AAPL",  True): 0.816, ("AAPL",  False): 0.747,
    ("AMZN",  True): 0.786, ("AMZN",  False): 0.781,
    ("GOOGL", True): 0.776, ("GOOGL", False): 0.777,
    ("META",  True): 0.774, ("META",  False): 0.719,
    ("MSFT",  True): 0.726, ("MSFT",  False): 0.780,
    ("NFLX",  True): 0.833, ("NFLX",  False): 0.831,
}

MIN_OBS_FOR_DB_WR = 30  # minimum observations before DB value is considered at all
MIN_OBS_BUCKET    = 15  # lower threshold for gap-bucket rows (smaller per-bucket n)
PRIOR_WEIGHT = 50       # raised from 20 → 50 to reflect 200–400 obs backing each prior

GAP_BUCKET_THRESHOLDS = (0.005, 0.015)  # <0.5% = small, 0.5–1.5% = medium, >1.5% = large


def _gap_bucket(gap_pct: float) -> str:
    abs_gap = abs(gap_pct)
    if abs_gap < GAP_BUCKET_THRESHOLDS[0]:
        return "small"
    if abs_gap < GAP_BUCKET_THRESHOLDS[1]:
        return "medium"
    return "large"

# ── Prior isolation ────────────────────────────────────────────────────────────
# The prior-building period ends Jan 31 2026. Only data before this date is
# used to compute the baseline WR stored in the `priors` table.
# Data from Feb 2026 onward is used only for live Bayesian updating.
# This prevents the prior from being contaminated by the same data we trade on.
PRIOR_PERIOD_END = date(2026, 2, 1)  # exclusive upper bound


# ── Schema ────────────────────────────────────────────────────────────────────


def _ensure_wr_table():
    """Create daily_wr table if it doesn't exist (stores per-date WR snapshots)."""
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_wr (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker       TEXT    NOT NULL,
                direction    TEXT    NOT NULL,  -- 'gap_up' or 'gap_down'
                gap_bucket   TEXT    NOT NULL DEFAULT 'all',  -- 'all' | 'small' | 'medium' | 'large'
                win_rate     REAL    NOT NULL,
                observations INTEGER NOT NULL,
                source       TEXT    NOT NULL DEFAULT 'computed',
                updated_at   TEXT    NOT NULL
            );
        """)
        # Migration: add gap_bucket column to existing tables that predate this schema
        cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_wr)").fetchall()]
        if "gap_bucket" not in cols:
            conn.execute("ALTER TABLE daily_wr ADD COLUMN gap_bucket TEXT NOT NULL DEFAULT 'all'")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_daily_wr_ticker_bucket
            ON daily_wr(ticker, direction, gap_bucket);
        """)
        conn.commit()
    finally:
        conn.close()


def _ensure_priors_table():
    """Create isolated priors table (WR from PRIOR_PERIOD_END data only)."""
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS isolated_priors (
                ticker      TEXT NOT NULL,
                direction   TEXT NOT NULL,
                win_rate    REAL NOT NULL,
                observations INTEGER NOT NULL,
                built_at    TEXT NOT NULL,
                PRIMARY KEY (ticker, direction)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def _ensure_stock_obs_table():
    """Create stock_daily_obs table — stores individual gap days from yfinance.

    Separate from scraped_observations (which is Polymarket-specific).
    This table accumulates forever; WR is recomputed from it each month.
    """
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily_obs (
                ticker    TEXT NOT NULL,
                date      TEXT NOT NULL,
                gap_pct   REAL NOT NULL,
                close_up  INTEGER NOT NULL,
                PRIMARY KEY (ticker, date)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def _last_stock_obs_date(ticker: str) -> str | None:
    """Return the most recent date stored for this ticker, or None."""
    _ensure_stock_obs_table()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT MAX(date) AS d FROM stock_daily_obs WHERE ticker = ?", (ticker,)
        ).fetchone()
        return row["d"] if row else None
    finally:
        conn.close()


def _append_stock_obs(ticker: str, bars) -> int:
    """Insert new rows into stock_daily_obs. Returns count inserted."""
    _ensure_stock_obs_table()
    inserted = 0
    conn = _conn()
    try:
        for _, row in bars.iterrows():
            try:
                conn.execute(
                    "INSERT INTO stock_daily_obs (ticker, date, gap_pct, close_up) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                    (ticker, str(row["date"]), float(row["gap_pct"]), int(row["close_up"])),
                )
                inserted += 1
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
    return inserted


def _recompute_priors_from_obs() -> int:
    """Recompute isolated_priors WR from full stock_daily_obs table.

    Called after appending new observations. Recalculates WR for every
    (ticker, direction) pair from the complete accumulated history.
    """
    _ensure_priors_table()
    _ensure_stock_obs_table()
    from config import TICKER_GAP_THRESHOLD

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    stored = 0

    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT ticker, date, gap_pct, close_up FROM stock_daily_obs"
        ).fetchall()
    finally:
        conn.close()

    import pandas as pd
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return 0

    for ticker, grp in df.groupby("ticker"):
        thresh = TICKER_GAP_THRESHOLD.get(ticker, 0.005)
        for gap_up, direction in [(True, "gap_up"), (False, "gap_down")]:
            if gap_up:
                sub  = grp[grp["gap_pct"] >= thresh]
                wins = sub["close_up"].sum()
            else:
                sub  = grp[grp["gap_pct"] <= -thresh]
                wins = (sub["close_up"] == 0).sum()
            n = len(sub)
            if n < 30:
                continue
            wr = round(int(wins) / n, 4)
            conn = _conn()
            try:
                conn.execute("""
                    INSERT INTO isolated_priors (ticker, direction, win_rate, observations, built_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, direction) DO UPDATE SET
                        win_rate=excluded.win_rate,
                        observations=excluded.observations,
                        built_at=excluded.built_at
                """, (ticker, direction, wr, n, now))
                conn.commit()
            finally:
                conn.close()
            stored += 1

    return stored


def update_stock_priors() -> int:
    """Incrementally append new daily stock observations and refresh isolated_priors.

    Called monthly by eod_update.py. Only fetches data after the last stored
    date per ticker — never re-downloads history that's already in the DB.

    On first run (empty table): seeds from 5-year history.
    On subsequent runs: fetches only the new month's trading days.

    Returns number of (ticker, direction) priors updated.
    """
    _ensure_stock_obs_table()
    _ensure_priors_table()

    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        print("  update_stock_priors: yfinance not available — skipping")
        return 0

    from config import TICKERS

    total_new = 0
    for display, yahoo in TICKERS:
        try:
            last_date = _last_stock_obs_date(display)

            if last_date is None:
                # First run — seed from 5 years
                bars = yf.Ticker(yahoo).history(period="5y", interval="1d", auto_adjust=True)
                fetch_note = "seeding 5yr"
            else:
                # Incremental — only fetch days after last stored date
                import datetime
                start = (datetime.date.fromisoformat(last_date) +
                         datetime.timedelta(days=1)).isoformat()
                bars = yf.Ticker(yahoo).history(
                    start=start, interval="1d", auto_adjust=True
                )
                fetch_note = f"appending from {start}"

            if bars.empty:
                continue

            bars = bars.reset_index()
            bars["date"]       = pd.to_datetime(bars["Date"]).dt.date
            bars["prev_close"] = bars["Close"].shift(1)
            bars["gap_pct"]    = (bars["Open"] - bars["prev_close"]) / bars["prev_close"]
            bars["close_up"]   = (bars["Close"] > bars["prev_close"]).astype(int)
            bars = bars.dropna(subset=["gap_pct"])

            n = _append_stock_obs(display, bars)
            total_new += n
            if n > 0:
                print(f"  update_stock_priors: {display} +{n} days ({fetch_note})")

        except Exception as e:
            print(f"  update_stock_priors: {display} error — {e}")

    # Recompute WR from full accumulated history
    updated = _recompute_priors_from_obs()
    print(f"  update_stock_priors: {total_new} new obs added, {updated} priors recomputed")
    return updated


def rebuild_priors():
    """Recompute baseline WR from scraped_observations WHERE date < PRIOR_PERIOD_END.

    This produces a truly independent prior — untouched by data the strategy
    has been trading on. Call once after a full historical scrape, or whenever
    PRIOR_PERIOD_END is updated.

    Stores results in `isolated_priors` table. load_base_wr() will use these
    values instead of HARDCODED_WR when available.
    """
    _ensure_priors_table()
    cutoff = PRIOR_PERIOD_END.isoformat()
    now = datetime.now(timezone.utc).isoformat()

    conn = _conn()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(scraped_observations)").fetchall()]
        if "date" not in cols:
            print("  rebuild_priors: scraped_observations has no 'date' column — skipping.")
            return 0

        rows = conn.execute("""
            SELECT
                ticker,
                CASE WHEN gap_pct > 0 THEN 'gap_up' ELSE 'gap_down' END AS direction,
                COUNT(*) AS obs,
                SUM(CASE WHEN (gap_pct > 0 AND close_up = 1)
                             OR (gap_pct < 0 AND close_up = 0) THEN 1 ELSE 0 END) AS wins
            FROM scraped_observations
            WHERE date < ?
            GROUP BY ticker, direction
        """, (cutoff,)).fetchall()
    finally:
        conn.close()

    stored = 0
    for r in rows:
        obs, wins = r["obs"], r["wins"] or 0
        if obs < MIN_OBS_FOR_DB_WR:
            continue
        wr = round(wins / obs, 4)
        conn = _conn()
        try:
            conn.execute("""
                INSERT INTO isolated_priors (ticker, direction, win_rate, observations, built_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker, direction) DO UPDATE SET
                    win_rate=excluded.win_rate,
                    observations=excluded.observations,
                    built_at=excluded.built_at
            """, (r["ticker"], r["direction"], wr, obs, now))
            conn.commit()
        finally:
            conn.close()
        stored += 1

    print(f"  rebuild_priors: stored {stored} isolated priors (cutoff: {cutoff})")
    return stored


# ── Load WR ───────────────────────────────────────────────────────────────────


def load_base_wr(
    ticker: str,
    gap_up: bool,
    gap_pct: float | None = None,
    require_obs: int = MIN_OBS_FOR_DB_WR,
) -> tuple[float, float, int]:
    """Return (yes_wr, no_wr, effective_obs) using a Bayesian blend of prior + observed data.

    When gap_pct is provided, attempts a bucket-specific WR lookup first (small/medium/large).
    Falls back to the flat 'all' rate if the bucket has fewer than MIN_OBS_BUCKET observations.

    Prior source (in order of preference):
      1. isolated_priors table — built from data before PRIOR_PERIOD_END only.
      2. HARDCODED_WR — fallback (full dataset, not truly independent).

    Bayesian blend: blended = (prior_wr × PRIOR_WEIGHT + obs_wr × obs) / (PRIOR_WEIGHT + obs)
    """
    _ensure_wr_table()
    _ensure_priors_table()
    direction = "gap_up" if gap_up else "gap_down"

    # 1. Prior (independent period or hardcoded fallback)
    conn = _conn()
    try:
        prior_row = conn.execute(
            "SELECT win_rate FROM isolated_priors WHERE ticker = ? AND direction = ?",
            (ticker, direction),
        ).fetchone()
    finally:
        conn.close()

    prior_wr = prior_row["win_rate"] if prior_row else HARDCODED_WR.get((ticker, gap_up), 0.60)

    # 2. Observed WR: try bucket-specific row first, fall back to flat 'all'
    obs_row = None
    obs_min  = require_obs  # threshold that applies to obs_row
    if gap_pct is not None:
        bucket = _gap_bucket(gap_pct)
        conn = _conn()
        try:
            obs_row = conn.execute(
                "SELECT win_rate, observations FROM daily_wr"
                " WHERE ticker = ? AND direction = ? AND gap_bucket = ?"
                " ORDER BY updated_at DESC LIMIT 1",
                (ticker, direction, bucket),
            ).fetchone()
        finally:
            conn.close()
        if obs_row and obs_row["observations"] >= MIN_OBS_BUCKET:
            obs_min = MIN_OBS_BUCKET  # bucket row — lower threshold applies
        else:
            obs_row = None  # not enough data — fall through to flat

    if obs_row is None:
        conn = _conn()
        try:
            obs_row = conn.execute(
                "SELECT win_rate, observations FROM daily_wr"
                " WHERE ticker = ? AND direction = ? AND gap_bucket = 'all'"
                " ORDER BY updated_at DESC LIMIT 1",
                (ticker, direction),
            ).fetchone()
        finally:
            conn.close()
        obs_min = require_obs  # flat row — original threshold

    if obs_row and obs_row["observations"] >= obs_min:
        obs_wr    = obs_row["win_rate"]
        obs_count = obs_row["observations"]
        blended   = (prior_wr * PRIOR_WEIGHT + obs_wr * obs_count) / (PRIOR_WEIGHT + obs_count)
        effective_obs = PRIOR_WEIGHT + obs_count
    else:
        blended       = prior_wr
        effective_obs = PRIOR_WEIGHT

    if gap_up:
        return blended, 1.0 - blended, effective_obs
    else:
        return 1.0 - blended, blended, effective_obs


def hardcoded_yes_wr(ticker: str, gap_up: bool) -> float:
    """Direct hardcoded lookup without DB."""
    return HARDCODED_WR.get((ticker, gap_up), 0.60)


# ── Update WR from outcomes ───────────────────────────────────────────────────


def daily_update():
    """Recompute per-ticker WR from scraped_observations table only.

    Stores two kinds of rows:
      gap_bucket='all'    — flat rate across all gap sizes (existing behavior)
      gap_bucket='small'|'medium'|'large' — conditioned on gap magnitude

    Paper trade outcomes are excluded to prevent feedback-loop contamination.
    Call after each scrape run or resolve.
    """
    _ensure_wr_table()

    conn = _conn()
    try:
        flat_rows = conn.execute("""
            SELECT
                ticker,
                CASE WHEN gap_pct > 0 THEN 'gap_up' ELSE 'gap_down' END as direction,
                COUNT(*) as obs,
                SUM(CASE WHEN (gap_pct > 0 AND close_up = 1) OR (gap_pct < 0 AND close_up = 0) THEN 1 ELSE 0 END) as wins
            FROM scraped_observations
            GROUP BY ticker, direction
        """).fetchall()

        bucket_rows = conn.execute("""
            SELECT
                ticker,
                CASE WHEN gap_pct > 0 THEN 'gap_up' ELSE 'gap_down' END as direction,
                CASE
                    WHEN ABS(gap_pct) < 0.005 THEN 'small'
                    WHEN ABS(gap_pct) < 0.015 THEN 'medium'
                    ELSE 'large'
                END as gap_bucket,
                COUNT(*) as obs,
                SUM(CASE WHEN (gap_pct > 0 AND close_up = 1) OR (gap_pct < 0 AND close_up = 0) THEN 1 ELSE 0 END) as wins
            FROM scraped_observations
            GROUP BY ticker, direction, gap_bucket
        """).fetchall()
    finally:
        conn.close()

    now = datetime.now(timezone.utc).isoformat()
    stored = 0
    seen: set[tuple[str, str, str]] = set()

    def _upsert(ticker: str, direction: str, gap_bucket: str, obs: int, wins: int, min_obs: int) -> None:
        nonlocal stored
        key = (ticker, direction, gap_bucket)
        if obs < min_obs or key in seen:
            return
        seen.add(key)
        wr = round(wins / obs, 4)
        conn = _conn()
        try:
            conn.execute(
                "DELETE FROM daily_wr WHERE ticker = ? AND direction = ? AND gap_bucket = ?",
                (ticker, direction, gap_bucket),
            )
            conn.execute(
                "INSERT INTO daily_wr (ticker, direction, gap_bucket, win_rate, observations, source, updated_at)"
                " VALUES (?, ?, ?, ?, ?, 'computed', ?)",
                (ticker, direction, gap_bucket, wr, obs, now),
            )
            conn.commit()
        finally:
            conn.close()
        stored += 1

    for r in flat_rows:
        _upsert(r["ticker"], r["direction"], "all", r["obs"], r["wins"] or 0, MIN_OBS_FOR_DB_WR)

    for r in bucket_rows:
        _upsert(r["ticker"], r["direction"], r["gap_bucket"], r["obs"], r["wins"] or 0, MIN_OBS_BUCKET)

    return stored
