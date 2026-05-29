"""
Database module for the Polymarket bot.

Always uses SQLite as the primary store — fast, local, no network dependency.
On Railway: SQLite lives at /data/polymarket.db (persistent volume).
Locally:    SQLite lives at data/polymarket.db.

Supabase is a read/write mirror via REST API (PostgREST). It is never the
primary store — SQLite always succeeds first, then REST fires in a background
thread. The psycopg2 / TCP path to Supabase is permanently broken for this
project (pooler returns "Tenant or user not found") and has been removed.

All DB access goes through this module.
"""

import sqlite3
import os
from datetime import date, datetime, timezone
from typing import Optional

# ── Supabase REST mirror (PostgREST — bypasses broken psycopg2/pooler path) ──
# psycopg2 path fails with "Tenant or user not found" for this project.
# PostgREST REST API works with anon key — confirmed INSERT 201 locally.
# SUPABASE_KEY env var should be set to the service_role key on Railway so it
# bypasses RLS; falls back to anon key (which also works for inserts currently).
_SUPABASE_URL = "https://dftkwvdhwkbtjxutgqzy.supabase.co"
_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRmdGt3dmRod2tidGp4dXRncXp5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3NjA4NjAsImV4cCI6MjA5NTMzNjg2MH0"
    ".d2Ey5WynBgGp3sTtKSEbHlKSd9ZhnrSIWFChykgOdcw"
)
_SUPABASE_KEY = os.getenv("SUPABASE_KEY", _ANON_KEY)

_rest_ok: bool = True                # tracks REST API reachability
_rest_last_error: str | None = None  # last REST error — exposed via /api/health

DB_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "polymarket.db"),
)




# ── Supabase REST helpers ────────────────────────────────────────────────────


def _rest_insert_sync(table: str, row: dict) -> None:
    """Synchronous POST to Supabase PostgREST — called from background thread."""
    global _rest_ok, _rest_last_error
    try:
        import requests as _req
        url = f"{_SUPABASE_URL}/rest/v1/{table}"
        headers = {
            "apikey": _SUPABASE_KEY,
            "Authorization": f"Bearer {_SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
        resp = _req.post(url, json=row, headers=headers, timeout=10)
        if resp.status_code in (200, 201):
            _rest_ok = True
            _rest_last_error = None
        else:
            _rest_ok = False
            _rest_last_error = f"REST {table} HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        _rest_ok = False
        _rest_last_error = str(e)[:200]


def _rest_insert(table: str, row: dict) -> None:
    """Fire-and-forget Supabase REST insert. Never blocks the SQLite write path."""
    import threading
    threading.Thread(target=_rest_insert_sync, args=(table, row), daemon=True).start()


# ── Connection ───────────────────────────────────────────────────────────────


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


# ── Schema ───────────────────────────────────────────────────────────────────


def init_db():
    """Create all tables and run column migrations. Safe to call on every startup."""
    conn = _conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS decisions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                date            TEXT    NOT NULL,
                ticker          TEXT    NOT NULL,
                slug            TEXT,
                gap_bps         REAL,
                yes_bid         REAL,
                yes_ask         REAL,
                spread_bps      REAL,
                entry_side      TEXT,
                entry_price     REAL,
                position_size   REAL    DEFAULT 0,
                decision        TEXT    NOT NULL,
                expected_edge   REAL,
                book_depth      REAL,
                created_at      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outcomes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id     INTEGER NOT NULL,
                date            TEXT    NOT NULL,
                ticker          TEXT    NOT NULL,
                resolved_yes    INTEGER,
                pnl_usd         REAL,
                closed_at       TEXT,
                exit_price      REAL,
                exit_type       TEXT DEFAULT 'resolve',
                FOREIGN KEY (decision_id) REFERENCES decisions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_decisions_date ON decisions(date);
            CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON decisions(ticker);
            CREATE INDEX IF NOT EXISTS idx_outcomes_date ON outcomes(date);
            CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON outcomes(decision_id);
            CREATE TABLE IF NOT EXISTS live_quotes (
                ticker          TEXT    NOT NULL,
                yes_bid         REAL,
                yes_ask         REAL,
                no_bid          REAL,
                no_ask          REAL,
                yes_depth       REAL,
                no_depth        REAL,
                spread_pct      REAL,
                gap_bps         REAL,
                updated_at      TEXT    NOT NULL,
                PRIMARY KEY (ticker)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                type            TEXT    NOT NULL,
                ticker          TEXT,
                message         TEXT    NOT NULL,
                created_at      TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at);
            CREATE TABLE IF NOT EXISTS scan_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                date            TEXT    NOT NULL,
                scanned_at      TEXT    NOT NULL,
                ticker          TEXT    NOT NULL,
                et_time         TEXT,
                gap_bps         REAL,
                yes_ask         REAL,
                yes_bid         REAL,
                adj_wr          REAL,
                edge            REAL,
                gfr             REAL,
                gfr_velocity    REAL,
                settlement_p_win REAL,
                signal          TEXT    NOT NULL,
                vix_change      REAL
            );
            CREATE INDEX IF NOT EXISTS idx_scan_log_date ON scan_log(date);
            CREATE INDEX IF NOT EXISTS idx_scan_log_ticker ON scan_log(ticker);
        """)
        for migration in [
            "ALTER TABLE outcomes ADD COLUMN exit_price REAL",
            "ALTER TABLE outcomes ADD COLUMN exit_type TEXT DEFAULT 'resolve'",
            "ALTER TABLE decisions ADD COLUMN adj_wr REAL",
            "ALTER TABLE decisions ADD COLUMN gfr_at_entry REAL",
            "ALTER TABLE decisions ADD COLUMN spread_at_entry REAL",
        ]:
            try:
                conn.execute(migration)
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


# ── Decisions ─────────────────────────────────────────────────────────────────


def store_decision(
    date_str: str,
    ticker: str,
    decision: str,
    *,
    slug: Optional[str] = None,
    gap_bps: Optional[float] = None,
    yes_bid: Optional[float] = None,
    yes_ask: Optional[float] = None,
    spread_bps: Optional[float] = None,
    entry_side: Optional[str] = None,
    entry_price: Optional[float] = None,
    position_size: float = 0,
    expected_edge: Optional[float] = None,
    book_depth: Optional[float] = None,
    adj_wr: Optional[float] = None,
    gfr_at_entry: Optional[float] = None,
    spread_at_entry: Optional[float] = None,
) -> int:
    """Log a decision row. Returns the row id."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO decisions
                (date, ticker, slug, gap_bps, yes_bid, yes_ask, spread_bps,
                 entry_side, entry_price, position_size, decision,
                 expected_edge, book_depth, adj_wr, gfr_at_entry,
                 spread_at_entry, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date_str, ticker, slug, gap_bps, yes_bid, yes_ask, spread_bps,
                entry_side, entry_price, position_size, decision,
                expected_edge, book_depth, adj_wr, gfr_at_entry,
                spread_at_entry, now,
            ),
        )
        row_id = cur.lastrowid
    _rest_insert("decisions", {
        "date": date_str, "ticker": ticker, "slug": slug,
        "gap_bps": gap_bps, "yes_bid": yes_bid, "yes_ask": yes_ask,
        "spread_bps": spread_bps, "entry_side": entry_side, "entry_price": entry_price,
        "position_size": position_size, "decision": decision,
        "expected_edge": expected_edge, "book_depth": book_depth,
        "adj_wr": adj_wr, "gfr_at_entry": gfr_at_entry,
        "spread_at_entry": spread_at_entry, "created_at": now,
    })
    return row_id


def get_decisions_by_date(date_str: str) -> list:
    """All decisions for a given date."""
    with _conn() as c:
        return c.execute(
            "SELECT * FROM decisions WHERE date = ? ORDER BY ticker", (date_str,)
        ).fetchall()


def get_unresolved_decisions() -> list:
    """Decisions that don't have an outcome yet."""
    with _conn() as c:
        return c.execute(
            """
            SELECT d.* FROM decisions d
            LEFT JOIN outcomes o ON o.decision_id = d.id
            WHERE d.entry_side IS NOT NULL
              AND o.id IS NULL
            ORDER BY d.date, d.ticker
            """
        ).fetchall()


# ── Outcomes ──────────────────────────────────────────────────────────────────


def store_outcome(
    decision_id: int,
    date_str: str,
    ticker: str,
    resolved_yes: Optional[int],
    pnl_usd: Optional[float],
    *,
    exit_price: Optional[float] = None,
    exit_type: str = "resolve",
) -> int:
    """Record an outcome for a decision.

    exit_type='resolve' — binary $1/$0 settlement at 4pm.
    exit_type='time_exit' — sold at CLOB market price.
    exit_type='stop_loss' — stop-loss triggered intraday.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO outcomes (decision_id, date, ticker, resolved_yes, pnl_usd, closed_at, exit_price, exit_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                date_str,
                ticker,
                resolved_yes,
                pnl_usd,
                now,
                exit_price,
                exit_type,
            ),
        )
        row_id = cur.lastrowid
    _rest_insert("outcomes", {
        "decision_id": decision_id, "date": date_str, "ticker": ticker,
        "resolved_yes": resolved_yes, "pnl_usd": pnl_usd,
        "closed_at": now, "exit_price": exit_price, "exit_type": exit_type,
    })
    return row_id


def get_outcomes_for_date(date_str: str) -> list:
    """All outcomes for a given date."""
    with _conn() as c:
        return c.execute(
            """
            SELECT o.*, d.decision, d.entry_side, d.entry_price, d.gap_bps,
                   d.position_size, d.expected_edge
            FROM outcomes o
            JOIN decisions d ON d.id = o.decision_id
            WHERE o.date = ?
            ORDER BY o.ticker
            """,
            (date_str,),
        ).fetchall()


def get_all_paper_trades(limit: int = 200) -> list[dict]:
    """All paper trades: open (no outcome) + closed (has outcome).

    Returns list of dicts with status='OPEN' or 'CLOSED'.
    """
    with _conn() as c:
        closed = c.execute(
            """
            SELECT d.id, d.date, d.ticker, d.entry_side, d.entry_price,
                   d.position_size, d.gap_bps, d.expected_edge,
                   o.pnl_usd, o.exit_type, o.exit_price, 'CLOSED' AS status
            FROM decisions d
            JOIN outcomes o ON o.decision_id = d.id
            WHERE d.entry_side IS NOT NULL
            ORDER BY d.date DESC, d.ticker
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        open_trades = c.execute(
            """
            SELECT d.id, d.date, d.ticker, d.entry_side, d.entry_price,
                   d.position_size, d.gap_bps, d.expected_edge,
                   NULL AS pnl_usd, NULL AS exit_type, NULL AS exit_price, 'OPEN' AS status
            FROM decisions d
            LEFT JOIN outcomes o ON o.decision_id = d.id
            WHERE d.entry_side IS NOT NULL AND o.id IS NULL
            ORDER BY d.date DESC, d.ticker
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(r) for r in closed] + [dict(r) for r in open_trades]


def get_all_outcomes(limit: int = 100) -> list:
    """Recent outcomes with full decision context."""
    with _conn() as c:
        return c.execute(
            """
            SELECT o.*, d.decision, d.entry_side, d.entry_price, d.gap_bps,
                   d.position_size, d.expected_edge
            FROM outcomes o
            JOIN decisions d ON d.id = o.decision_id
            ORDER BY o.date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


# ── Stats ─────────────────────────────────────────────────────────────────────


def daily_stats(date_str: str) -> dict:
    """One-row stats for a day."""
    with _conn() as c:
        trades = c.execute(
            """
            SELECT COUNT(*) as count,
                   SUM(CASE WHEN o.pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN o.pnl_usd < 0 THEN 1 ELSE 0 END) as losses
            FROM outcomes o
            WHERE o.date = ?
            """,
            (date_str,),
        ).fetchone()

        pnl = c.execute(
            "SELECT COALESCE(SUM(pnl_usd), 0) as total FROM outcomes WHERE date = ?",
            (date_str,),
        ).fetchone()

        return {
            "date": date_str,
            "trades": trades["count"] if trades else 0,
            "wins": trades["wins"] if trades else 0,
            "losses": trades["losses"] if trades else 0,
            "win_rate": (
                round(trades["wins"] / trades["count"] * 100, 1)
                if trades and trades["count"] > 0
                else 0
            ),
            "pnl": round(pnl["total"], 2) if pnl else 0,
        }


def total_stats() -> dict:
    """Aggregate across all dates."""
    with _conn() as c:
        row = c.execute(
            """
            SELECT COUNT(*) as count,
                   COALESCE(SUM(pnl_usd), 0) as total_pnl,
                   SUM(CASE WHEN o.pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN o.pnl_usd < 0 THEN 1 ELSE 0 END) as losses
            FROM outcomes o
            """
        ).fetchone()

        count = (row["count"] or 0) if row else 0
        wins  = (row["wins"]  or 0) if row else 0
        losses= (row["losses"]or 0) if row else 0
        return {
            "trades": count,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / count * 100, 1) if count > 0 else 0,
            "total_pnl": round(row["total_pnl"], 2) if row else 0,
        }


def per_ticker_stats() -> list[dict]:
    """Stats grouped by ticker."""
    with _conn() as c:
        rows = c.execute(
            """
            SELECT o.ticker,
                   COUNT(*) as count,
                   COALESCE(SUM(pnl_usd), 0) as total_pnl,
                   SUM(CASE WHEN o.pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN o.pnl_usd < 0 THEN 1 ELSE 0 END) as losses
            FROM outcomes o
            GROUP BY o.ticker
            ORDER BY total_pnl DESC
            """
        ).fetchall()

        return [
            {
                "ticker": r["ticker"],
                "trades": r["count"],
                "wins": r["wins"],
                "losses": r["losses"],
                "win_rate": (
                    round(r["wins"] / r["count"] * 100, 1)
                    if r["count"] and r["wins"] is not None
                    else 0
                ),
                "pnl": round(r["total_pnl"], 2),
            }
            for r in rows
        ]


def pnl_history(limit: int = 30) -> list[dict]:
    """Daily P&L series for charting."""
    with _conn() as c:
        rows = c.execute(
            """
            SELECT o.date, COALESCE(SUM(o.pnl_usd), 0) as daily_pnl
            FROM outcomes o
            GROUP BY o.date
            ORDER BY o.date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [{"date": r["date"], "pnl": r["daily_pnl"]} for r in reversed(rows)]


# ── Live Quotes ───────────────────────────────────────────────────────────────


def update_live_quote(ticker: str, *, yes_bid=None, yes_ask=None,
                      no_bid=None, no_ask=None, yes_depth=None, no_depth=None,
                      spread_pct=None, gap_bps=None):
    """Upsert a live quote row for a ticker."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO live_quotes
               (ticker, yes_bid, yes_ask, no_bid, no_ask, yes_depth, no_depth,
                spread_pct, gap_bps, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ticker) DO UPDATE SET
               yes_bid=EXCLUDED.yes_bid, yes_ask=EXCLUDED.yes_ask,
               no_bid=EXCLUDED.no_bid, no_ask=EXCLUDED.no_ask,
               yes_depth=EXCLUDED.yes_depth, no_depth=EXCLUDED.no_depth,
               spread_pct=EXCLUDED.spread_pct, gap_bps=EXCLUDED.gap_bps,
               updated_at=EXCLUDED.updated_at
            """,
            (ticker, yes_bid, yes_ask, no_bid, no_ask, yes_depth, no_depth,
             spread_pct, gap_bps, now),
        )


def get_live_quotes() -> list:
    """All current live quotes."""
    with _conn() as c:
        return c.execute("SELECT * FROM live_quotes ORDER BY ticker").fetchall()


# ── Notifications ─────────────────────────────────────────────────────────────


def store_scan_log(
    date_str: str,
    ticker: str,
    signal: str,
    *,
    et_time: Optional[str] = None,
    gap_bps: Optional[float] = None,
    yes_ask: Optional[float] = None,
    yes_bid: Optional[float] = None,
    adj_wr: Optional[float] = None,
    edge: Optional[float] = None,
    gfr: Optional[float] = None,
    gfr_velocity: Optional[float] = None,
    settlement_p_win: Optional[float] = None,
    vix_change: Optional[float] = None,
):
    """Record every 2-min evaluation tick — entry, skip, flat, fade."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO scan_log
                (date, scanned_at, ticker, et_time, gap_bps, yes_ask, yes_bid,
                 adj_wr, edge, gfr, gfr_velocity, settlement_p_win, signal, vix_change)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (date_str, now, ticker, et_time, gap_bps, yes_ask, yes_bid,
             adj_wr, edge, gfr, gfr_velocity, settlement_p_win, signal, vix_change),
        )
    _rest_insert("scan_log", {
        "date": date_str, "scanned_at": now, "ticker": ticker, "et_time": et_time,
        "gap_bps": gap_bps, "yes_ask": yes_ask, "yes_bid": yes_bid,
        "adj_wr": adj_wr, "edge": edge, "gfr": gfr, "gfr_velocity": gfr_velocity,
        "settlement_p_win": settlement_p_win, "signal": signal, "vix_change": vix_change,
    })


def get_scan_log(date_str: str) -> list[dict]:
    """All scan_log rows for a given date, ordered by time."""
    with _conn() as c:
        rows = c.execute(
            """
            SELECT * FROM scan_log
            WHERE date = ?
            ORDER BY scanned_at
            """,
            (date_str,),
        ).fetchall()
        return [dict(r) for r in rows]


def store_notification(type_: str, ticker: str | None, message: str):
    """Log a notification event (entry, exit, scan, info)."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO notifications (type, ticker, message, created_at) VALUES (?, ?, ?, ?)",
            (type_, ticker, message, now),
        )


def get_recent_notifications(limit: int = 50) -> list:
    """Most recent notifications."""
    with _conn() as c:
        return c.execute(
            "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
