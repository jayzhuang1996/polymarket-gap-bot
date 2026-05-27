"""REST API endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Query
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
