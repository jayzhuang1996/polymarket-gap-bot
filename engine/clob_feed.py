"""Polymarket CLOB feed — WebSocket subscription and REST fallback/poll."""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import websockets

import engine.state as state
from config import CLOB_API, TRADING_FEE_PCT
from engine.strategy import _spread_pct, _est_edge, _compute_signal
from database.db import update_live_quote

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


# ── WebSocket loop ─────────────────────────────────────────────────────────────

async def polymarket_loop():
    """Connect to Polymarket CLOB WS; update in-memory state and enqueue broadcasts."""
    while True:
        asset_ids = list(state.token_map.keys())
        if not asset_ids:
            await asyncio.sleep(5)
            continue
        try:
            async with websockets.connect(WS_URL, ping_interval=30, ping_timeout=10) as ws:
                await ws.send(json.dumps({
                    "type": "market", "assets_ids": asset_ids,
                    "initial_dump": True, "custom_feature_enabled": True,
                }))
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    for ev in data if isinstance(data, list) else [data]:
                        _process_event(ev)
                    # Token IDs changed (daily reset) — reconnect to new markets.
                    if set(state.token_map.keys()) != set(asset_ids):
                        break
        except Exception:
            await asyncio.sleep(5)


def _process_event(ev: dict):
    """Single Polymarket WS event → update in-memory state + enqueue broadcast."""
    asset_id = ev.get("asset_id", "")
    info     = state.token_map.get(asset_id)
    if not info:
        return

    ticker = info["ticker"]
    side   = info["side"]
    now    = datetime.now(timezone.utc).isoformat()

    if ticker not in state.current_quotes:
        state.current_quotes[ticker] = {"ticker": ticker, "gap_bps": None}

    q = state.current_quotes[ticker]

    bid = ev.get("bid") or ev.get("best_bid")
    ask = ev.get("ask") or ev.get("best_ask")
    if bid is not None and ask is not None:
        try:
            bid_f, ask_f = float(bid), float(ask)
        except (TypeError, ValueError):
            pass
        else:
            if side == "YES":
                q["yes_bid"] = bid_f; q["yes_ask"] = ask_f
                q["yes_spread"] = _spread_pct(bid_f, ask_f)
            else:
                q["no_bid"] = bid_f; q["no_ask"] = ask_f
                q["no_spread"] = _spread_pct(bid_f, ask_f)

    price = ev.get("price")
    if price is not None:
        try:
            p = float(price)
        except (TypeError, ValueError):
            pass
        else:
            if side == "YES":
                if q.get("yes_bid") is None: q["yes_bid"] = p
                if q.get("yes_ask") is None: q["yes_ask"] = p
            else:
                if q.get("no_bid") is None: q["no_bid"] = p
                if q.get("no_ask") is None: q["no_ask"] = p

    if q.get("yes_bid") is None and q.get("no_bid") is None:
        return

    adj_wr = q.get("adj_wr")
    if adj_wr is not None:
        gap_bps   = q.get("gap_bps") or 0
        payout    = 1.0 - TRADING_FEE_PCT
        entry_ask = (q.get("yes_ask") if gap_bps > 50
                     else q.get("no_ask") if gap_bps < -50 else None)
        live_edge = round(adj_wr * payout - entry_ask, 4) if entry_ask else None
        q["live_edge"] = live_edge   # WR-based; settlement model overwrites in session.py
        q["signal"]    = _compute_signal(gap_bps, q.get("gfr"), live_edge)
    else:
        q["est_edge"] = _est_edge(ticker, q.get("gap_bps"), q.get("yes_ask"), q.get("no_ask"))

    q["updated_at"] = now

    update_live_quote(
        ticker,
        yes_bid=q.get("yes_bid"), yes_ask=q.get("yes_ask"),
        no_bid=q.get("no_bid"),   no_ask=q.get("no_ask"),
        spread_pct=q.get("yes_spread"),
        gap_bps=q.get("gap_bps"),
    )
    state.broadcast_queue.put_nowait(json.dumps({"type": "quote", **q}))


# ── REST fallback ──────────────────────────────────────────────────────────────

async def initial_rest_fallback():
    """One-shot: fill missing WS data via CLOB REST 15 seconds after startup."""
    await asyncio.sleep(15)
    for ticker in [m["ticker"] for m in state.market_list]:
        q       = state.current_quotes.get(ticker, {})
        has_yes = q.get("yes_bid") is not None
        has_no  = q.get("no_bid") is not None
        if has_yes and has_no:
            continue

        yes_id = no_id = None
        for m in state.market_list:
            if m["ticker"] == ticker:
                yes_id, no_id = m["yes_token"], m["no_token"]
                break
        if not yes_id:
            continue

        try:
            async with httpx.AsyncClient(timeout=10) as c:
                if not has_yes:
                    ask_r = await c.get(f"{CLOB_API}/price", params={"token_id": yes_id, "side": "SELL"})
                    bid_r = await c.get(f"{CLOB_API}/price", params={"token_id": yes_id, "side": "BUY"})
                    if ask_r.status_code == 200:
                        ask_p = float(ask_r.json().get("price", 0))
                        bid_p = (float(bid_r.json().get("price", 0))
                                 if bid_r.status_code == 200 else ask_p * 0.95)
                        if ask_p > 0:
                            state.current_quotes.setdefault(ticker, {"ticker": ticker})
                            state.current_quotes[ticker].update({
                                "yes_bid":    bid_p,
                                "yes_ask":    ask_p,
                                "yes_spread": _spread_pct(bid_p, ask_p),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            })
                if not has_no:
                    ask_r = await c.get(f"{CLOB_API}/price", params={"token_id": no_id, "side": "SELL"})
                    bid_r = await c.get(f"{CLOB_API}/price", params={"token_id": no_id, "side": "BUY"})
                    if ask_r.status_code == 200:
                        ask_p = float(ask_r.json().get("price", 0))
                        bid_p = (float(bid_r.json().get("price", 0))
                                 if bid_r.status_code == 200 else ask_p * 0.95)
                        if ask_p > 0:
                            state.current_quotes.setdefault(ticker, {"ticker": ticker})
                            state.current_quotes[ticker].update({
                                "no_bid":     bid_p,
                                "no_ask":     ask_p,
                                "no_spread":  _spread_pct(bid_p, ask_p),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            })
        except Exception:
            continue

        if ticker in state.current_quotes:
            q2 = state.current_quotes[ticker]
            q2["est_edge"] = _est_edge(ticker, q2.get("gap_bps"), q2.get("yes_ask"), q2.get("no_ask"))
            state.broadcast_queue.put_nowait(json.dumps({"type": "quote", **q2}))

    with_data = sum(
        1 for t in [m["ticker"] for m in state.market_list]
        if state.current_quotes.get(t, {}).get("yes_bid")
        or state.current_quotes.get(t, {}).get("no_bid")
    )
    print(f"  REST fallback: {with_data}/{len(state.market_list)} tickers have price data")


async def periodic_rest_poll():
    """Refresh all ticker prices via CLOB REST every 25 seconds."""
    while True:
        await asyncio.sleep(25)
        async with httpx.AsyncClient(timeout=10) as c:
            for m in state.market_list:
                ticker = m["ticker"]
                try:
                    yes_ask_r = await c.get(f"{CLOB_API}/price",
                                            params={"token_id": m["yes_token"], "side": "SELL"})
                    yes_bid_r = await c.get(f"{CLOB_API}/price",
                                            params={"token_id": m["yes_token"], "side": "BUY"})
                    if yes_ask_r.status_code == 200:
                        ask_p = float(yes_ask_r.json().get("price", 0))
                        bid_p = (float(yes_bid_r.json().get("price", 0))
                                 if yes_bid_r.status_code == 200 else ask_p * 0.95)
                        if ask_p > 0:
                            state.current_quotes.setdefault(ticker, {"ticker": ticker, "gap_bps": None})
                            state.current_quotes[ticker].update({
                                "yes_bid":    bid_p,
                                "yes_ask":    ask_p,
                                "yes_spread": _spread_pct(bid_p, ask_p),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            })
                    no_ask_r = await c.get(f"{CLOB_API}/price",
                                           params={"token_id": m["no_token"], "side": "SELL"})
                    no_bid_r = await c.get(f"{CLOB_API}/price",
                                           params={"token_id": m["no_token"], "side": "BUY"})
                    if no_ask_r.status_code == 200:
                        ask_p = float(no_ask_r.json().get("price", 0))
                        bid_p = (float(no_bid_r.json().get("price", 0))
                                 if no_bid_r.status_code == 200 else ask_p * 0.95)
                        if ask_p > 0:
                            state.current_quotes.setdefault(ticker, {"ticker": ticker, "gap_bps": None})
                            state.current_quotes[ticker].update({
                                "no_bid":     bid_p,
                                "no_ask":     ask_p,
                                "no_spread":  _spread_pct(bid_p, ask_p),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            })
                except Exception:
                    continue

                if state.current_quotes.get(ticker, {}).get("yes_bid"):
                    q = state.current_quotes[ticker]
                    q["est_edge"] = _est_edge(ticker, q.get("gap_bps"), q.get("yes_ask"), q.get("no_ask"))
                    state.broadcast_queue.put_nowait(json.dumps({"type": "quote", **q}))
