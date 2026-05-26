#!/usr/bin/env python3
"""
Live Streamlit dashboard for the gap mispricing bot.

Usage: streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh
from database.db import (
    init_db,
    get_decisions_by_date,
    get_unresolved_decisions,
    get_all_outcomes,
    daily_stats,
    total_stats,
    per_ticker_stats,
    pnl_history,
    get_live_quotes,
    get_recent_notifications,
)

st.set_page_config(
    page_title="Gap Mispricing Bot",
    page_icon="📈",
    layout="wide",
)

init_db()

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Auto-refresh every 5s while page is visible
st_autorefresh(interval=5000, key="live_refresh")

# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.title("📈 Gap Bot")
st.sidebar.caption(f"Today: {TODAY}")

if st.sidebar.button("🔄 Refresh Data"):
    st.rerun()

st.sidebar.divider()

# Quick stats in sidebar
ts = total_stats()
st.sidebar.metric("Total P&L", f"${ts['total_pnl']:.2f}")
st.sidebar.metric("Win Rate", f"{ts['win_rate']}%" if ts['trades'] > 0 else "—")
st.sidebar.metric("Total Trades", ts['trades'])

# Today's quick P&L
today_resolved = daily_stats(TODAY)
st.sidebar.metric("Today's P&L", f"${today_resolved['pnl']:.2f}",
                  delta=f"{today_resolved['wins']}W / {today_resolved['losses']}L")

open_positions = len(get_unresolved_decisions())
st.sidebar.metric("Open Positions", open_positions)

st.sidebar.divider()
st.sidebar.caption(
    "**Commands:**\n"
    "`python main.py scan` — morning scan\n"
    "`python main.py resolve` — evening resolve\n"
    "`streamlit run dashboard.py` — this dashboard"
)

# ── Live Quotes ──────────────────────────────────────────────────────────────

st.subheader("🔴 Live Quotes — CLOB Feed")

live_quotes = get_live_quotes()
if live_quotes:
    lq_rows = []
    for q in live_quotes:
        lq_rows.append({
            "Ticker": q["ticker"],
            "YES Bid": f"${q['yes_bid']:.3f}" if q['yes_bid'] else "—",
            "YES Ask": f"${q['yes_ask']:.3f}" if q['yes_ask'] else "—",
            "NO Bid": f"${q['no_bid']:.3f}" if q['no_bid'] else "—",
            "NO Ask": f"${q['no_ask']:.3f}" if q['no_ask'] else "—",
            "Spread": f"{q['spread_pct']:.1f}%" if q['spread_pct'] else "—",
            "Gap (bps)": f"{q['gap_bps']:.0f}" if q['gap_bps'] else "—",
            "Updated": q["updated_at"][11:19] if q.get("updated_at") else "—",
        })
    lq_df = pd.DataFrame(lq_rows)

    def _color_spread(val):
        if isinstance(val, str) and val.endswith("%"):
            try:
                v = float(val[:-1])
                if v is None:
                    return ""
                if v > 15.0:
                    return "color: red; font-weight: bold"
                if v > 10.0:
                    return "color: orange"
                if v < 5.0:
                    return "color: green"
            except (ValueError, TypeError):
                pass
        return ""

    st.dataframe(
        lq_df.style.applymap(_color_spread, subset=["Spread"]),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No live quotes yet. Run `python monitor.py` to start the WebSocket feed.")

# ── Notifications Feed ───────────────────────────────────────────────────────

st.divider()
st.subheader("🔔 Event Feed")

notifications = get_recent_notifications(limit=20)
if notifications:
    notif_icons = {"entry": "🟢", "exit": "🔴", "scan": "📡", "info": "ℹ️", "error": "❌"}
    for n in reversed(notifications):
        ts = n["created_at"][11:19] if n.get("created_at") else ""
        icon = notif_icons.get(n["type"], "📌")
        ticker_tag = f"**{n['ticker']}**" if n["ticker"] else "System"
        st.caption(f"{icon} `{ts}` {ticker_tag} — {n['message']}")
else:
    st.caption("No events yet. Notifications appear as the bot scans and trades.")

st.divider()

# ── Main Panel ───────────────────────────────────────────────────────────────

st.title("📈 Daily Stock Gap Mispricing Bot")

# ── Open Positions ───────────────────────────────────────────────────────────

open_decisions = get_unresolved_decisions()
if open_decisions:
    st.subheader("🔴 Open Positions")
    rows = []
    for d in open_decisions:
        rows.append({
            "Date": d["date"],
            "Ticker": d["ticker"],
            "Side": d["entry_side"],
            "Entry": f"${d['entry_price']:.2f}" if d['entry_price'] else "—",
            "Size": f"${d['position_size']:.0f}" if d['position_size'] else "—",
            "Gap (bps)": f"{d['gap_bps']:.0f}" if d['gap_bps'] else "—",
            "Expected Edge": f"{d['expected_edge']:.1f}%" if d['expected_edge'] else "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.info("No open positions.")

# ── Today's Scan ─────────────────────────────────────────────────────────────

st.divider()
st.subheader(f"📋 Today's Scan — {TODAY}")

today_decisions = get_decisions_by_date(TODAY)
if today_decisions:
    rows = []
    for d in today_decisions:
        rows.append({
            "Ticker": d["ticker"],
            "Gap (bps)": f"{d['gap_bps']:.0f}" if d['gap_bps'] else "—",
            "Bid": f"${d['yes_bid']:.3f}" if d['yes_bid'] else "—",
            "Ask": f"${d['yes_ask']:.3f}" if d['yes_ask'] else "—",
            "Depth": f"{d['book_depth']:.0f}" if d['book_depth'] else "—",
            "Decision": d["decision"],
        })
    df = pd.DataFrame(rows)

    # Color the Decision column
    def color_decision(val):
        if isinstance(val, str) and val.startswith("BUY"):
            return "color: green; font-weight: bold"
        return "color: gray"

    st.dataframe(
        df.style.applymap(color_decision, subset=["Decision"]),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No scan data for today. Run `python main.py scan` first.")

# ── Today's Resolved ─────────────────────────────────────────────────────────

today_outcomes = daily_stats(TODAY)
if today_outcomes["trades"] > 0:
    st.subheader("✅ Today's Results")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trades", today_outcomes["trades"])
    c2.metric("Wins", today_outcomes["wins"])
    c3.metric("Win Rate", f"{today_outcomes['win_rate']}%")
    c4.metric("P&L", f"${today_outcomes['pnl']:.2f}")

    # Trade details
    outcomes = get_all_outcomes(limit=30)
    today_rows = [o for o in outcomes if o["date"] == TODAY]
    if today_rows:
        detail_rows = []
        for o in today_rows:
            detail_rows.append({
                "Ticker": o["ticker"],
                "Side": o["entry_side"],
                "Entry": f"${o['entry_price']:.2f}" if o['entry_price'] else "—",
                "Gap (bps)": f"{o['gap_bps']:.0f}" if o['gap_bps'] else "—",
                "Result": "UP → WON" if (o["resolved_yes"] and o["entry_side"] == "YES") or (not o["resolved_yes"] and o["entry_side"] == "NO") else f"{'UP' if o['resolved_yes'] else 'DOWN'} → LOST",
                "P&L": f"${o['pnl_usd']:.2f}" if o['pnl_usd'] else "—",
            })
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

# ── Overall Stats ────────────────────────────────────────────────────────────

st.divider()
st.subheader("📊 Overall Performance")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Trades", ts["trades"])
c2.metric("Wins", ts["wins"])
c3.metric("Losses", ts["losses"])
c4.metric("Win Rate", f"{ts['win_rate']}%" if ts['trades'] > 0 else "—")
c5.metric("Total P&L", f"${ts['total_pnl']:.2f}")

# ── Per-Ticker Performance ───────────────────────────────────────────────────

ticker_stats = per_ticker_stats()
if ticker_stats:
    st.subheader("📊 Per-Ticker Performance")
    tf = pd.DataFrame(ticker_stats)
    tf["Win Rate"] = tf["win_rate"].apply(lambda x: f"{x}%")
    tf["P&L"] = tf["pnl"].apply(lambda x: f"${x:.2f}")
    st.dataframe(
        tf[["ticker", "trades", "wins", "losses", "Win Rate", "P&L"]]
        .rename(columns={"ticker": "Ticker", "trades": "Trades", "wins": "Wins", "losses": "Losses"}),
        use_container_width=True,
        hide_index=True,
    )

# ── P&L History Chart ────────────────────────────────────────────────────────

history = pnl_history(limit=30)
if len(history) > 1:
    st.subheader("📈 P&L History")
    hf = pd.DataFrame(history)
    hf["cumulative"] = hf["pnl"].cumsum()
    st.line_chart(hf.set_index("date")[["pnl", "cumulative"]])
elif len(history) == 1:
    st.caption("Run more trading days to see P&L history chart.")

# ── All-Time Trade Log ───────────────────────────────────────────────────────

st.divider()
st.subheader("📜 All-Time Trade Log")

all_outcomes = get_all_outcomes(limit=100)
if all_outcomes:
    rows = []
    for o in all_outcomes:
        rows.append({
            "Date": o["date"],
            "Ticker": o["ticker"],
            "Side": o["entry_side"],
            "Gap (bps)": f"{o['gap_bps']:.0f}" if o['gap_bps'] else "—",
            "Entry": f"${o['entry_price']:.2f}" if o['entry_price'] else "—",
            "Expected Edge": f"{o['expected_edge']:.1f}%" if o['expected_edge'] else "—",
            "Result": "WON" if (o["resolved_yes"] and o["entry_side"] == "YES") or (not o["resolved_yes"] and o["entry_side"] == "NO") else "LOST",
            "P&L": f"${o['pnl_usd']:.2f}" if o['pnl_usd'] else "—",
        })
    df = pd.DataFrame(rows)

    def color_pnl(val):
        if isinstance(val, str):
            try:
                v = float(val.replace("$", ""))
                return "color: green" if v > 0 else "color: red" if v < 0 else ""
            except:
                pass
        return ""

    st.dataframe(
        df.style.applymap(color_pnl, subset=["P&L"]),
        use_container_width=True,
        hide_index=True,
    )
