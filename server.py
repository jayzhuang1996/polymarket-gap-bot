"""Gap Bot — entrypoint.

Wires startup, background tasks, and the FastAPI app.
All trading logic lives in engine/; all HTTP/WS handlers in api/.

Usage:  python server.py  →  http://localhost:8000
"""

import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

import engine.state as state
from config import TICKERS
from database.db import init_db
from database.wr_store import load_base_wr
from engine.data_feed import discover_markets, calc_gaps, stock_price_loop
from engine.clob_feed import polymarket_loop, initial_rest_fallback, periodic_rest_poll
from engine.session import trading_session_loop, reconcile_session_state
from engine.order_manager import OrderManager
from api.routes import router as api_router
from api.ws import router as ws_router, broadcast_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    state.order_manager = OrderManager(private_key=os.getenv("POLYMARKET_PRIVATE_KEY", ""))
    print("Starting up...")

    markets = await discover_markets()
    state.market_list = markets
    print(f"  Discovered {len(markets)} markets")

    for m in markets:
        state.token_map[m["yes_token"]] = {"ticker": m["ticker"], "side": "YES"}
        state.token_map[m["no_token"]]  = {"ticker": m["ticker"], "side": "NO"}

    gap_data = calc_gaps()
    for ticker, (bps, open_p, prev_p) in gap_data.items():
        state.current_quotes.setdefault(ticker, {"ticker": ticker})
        state.current_quotes[ticker].update({
            "gap_bps":    bps,
            "open_price": open_p,
            "prev_close": prev_p,
        })
    print(f"  Gaps: {len(gap_data)}/{len(TICKERS)} tickers")

    for display, _yahoo in TICKERS:
        gap_up = (state.current_quotes.get(display, {}).get("gap_bps") or 0) > 0
        yes_wr, no_wr, _obs = load_base_wr(display, gap_up)
        state.wr_cache[display] = (yes_wr, no_wr)
    print(f"  WR cache: {len(state.wr_cache)} tickers")

    reconcile_session_state()

    asyncio.create_task(initial_rest_fallback(), name="rest-fallback")
    asyncio.create_task(polymarket_loop(),        name="polymarket-ws")
    asyncio.create_task(periodic_rest_poll(),     name="periodic-rest")
    asyncio.create_task(broadcast_worker(),       name="broadcast")
    asyncio.create_task(stock_price_loop(),       name="stock-prices")
    asyncio.create_task(trading_session_loop(),   name="trading-session")
    port = int(os.environ.get("PORT", 8001))
    print(f"  Server ready → http://localhost:{port}\n")

    yield


app = FastAPI(title="Gap Bot Dashboard", lifespan=lifespan)
app.include_router(api_router)
app.include_router(ws_router)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
