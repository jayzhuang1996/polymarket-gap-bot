#!/usr/bin/env python3
"""
Live market monitor — WebSocket streaming + scan cycle + notifications.

Connects to Polymarket CLOB WebSocket for real-time prices, runs the 3-gate
scanner every 5 minutes (9:30-10:30 ET), and sends macOS notifications on
entry/exit decisions.

Usage:
  python monitor.py              Full monitor (WebSocket + scan + notify)
  python monitor.py --stream     WebSocket only (no scan cycle)
  python monitor.py --scan       One scan cycle only (for testing)
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
import websockets
import yfinance as yf

from database.db import (
    init_db, update_live_quote, store_notification,
    get_unresolved_decisions,
)
from database.wr_store import load_base_wr
from engine.scanner import MultiScanDecider

# ── Constants ─────────────────────────────────────────────────────────────────

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
CLOB_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

TICKERS = [
    ("SPX", "^GSPC"), ("NVDA", "NVDA"), ("TSLA", "TSLA"),
    ("AAPL", "AAPL"), ("AMZN", "AMZN"), ("GOOGL", "GOOGL"),
    ("META", "META"), ("MSFT", "MSFT"), ("NFLX", "NFLX"),
]

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
SLUG_OVERRIDES = {"^GSPC": "spx"}

_ET_OFFSET = timedelta(hours=-4)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _et_now_str() -> str:
    return (datetime.now(timezone.utc) + _ET_OFFSET).strftime("%H:%M:%S ET")


def _et_dt() -> datetime:
    return datetime.now(timezone.utc) + _ET_OFFSET


def _slug(ticker: str) -> str:
    prefix = SLUG_OVERRIDES.get(ticker, ticker.lower())
    today = datetime.now(timezone.utc)
    return f"{prefix}-up-or-down-on-{MONTH_NAMES[today.month - 1]}-{today.day}-{today.year}"


def _notify(title: str, body: str):
    """Send macOS Notification Center alert."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{body}" with title "{title}"'],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _spread_pct(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid * 100.0


# ── Market Discovery ─────────────────────────────────────────────────────────


def find_today_markets() -> dict:
    """Find all of today's markets via Gamma slug search.

    Returns dict keyed by YES token ID:
      {yes_token: {ticker, yes_token, no_token, condition_id, slug}}
    """
    today = datetime.now(timezone.utc)
    result = {}
    for display_name, yahoo_ticker in TICKERS:
        slug = _slug(yahoo_ticker)
        try:
            resp = requests.get(f"{GAMMA_API}/events?slug={slug}", timeout=15)
            if resp.status_code != 200:
                print(f"  [{_et_now_str()}] {display_name}: HTTP {resp.status_code}")
                continue
            events = resp.json()
            if not events:
                print(f"  [{_et_now_str()}] {display_name}: no event for slug={slug}")
                continue
            mk = events[0].get("markets", [None])[0]
            if not mk:
                print(f"  [{_et_now_str()}] {display_name}: no markets")
                continue
            raw = mk.get("clobTokenIds", "[]")
            ids = json.loads(raw) if isinstance(raw, str) else (raw or [])
            if len(ids) >= 2:
                yes_token = str(ids[0]).strip()
                no_token = str(ids[1]).strip()
                result[yes_token] = {
                    "ticker": display_name,
                    "yes_token": yes_token,
                    "no_token": no_token,
                    "condition_id": mk.get("conditionId", ""),
                    "slug": slug,
                }
        except requests.RequestException as e:
            print(f"  [{_et_now_str()}] {display_name}: {e}")
    return result


# ── CLOB REST Fallback ────────────────────────────────────────────────────────


def _clob_price(token_id: str) -> tuple[float | None, float | None]:
    """Fallback REST poll for bid/ask if WebSocket hasn't updated."""
    try:
        b = requests.get(f"{CLOB_API}/price", params={"token_id": token_id, "side": "BUY"}, timeout=10)
        a = requests.get(f"{CLOB_API}/price", params={"token_id": token_id, "side": "SELL"}, timeout=10)
        bid = float(b.json()["price"]) if b.status_code == 200 else None
        ask = float(a.json()["price"]) if a.status_code == 200 else None
        return bid, ask
    except Exception:
        return None, None


def _clob_depth(token_id: str, side: str) -> float:
    try:
        resp = requests.get(f"{CLOB_API}/book", params={"token_id": token_id}, timeout=10)
        if resp.status_code != 200:
            return 0
        levels = resp.json().get(side, [])
        return float(levels[0]["size"]) if levels else 0
    except Exception:
        return 0


# ── WebSocket Stream ──────────────────────────────────────────────────────────


async def websocket_loop(token_map: dict):
    """Connect to CLOB WebSocket, stream live quotes into DB.

    Reconnects automatically on failure with exponential backoff.
    Each event updates the live_quotes table for the dashboard to read.
    """
    asset_ids = list(token_map.keys())
    ticker_by_token = {v["yes_token"]: v["ticker"] for v in token_map.values()}
    ticker_by_token.update({v["no_token"]: v["ticker"] for v in token_map.values()})

    backoff = 1
    while True:
        # Hard cutoff at 4pm ET — markets resolved, CLOB returns garbage
        now_et = _et_dt()
        if now_et.hour >= 16:
            next_check = 300  # check again in 5 minutes
            print(f"  [{_et_now_str()}] Past 4pm ET — pausing WebSocket {next_check}s")
            await asyncio.sleep(next_check)
            continue

        try:
            async with websockets.connect(WS_URL, ping_interval=30, ping_timeout=10) as ws:
                # Subscribe
                sub = {
                    "type": "market",
                    "assets_ids": asset_ids,
                    "initial_dump": True,
                    "custom_feature_enabled": True,
                }
                await ws.send(json.dumps(sub))
                print(f"  [{_et_now_str()}] WebSocket connected, {len(asset_ids)} tokens subscribed")
                backoff = 1  # reset on successful connect

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # Can be a single event or a batch
                    events = data if isinstance(data, list) else [data]
                    for ev in events:
                        _handle_ws_event(ev, ticker_by_token, token_map)

        except (websockets.ConnectionClosed, asyncio.TimeoutError,
                OSError, Exception) as e:
            print(f"  [{_et_now_str()}] WebSocket disconnected: {e}")
            print(f"  Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)  # cap at 60s


def _handle_ws_event(ev: dict, ticker_by_token: dict, token_map: dict):
    """Process a single WebSocket event and update live_quotes."""
    asset_id = ev.get("asset_id", "")
    ticker = ticker_by_token.get(asset_id)

    # best_bid_ask messages carry the current quote
    if "best_bid_ask" in ev or "bid" in ev or "ask" in ev:
        bid = ev.get("bid") or ev.get("best_bid")
        ask = ev.get("ask") or ev.get("best_ask")
        if bid is not None and ask is not None and ticker:
            try:
                bid_f = float(bid)
                ask_f = float(ask)
            except (TypeError, ValueError):
                return

            # Determine if this is YES or NO token
            info = token_map.get(asset_id)
            if info and ticker:
                if asset_id == info["yes_token"]:
                    update_live_quote(ticker, yes_bid=bid_f, yes_ask=ask_f,
                                      spread_pct=_spread_pct(bid_f, ask_f))
                elif asset_id == info["no_token"]:
                    update_live_quote(ticker, no_bid=bid_f, no_ask=ask_f,
                                      spread_pct=_spread_pct(bid_f, ask_f))

    # price_change events carry last trade price
    elif "price" in ev and ticker:
        try:
            price = float(ev["price"])
        except (TypeError, ValueError):
            return
        # Update whichever side this token is
        info = token_map.get(asset_id)
        if info:
            if asset_id == info["yes_token"]:
                update_live_quote(ticker, yes_bid=price, yes_ask=price)
            elif asset_id == info["no_token"]:
                update_live_quote(ticker, no_bid=price, no_ask=price)


# ── Scan Cycle ────────────────────────────────────────────────────────────────


async def scan_cycle(token_map: dict):
    """Run the 3-gate scanner every 5 minutes during the entry window.

    Phase 0: Discover markets, calculate gaps
    Phase 1-2: Every 5 min, snapshot CLOB prices and feed into MultiScanDecider
    Phase 3: After 10:30am (or window close), make final decisions
    """
    # Wait until 9:35am ET (first 5m candle closes at 9:35)
    while True:
        now = _et_dt()
        if now.hour >= 9 and (now.hour > 9 or now.minute >= 35):
            break
        wait_sec = ((9 * 60 + 35) - (now.hour * 60 + now.minute)) * 60
        if wait_sec > 0:
            print(f"  [{_et_now_str()}] Waiting {wait_sec/60:.0f}min until 9:35am ET...")
            await asyncio.sleep(min(wait_sec, 300))
        else:
            break

    print(f"\n  [{_et_now_str()}] === SCAN CYCLE START ===\n")

    # Phase 0: Build ticker → token map (reverse of token_map)
    ticker_info = {}
    for info in token_map.values():
        ticker = info["ticker"]
        ticker_info[ticker] = info

    # Calculate gaps and create deciders
    markets = {}
    gaps = {}
    deciders = {}

    print(f"  [{_et_now_str()}] Pre-scanning {len(TICKERS)} tickers...\n")

    for display_name, yahoo_ticker in TICKERS:
        if display_name not in ticker_info:
            print(f"  [{_et_now_str()}] {display_name}: no market found")
            continue

        # Calculate gap via yfinance
        try:
            stock = yf.Ticker(yahoo_ticker)
            hist = stock.history(period="5d")
            if len(hist) < 2:
                print(f"  [{_et_now_str()}] {display_name}: insufficient yfinance data")
                continue
            today_bar = hist.iloc[-1]
            prev_close = float(hist.iloc[-2]["Close"])
            today_open = float(today_bar["Open"])
            if today_open == 0 or prev_close == 0:
                continue
            gap = (today_open - prev_close) / prev_close
        except Exception as e:
            print(f"  [{_et_now_str()}] {display_name}: gap error: {e}")
            continue

        gap_up = gap > 0
        base_yes, base_no = load_base_wr(display_name, gap_up)
        gap_label = f"{gap*10000:+.0f} bps"
        print(f"  [{_et_now_str()}] {display_name:6s}: gap={gap_label}, base_WR={base_yes if gap_up else base_no:.0%}")

        decider = MultiScanDecider(
            ticker=display_name, gap_pct=gap,
            open_price=today_open, prev_close=prev_close,
            base_wr_yes=base_yes, base_wr_no=base_no,
        )

        markets[display_name] = ticker_info[display_name]
        gaps[display_name] = gap
        deciders[display_name] = decider

        # Update gap in live_quotes
        update_live_quote(display_name, gap_bps=gap * 10000 if gap else 0)

    if not deciders:
        print(f"\n  [{_et_now_str()}] No tradeable tickers today.")
        store_notification("info", None, "No tradeable tickers found today")
        return

    # Phase 1-2: Scan loop (12 rounds, 5 min apart)
    n_scans = 12
    decisions_made: set[str] = set()
    open_positions = len(get_unresolved_decisions())

    for round_i in range(n_scans):
        round_time = _et_now_str()

        if round_i > 0:
            print(f"\n  [{round_time}] Scan {round_i + 1}/{n_scans}")
            # Wait 5 minutes between scans (check every 15s for early exit)
            for _ in range(20):
                await asyncio.sleep(15)
                now = _et_dt()
                # Stop scanning after 10:30am ET
                if now.hour >= 10 and now.minute >= 30:
                    break
        else:
            print(f"\n  [{round_time}] Scan {round_i + 1}/{n_scans}")

        for display_name, yahoo_ticker in TICKERS:
            if display_name not in deciders or display_name in decisions_made:
                continue

            info = markets[display_name]
            decider = deciders[display_name]

            # Current stock price (yfinance)
            try:
                stock = yf.Ticker(yahoo_ticker)
                recent = stock.history(period="1d", interval="5m")
                current_price = float(recent.iloc[-1]["Close"]) if not recent.empty else decider.open_price
            except Exception:
                current_price = decider.open_price

            # CLOB prices — prefer live_quotes from WebSocket, fall back to REST
            q = _get_quote_from_db(display_name)
            if q and q["yes_ask"] and q["no_ask"]:
                yes_ask = q["yes_ask"]
                yes_bid = q["yes_bid"] or 0
                no_ask = q["no_ask"]
                no_bid = q["no_bid"] or 0
                yes_depth = q["yes_depth"] or _clob_depth(info["yes_token"], "asks")
                no_depth = q["no_depth"] or _clob_depth(info["no_token"], "asks")
            else:
                yes_bid, yes_ask = _clob_price(info["yes_token"])
                no_bid, no_ask = _clob_price(info["no_token"])
                yes_depth = _clob_depth(info["yes_token"], "asks")
                no_depth = _clob_depth(info["no_token"], "asks")

            if not yes_ask or not no_ask:
                print(f"  [{_et_now_str()}] {display_name}: no CLOB prices")
                continue

            # Add scan
            decider.add_scan(
                et_time=round_time, current_price=current_price,
                yes_bid=yes_bid or 0, yes_ask=yes_ask,
                no_bid=no_bid or 0, no_ask=no_ask,
                yes_depth=yes_depth, no_depth=no_depth,
            )

            # Update live quote with latest scan data
            sp = _spread_pct(yes_bid, yes_ask)
            update_live_quote(display_name, yes_bid=yes_bid, yes_ask=yes_ask,
                              no_bid=no_bid, no_ask=no_ask,
                              yes_depth=yes_depth, no_depth=no_depth,
                              spread_pct=sp)

        # Check if we're past the entry window
        now = _et_dt()
        if now.hour >= 10 and now.minute >= 30:
            print(f"  [{_et_now_str()}] Past 10:30am — finalising decisions")
            break

    # Phase 3: Final decisions
    print(f"\n  [{_et_now_str()}] === FINALISING DECISIONS ===\n")

    for display_name in deciders:
        if display_name in decisions_made:
            continue
        decider = deciders[display_name]
        decision = decider.decide()
        _handle_decision(display_name, markets[display_name],
                         gaps[display_name], decision, open_positions)
        if decision and decision.is_buy:
            open_positions += 1

    store_notification("info", None,
                       f"Scan complete. {sum(1 for d in deciders.values() if d.decide().is_buy)}/{len(deciders)} actionable")
    print(f"\n  [{_et_now_str()}] === SCAN CYCLE END ===\n")


def _get_quote_from_db(ticker: str) -> dict | None:
    """Read latest quote from live_quotes table."""
    from database.db import _conn
    try:
        with _conn() as c:
            row = c.execute("SELECT * FROM live_quotes WHERE ticker = ?", (ticker,)).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def _handle_decision(display_name: str, market: dict, gap_pct: float,
                     decision, open_positions: int):
    """Log, notify, and store a scan decision."""
    from database.db import store_decision

    gap_bps = gap_pct * 10000 if gap_pct else None

    if decision is None or not decision.is_buy:
        reason = decision.reason if decision else "no decision"
        print(f"  [{_et_now_str()}] {display_name}: SKIP ({reason})")
        store_notification("scan", display_name, f"SKIP: {reason}")
        return

    # BUY decision
    entry_side = decision.side
    entry_price = decision.price
    edge = decision.edge
    conv = decision.conviction

    # Price sanity: reject garbage prices from after-hours CLOB
    if entry_price is not None and (entry_price < 0.01 or entry_price > 0.99):
        print(f"  [{_et_now_str()}] {display_name}: SKIP (implausible price ${entry_price:.4f})")
        store_notification("scan", display_name, f"SKIP: implausible price ${entry_price:.4f}")
        return

    # Compute position size via Kelly
    from engine.sizer import compute_position_size
    pos = compute_position_size(decision.win_rate, entry_price) if decision.win_rate else 100
    if pos <= 0:
        print(f"  [{_et_now_str()}] {display_name}: SKIP (Kelly: WR={decision.win_rate:.0%} insufficient)")
        store_notification("info", display_name, f"Kelly skip: WR={decision.win_rate:.0%} price=${entry_price:.2f}")
        return

    print(f"  [{_et_now_str()}] {display_name}: >>> BUY {entry_side} @ ${entry_price:.2f} "
          f"edge={edge*100 if edge else 0:.1f}% conviction={conv} size=${pos:.0f} <<<")

    # macOS notification
    _notify(f"GAP BOT: BUY {display_name}",
            f"{entry_side} @ ${entry_price:.2f} | edge={edge*100 if edge else 0:.1f}% | ${pos:.0f}")

    # Store in DB
    store_notification("entry", display_name,
                       f"BUY {entry_side} @ ${entry_price:.2f} edge={edge*100:.1f}% pos=${pos:.0f}")
    store_decision(
        date_str=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        ticker=display_name, slug=market["slug"],
        decision=f"BUY {entry_side} ({decision.reason})",
        gap_bps=gap_bps, entry_side=entry_side,
        entry_price=entry_price, position_size=pos,
        expected_edge=edge,
    )


# ── Main Loop ────────────────────────────────────────────────────────────────


async def run_monitor():
    """Full monitor: WebSocket + scan cycle concurrently."""
    init_db()
    print(f"\n{'='*60}")
    print(f"  GAP BOT MONITOR — {_et_now_str()}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    print(f"{'='*60}")

    # Discover markets
    print(f"\n  [{_et_now_str()}] Discovering today's markets...")
    token_map = find_today_markets()
    if not token_map:
        print("  No markets found. Exiting.")
        sys.exit(1)
    print(f"  Found {len(token_map)} markets:")
    for info in token_map.values():
        print(f"    {info['ticker']:6s}: YES={info['yes_token'][:20]}...")

    # Run WebSocket + scan cycle concurrently
    ws_task = asyncio.create_task(websocket_loop(token_map))
    scan_task = asyncio.create_task(scan_cycle(token_map))

    try:
        await asyncio.gather(ws_task, scan_task)
    except KeyboardInterrupt:
        print(f"\n  [{_et_now_str()}] Monitor stopped by user.")
    except Exception as e:
        print(f"\n  [{_et_now_str()}] Monitor error: {e}")
    finally:
        ws_task.cancel()
        scan_task.cancel()


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Live gap bot monitor")
    parser.add_argument("--stream", action="store_true", help="WebSocket only (no scan)")
    parser.add_argument("--scan", action="store_true", help="One scan cycle only")
    args = parser.parse_args()

    if args.stream:
        # WebSocket streaming only
        init_db()
        token_map = find_today_markets()
        if not token_map:
            print("No markets found.")
            sys.exit(1)
        asyncio.run(websocket_loop(token_map))
    elif args.scan:
        # One scan cycle, no WebSocket
        init_db()
        token_map = find_today_markets()
        if not token_map:
            print("No markets found.")
            sys.exit(1)
        asyncio.run(scan_cycle(token_map))
    else:
        # Full monitor
        try:
            asyncio.run(run_monitor())
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
