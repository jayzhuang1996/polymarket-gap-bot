"""REST API endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

import engine.state as state
from database.db import (
    get_recent_notifications, get_decisions_by_date,
    get_unresolved_decisions, total_stats, daily_stats,
    get_all_outcomes, pnl_history, get_all_paper_trades,
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
