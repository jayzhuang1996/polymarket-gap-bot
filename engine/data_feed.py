"""External market data — Gamma API discovery, yfinance gaps, Yahoo Finance price loop."""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import yfinance as yf

import engine.state as state
from config import (
    TICKERS, GAMMA_API, CLOB_API, MONTH_NAMES, SLUG_OVERRIDES,
    TRADING_FEE_PCT, BAYES_LAMBDA, BAYES_STEEP_LAMBDA,
)
from engine.strategy import _compute_signal, ET_OFFSET_H
from engine.settlement_model import predict as settlement_predict, is_available as settlement_available


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slug(yahoo_ticker: str) -> str:
    today  = datetime.now(timezone.utc)
    prefix = SLUG_OVERRIDES.get(yahoo_ticker, yahoo_ticker.lower())
    return f"{prefix}-up-or-down-on-{MONTH_NAMES[today.month-1]}-{today.day}-{today.year}"


def _token_id(ticker: str, side: str) -> str | None:
    for m in state.market_list:
        if m["ticker"] == ticker:
            return m["yes_token"] if side == "YES" else m["no_token"]
    return None


# ── Market discovery ───────────────────────────────────────────────────────────

async def discover_markets() -> list[dict]:
    """Fetch today's YES/NO markets from Gamma API for all configured tickers."""
    found: list[dict] = []
    async with httpx.AsyncClient(timeout=15) as c:
        for display, yahoo in TICKERS:
            try:
                resp = await c.get(f"{GAMMA_API}/events?slug={_slug(yahoo)}")
                if resp.status_code != 200:
                    continue
                events = resp.json()
                if not events:
                    continue
                mk = events[0].get("markets", [None])[0]
                if not mk:
                    continue
                raw = mk.get("clobTokenIds", "[]")
                ids = json.loads(raw) if isinstance(raw, str) else (raw or [])
                if len(ids) >= 2:
                    found.append({
                        "ticker":       display,
                        "yes_token":    str(ids[0]).strip(),
                        "no_token":     str(ids[1]).strip(),
                        "condition_id": mk.get("conditionId", ""),
                    })
            except Exception:
                continue
    return found


# ── Gap calculation ────────────────────────────────────────────────────────────

def calc_gaps() -> dict[str, tuple[int, float, float]]:
    """Calculate today's opening gaps via yfinance.

    Returns {ticker: (gap_bps, open_price, prev_close)}.
    """
    gaps: dict[str, tuple[int, float, float]] = {}
    for display, yahoo in TICKERS:
        try:
            hist = yf.Ticker(yahoo).history(period="5d")
            if len(hist) < 2:
                continue
            prev_close = float(hist.iloc[-2]["Close"])
            today_open = float(hist.iloc[-1]["Open"])
            if today_open and prev_close:
                bps = round((today_open - prev_close) / prev_close * 10000)
                gaps[display] = (bps, today_open, prev_close)
        except Exception:
            continue
    return gaps


# ── Stock price loop ───────────────────────────────────────────────────────────

async def _fetch_all_prices_async() -> dict[str, float]:
    """Async Yahoo Finance poll — returns {display_name: last_price}."""
    result: dict[str, float] = {}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; gap-bot/1.0)"}
    async with httpx.AsyncClient(timeout=8, headers=headers) as client:
        for display, yahoo in TICKERS:
            try:
                resp = await client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}",
                    params={"interval": "1m", "range": "1d"},
                )
                if resp.status_code != 200:
                    continue
                meta = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
                price = meta.get("regularMarketPrice") or meta.get("previousClose")
                if price and float(price) > 0:
                    result[display] = float(price)
            except Exception:
                continue
    return result


def _bayesian_adj_wr(base_wr: float, gfr: float, direction_sign: int) -> float:
    """Two-slope Bayesian WR adjustment.

    direction_sign = +1 for gap-up YES trades, -1 for gap-down NO trades.
    signed_gfr > 0  → stock moved in gap direction (thesis holding)
    signed_gfr < 0  → stock fading against gap (thesis at risk)
    signed_gfr < -1 → stock crossed prev_close (regime change: steep penalty)

    Linear above the breakpoint; BAYES_STEEP_LAMBDA below it.
    Prevents the linear formula from showing 63% adj_WR when the stock has
    already crossed prev_close (GFR = -2.12 → adj_wr ≈ 21% with base 0.75).
    """
    signed_gfr = gfr * direction_sign
    if signed_gfr >= -1.0:
        adj = BAYES_LAMBDA * signed_gfr
    else:
        # Stock crossed prev_close: apply steep discount from the -1.0 breakpoint.
        adj = BAYES_LAMBDA * (-1.0) + BAYES_STEEP_LAMBDA * (signed_gfr + 1.0)
    return min(0.95, max(0.05, base_wr + adj))


async def stock_price_loop():
    """Poll Yahoo Finance every 5 seconds; compute GFR, adj_wr, edge, signal and broadcast."""
    payout = 1.0 - TRADING_FEE_PCT

    while True:
        try:
            prices = await _fetch_all_prices_async()
            for display, current_price in prices.items():
                q = state.current_quotes.get(display)
                if not q:
                    continue
                open_p  = q.get("open_price")
                prev_p  = q.get("prev_close")
                gap_bps = q.get("gap_bps") or 0
                if not open_p or not prev_p or open_p == 0 or prev_p == 0:
                    continue

                stock_move_pct  = (current_price - open_p) / open_p * 100
                current_gap_bps = round((current_price - prev_p) / prev_p * 10000)
                gap_d = open_p - prev_p
                gfr   = (current_price - open_p) / gap_d if abs(gap_d) > 0.001 else 0.0
                gfr   = max(-3.0, min(3.0, gfr))

                gap_up         = gap_bps > 50
                gap_dn         = gap_bps < -50
                direction_sign = 1 if gap_up else -1
                yes_wr, no_wr  = state.wr_cache.get(display, (0.55, 0.45))

                if gap_up:
                    adj_wr    = _bayesian_adj_wr(yes_wr, gfr, direction_sign)
                    entry_ask = q.get("yes_ask")
                elif gap_dn:
                    adj_wr    = _bayesian_adj_wr(no_wr, gfr, direction_sign)
                    entry_ask = q.get("no_ask")
                else:
                    adj_wr    = None
                    entry_ask = None

                live_edge = (
                    round(adj_wr * payout - entry_ask, 4)
                    if adj_wr is not None and entry_ask else None
                )
                signal       = _compute_signal(gap_bps, gfr, live_edge)
                gfr_velocity = gfr - state._gfr_snapshot.get(display, gfr)

                # stock_pct_vs_prevclose: where stock is right now vs prev_close (in %)
                # = gap_pct_fraction * 100 * (1 + gfr), same units as training data
                gap_pct_frac    = (open_p - prev_p) / prev_p if prev_p else 0
                stock_pos       = gap_pct_frac * 100.0 * (1.0 + gfr)

                # 30-min momentum: rolling history of stock_pos per ticker (max 20 ticks)
                hist = state._stock_pos_history.setdefault(display, [])
                momentum_30min  = (stock_pos - hist[-15]) if len(hist) >= 15 else 0.0
                hist.append(stock_pos)
                if len(hist) > 20:
                    hist.pop(0)

                settlement_p_win = settlement_edge = None
                if settlement_available():
                    tbf_min  = max(2, int(390 - (
                        datetime.now(timezone.utc).hour * 60 +
                        datetime.now(timezone.utc).minute +
                        ET_OFFSET_H * 60 - 9 * 60 - 30
                    )))
                    tbf_min  = max(2, min(390, tbf_min))
                    yes_vwap = q.get("yes_ask") or 0.5
                    yes_bid  = q.get("yes_bid") or yes_vwap
                    settlement_p_win, settlement_edge = settlement_predict(
                        stock_pct_vs_prevclose=stock_pos,
                        momentum_30min=momentum_30min,
                        tbf_min=tbf_min,
                        yes_vwap=yes_vwap,
                        dow=datetime.now().strftime("%a"),
                        current_token_bid=yes_bid,
                    )

                q.update({
                    "current_price":          round(current_price, 2),
                    "stock_move_pct":         round(stock_move_pct, 2),
                    "current_gap_bps":        current_gap_bps,
                    "gfr":                    round(gfr, 3),
                    "gfr_velocity":           round(gfr_velocity, 4),
                    "stock_pct_vs_prevclose": round(stock_pos, 4),
                    "momentum_30min":         round(momentum_30min, 4),
                    "adj_wr":                 round(adj_wr, 4) if adj_wr is not None else None,
                    "live_edge":              live_edge,
                    "settlement_p_win":       settlement_p_win,
                    "settlement_edge":        settlement_edge,
                    "signal":                 signal,
                })
                if live_edge is not None:
                    q["est_edge"] = live_edge

                state.broadcast_queue.put_nowait(json.dumps({"type": "quote", **q}))

        except Exception:
            pass

        await asyncio.sleep(5)
