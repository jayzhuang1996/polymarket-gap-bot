"""REST API endpoints."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import FileResponse

import engine.state as state
from database.db import (
    get_recent_notifications, get_decisions_by_date,
    get_unresolved_decisions, total_stats, daily_stats,
    get_all_outcomes, pnl_history, get_all_paper_trades,
    get_scan_log, get_outcomes_for_date,
)
from engine.session import get_session_state

router = APIRouter()


@router.get("/")
def index():
    return FileResponse("index.html")


@router.get("/api/stats")
def api_stats():
    return {
        "total": total_stats(),
        "today": daily_stats(datetime.now(timezone.utc).strftime("%Y-%m-%d")),
    }


@router.get("/api/live-quotes")
def api_live_quotes():
    return list(state.current_quotes.values())


@router.get("/api/notifications")
def api_notifications(limit: int = Query(30, ge=1, le=100)):
    return [dict(r) for r in get_recent_notifications(limit)]


@router.get("/api/decisions/today")
def api_decisions_today():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [dict(r) for r in get_decisions_by_date(today)]


@router.get("/api/open-positions")
def api_open_positions():
    return [dict(r) for r in get_unresolved_decisions()]


@router.get("/api/paper-trades")
def api_paper_trades():
    trades = get_all_paper_trades()
    for t in trades:
        if t["status"] == "OPEN":
            q         = state.current_quotes.get(t["ticker"], {})
            side      = t.get("entry_side", "")
            ep        = t.get("entry_price") or 0
            sz        = t.get("position_size") or 0
            contracts = sz / ep if ep > 0 else 0
            exit_bid  = q.get("yes_bid" if side == "YES" else "no_bid")
            cur_val   = contracts * exit_bid if exit_bid and contracts else None
            t["est_pnl"] = round(cur_val - sz, 2) if cur_val is not None else None
            t["cur_bid"] = exit_bid
    return trades


@router.get("/api/outcomes")
def api_outcomes(limit: int = Query(50, ge=1, le=200)):
    return [dict(r) for r in get_all_outcomes(limit)]


@router.get("/api/pnl-history")
def api_pnl_history(limit: int = Query(30, ge=1, le=365)):
    return pnl_history(limit)


@router.get("/api/session-state")
def api_session_state():
    return get_session_state()


@router.post("/api/trigger/eod")
async def api_trigger_eod(background_tasks: BackgroundTasks):
    """Trigger end-of-day data collection in-process.

    Called by the Railway cron service via:
        curl -X POST https://<app>/api/trigger/eod

    Runs inside the main server process so it writes to the
    persistent volume at /data/polymarket.db, not the cron
    container's ephemeral disk.
    """
    from tools.eod_update import eod_update
    from datetime import date

    def _run():
        try:
            result = eod_update(date.today())
            print(f"[eod-trigger] done: {result}")
        except Exception as e:
            print(f"[eod-trigger] error: {e}")

    background_tasks.add_task(_run)
    return {"status": "started", "date": date.today().isoformat()}


@router.get("/api/test/preflight")
async def api_preflight():
    """Pre-market system check. Run this at 9:00 AM before trading starts.

    Tests every component the bot depends on. Green across the board = safe to trade.
    Any red = something will fail when the market opens at 9:35 AM.
    """
    import time
    import requests as _req
    from database.db import _pg_available, USE_PG, DB_PATH, store_scan_log, get_scan_log
    from database.wr_store import load_base_wr

    checks = {}

    # 1. DB write + read round-trip
    try:
        store_scan_log("1970-01-01", "_preflight_test", "TEST",
                       gap_bps=0.0, edge=0.0)
        rows = get_scan_log("1970-01-01")
        hit  = any(r.get("ticker") == "_preflight_test" for r in rows)
        checks["db_write_read"] = "ok" if hit else "wrote but could not read back"
    except Exception as e:
        checks["db_write_read"] = f"FAIL: {e}"

    # 2. Volume / persistent path
    import os as _os
    checks["volume_mounted"]  = "ok" if DB_PATH.startswith("/data") else f"WARN: path is {DB_PATH} — data lost on redeploy"
    checks["db_file_exists"]  = "ok" if _os.path.exists(DB_PATH) else "WARN: file not found yet (first run?)"

    # 3. DB backend
    if USE_PG and _pg_available:
        checks["db_backend"] = "supabase (connected)"
    elif USE_PG and not _pg_available:
        checks["db_backend"] = "sqlite_fallback (supabase unavailable)"
    else:
        checks["db_backend"] = "sqlite (local only)"

    # 4. WR cache loaded
    try:
        wr_ok = sum(1 for t, _ in state.wr_cache.items() if state.wr_cache[t][0] is not None)
        checks["wr_cache"] = f"ok ({wr_ok}/{len(state.wr_cache)} tickers loaded)"
    except Exception as e:
        checks["wr_cache"] = f"FAIL: {e}"

    # 5. Markets discovered
    n_markets = len(state.market_list)
    checks["markets_discovered"] = f"ok ({n_markets} markets)" if n_markets >= 9 else f"WARN: only {n_markets} markets (expected 9)"

    # 6. CLOB / live quotes arriving
    n_quotes = sum(1 for q in state.current_quotes.values() if q.get("yes_ask"))
    checks["live_quotes"] = f"ok ({n_quotes}/9 tickers have quotes)" if n_quotes >= 6 else f"WARN: only {n_quotes}/9 tickers have live quotes"

    # 7. Polymarket API reachable
    try:
        t0 = time.time()
        r  = _req.get("https://gamma-api.polymarket.com/markets?limit=1", timeout=5)
        ms = int((time.time() - t0) * 1000)
        checks["polymarket_api"] = f"ok ({ms}ms)" if r.status_code == 200 else f"FAIL: HTTP {r.status_code}"
    except Exception as e:
        checks["polymarket_api"] = f"FAIL: {e}"

    # 8. yfinance reachable (quick SPX fetch)
    try:
        import yfinance as yf
        t0   = time.time()
        spx  = yf.Ticker("^GSPC").fast_info
        ms   = int((time.time() - t0) * 1000)
        last = getattr(spx, "last_price", None)
        checks["yfinance"] = f"ok (SPX={last:.0f}, {ms}ms)" if last else "WARN: no price returned"
    except Exception as e:
        checks["yfinance"] = f"FAIL: {e}"

    # overall
    any_fail = any("FAIL" in str(v) for v in checks.values())
    any_warn = any("WARN" in str(v) for v in checks.values())
    overall  = "FAIL" if any_fail else ("WARN" if any_warn else "ALL GREEN")

    from datetime import timedelta as _td
    et = datetime.now(timezone.utc) + _td(hours=-4)
    mins_to_open = max(0, (9*60+35) - (et.hour*60+et.minute))

    return {
        "overall":        overall,
        "et_time":        et.strftime("%H:%M"),
        "mins_to_open":   mins_to_open,
        "checks":         checks,
    }


@router.get("/api/health")
def api_health():
    """System health check — call this anytime to verify everything is working.

    Returns DB backend, last scan time, today's row counts, and trading status.
    Green means data is flowing. Use this every morning before market open.
    """
    from database.db import _pg_available, USE_PG, DB_PATH, get_scan_log
    import os

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scan_rows = get_scan_log(today)

    last_scan = None
    last_ticker = None
    if scan_rows:
        last = scan_rows[-1]
        last_scan  = last.get("scanned_at")
        last_ticker = last.get("ticker")

    # DB backend
    if USE_PG and _pg_available:
        db_backend = "supabase"
        db_status  = "connected"
    elif USE_PG and not _pg_available:
        db_backend = "sqlite_fallback"
        db_status  = "supabase_unavailable"
    else:
        db_backend = "sqlite"
        db_status  = "ok"

    # Volume check — is SQLite on a persistent path?
    db_path         = DB_PATH
    volume_mounted  = db_path.startswith("/data")
    db_file_exists  = os.path.exists(db_path)

    # ET time + market hours
    from datetime import timedelta
    et_now    = datetime.now(timezone.utc) + timedelta(hours=-4)
    in_window = 9 <= et_now.hour < 16

    return {
        "status":        "ok",
        "et_time":       et_now.strftime("%H:%M"),
        "in_market_hours": in_window,
        "db_backend":    db_backend,
        "db_status":     db_status,
        "db_path":       db_path,
        "volume_mounted": volume_mounted,
        "db_file_exists": db_file_exists,
        "today":         today,
        "scan_rows_today":  len(scan_rows),
        "last_scan_at":  last_scan,
        "last_scan_ticker": last_ticker,
        "open_positions": len([r for r in get_unresolved_decisions()
                               if dict(r).get("date") == today]),
    }


@router.get("/api/test/volume")
def api_test_volume():
    """Write a real scan_log row for today, read it back via the normal path, then delete it.

    This proves the full pipeline: SQLite write → persistent volume → API read.
    Run this any time before market open to confirm data will survive the session.
    """
    import os
    from database.db import store_scan_log, get_scan_log, _conn, DB_PATH

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    test_ticker = "__vol_test__"

    # 1. Write
    try:
        store_scan_log(
            today, test_ticker, "TEST",
            gap_bps=42.0, edge=0.07, adj_wr=0.75,
        )
        write_ok = True
    except Exception as e:
        return {"passed": False, "stage": "write", "error": str(e)}

    # 2. Read back via the same function the API uses
    try:
        rows = get_scan_log(today)
        found = any(r.get("ticker") == test_ticker for r in rows)
        read_ok = found
    except Exception as e:
        return {"passed": False, "stage": "read", "error": str(e)}

    # 3. Cleanup
    try:
        c = _conn()
        c.execute("DELETE FROM scan_log WHERE ticker = ?", (test_ticker,))
        c.commit()
        c.close()
    except Exception:
        pass  # cleanup failure doesn't fail the test

    # 4. File size — confirms data is accumulating on the volume
    try:
        size_kb = round(os.path.getsize(DB_PATH) / 1024, 1)
    except Exception:
        size_kb = None

    passed = write_ok and read_ok
    return {
        "passed":      passed,
        "write":       "ok" if write_ok else "FAIL",
        "read_back":   "ok" if read_ok  else "FAIL — wrote but could not read",
        "db_path":     DB_PATH,
        "db_size_kb":  size_kb,
        "note":        "Volume is working — data will persist across restarts." if passed
                       else "PROBLEM: data written but not readable. Check volume mount.",
    }


@router.get("/api/scan-log/latest")
def api_scan_log_latest():
    """Most recent scan_log row per ticker for today.

    Used by the Live Scanner panel — shows each ticker's last 2-min evaluation.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows  = get_scan_log(today)
    latest: dict[str, dict] = {}
    for r in rows:
        latest[r["ticker"]] = r  # later rows overwrite earlier — gets most recent
    return list(latest.values())


@router.get("/api/export/daily")
def api_export_daily(date: str = Query(None, description="YYYY-MM-DD, defaults to today")):
    """Full day export for post-market analysis.

    Returns scan_log (every 2-min tick), decisions (entries), and outcomes (P&L).
    Call this from Claude Code to analyse any trading day without a direct DB connection.
    """
    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scan     = get_scan_log(date_str)
    decisions = [dict(r) for r in get_decisions_by_date(date_str)]
    outcomes  = [dict(r) for r in get_outcomes_for_date(date_str)]

    # compute simple per-ticker summary inline
    tickers_seen = sorted({r["ticker"] for r in scan})
    summary = []
    for ticker in tickers_seen:
        ticks   = [r for r in scan if r["ticker"] == ticker]
        entered = next((d for d in decisions if d["ticker"] == ticker), None)
        outcome = next((o for o in outcomes if o["ticker"] == ticker), None)
        signals = [t["signal"] for t in ticks if t.get("signal")]
        summary.append({
            "ticker":        ticker,
            "n_ticks":       len(ticks),
            "signals_seen":  list(dict.fromkeys(signals)),  # ordered unique
            "gap_bps":       ticks[0].get("gap_bps") if ticks else None,
            "entered":       entered is not None,
            "entry_side":    entered.get("entry_side") if entered else None,
            "entry_price":   entered.get("entry_price") if entered else None,
            "edge_at_entry": entered.get("expected_edge") if entered else None,
            "adj_wr":        entered.get("adj_wr") if entered else None,
            "pnl_usd":       outcome.get("pnl_usd") if outcome else None,
            "exit_type":     outcome.get("exit_type") if outcome else None,
        })

    return {
        "date":      date_str,
        "summary":   summary,
        "scan_log":  scan,
        "decisions": decisions,
        "outcomes":  outcomes,
    }
