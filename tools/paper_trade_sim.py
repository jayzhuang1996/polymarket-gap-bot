"""
May 22 Paper Trade Simulation
Uses actual scraped CLOB trade data + yfinance stock data + engine/scanner.py + engine/exit_model.py

Usage: python tools/paper_trade_sim.py [--date YYYY-MM-DD]
"""
import sys
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from engine.scanner import MultiScanDecider
from engine.exit_model import estimate_token_price
from database.wr_store import load_base_wr
from config import (
    TICKERS, ENTRY_WINDOWS, MIN_BOOK_DEPTH,
    MAX_POSITION_SIZE,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ── May 22 intraday GFR path (from yfinance 5m bars) ─────────────────────────
# GFR = (price - open) / (open - prev_close)
# Positive = gap holding, negative = gap fading

STOCK_DATA = {
    "SPX":   {"gap_bps": +31,  "open": 7468.82, "prev": 7446.05, "close": 7474.07,
              "gfr_10_00": 0.10, "gfr_10_30": 0.18, "gfr_14_00": 0.23, "close_up": True},
    "NVDA":  {"gap_bps": +64,  "open": 220.90, "prev": 219.50, "close": 215.25,
              "gfr_10_00": -0.15, "gfr_10_30": -0.80, "gfr_14_00": -4.04, "close_up": False},
    "TSLA":  {"gap_bps": +118, "open": 422.67, "prev": 417.75, "close": 425.95,
              "gfr_10_00": 0.35, "gfr_10_30": 0.50, "gfr_14_00": 0.67, "close_up": True},
    "AAPL":  {"gap_bps": +35,  "open": 306.06, "prev": 305.09, "close": 308.88,
              "gfr_10_00": 0.50, "gfr_10_30": 0.80, "gfr_14_00": 2.91, "close_up": True},
    "AMZN":  {"gap_bps": +10,  "open": 268.65, "prev": 268.39, "close": 266.30,
              "gfr_10_00": -1.0, "gfr_10_30": -3.0, "gfr_14_00": -9.0, "close_up": False},
    "GOOGL": {"gap_bps": -9,   "open": 387.33, "prev": 387.66, "close": 383.00,
              "gfr_10_00": -1.5, "gfr_10_30": -3.0, "gfr_14_00": -13.0, "close_up": False},
    "META":  {"gap_bps": +8,   "open": 607.49, "prev": 607.64, "close": 610.37,
              "gfr_10_00": -1.0, "gfr_10_30": -3.0, "gfr_14_00": 19.0, "close_up": True},
    "MSFT":  {"gap_bps": +9,   "open": 419.48, "prev": 419.04, "close": 418.58,
              "gfr_10_00": -0.5, "gfr_10_30": -1.5, "gfr_14_00": -2.0, "close_up": False},
    "NFLX":  {"gap_bps": -34,  "open": 89.02,  "prev": 89.32,  "close": 88.60,
              "gfr_10_00": -1.0, "gfr_10_30": -2.0, "gfr_14_00": -1.4, "close_up": False},
}


def get_clob_snapshot(ticker, et_hour, et_minute):
    """Get approximate YES/NO bid/ask from trade parquet around a given ET time.

    Polymarket trades don't label YES vs NO directly, but YES+NO ≈ $1.
    Trades > $0.50 are YES token trades; < $0.50 are NO token trades.
    Returns (yes_bid, yes_ask, no_bid, no_ask).
    """
    fname = "spx_trades" if ticker.upper() == "SPX" else f"{ticker.lower()}_trades"
    path = DATA_DIR / f"{fname}.parquet"
    if not path.exists():
        return None, None, None, None

    df = pd.read_parquet(path)
    if df.empty:
        return None, None, None, None

    df['et'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)

    target = pd.Timestamp(f'2026-05-22 {et_hour:02d}:{et_minute:02d}:00', tz='US/Eastern')
    window = df[(df['et'] >= (target - pd.Timedelta(minutes=3)).tz_convert('UTC')) &
                (df['et'] <= (target + pd.Timedelta(minutes=2)).tz_convert('UTC'))]

    if window.empty:
        return None, None, None, None

    prices = window['price'].dropna()
    if len(prices) < 3:
        return None, None, None, None

    yes_prices = prices[prices > 0.50]
    no_prices = prices[prices < 0.50]

    def bidask(series):
        if len(series) < 2:
            return None, None
        mid = float(series.median())
        spread = 0.02
        bid = mid * (1 - spread / 2)
        ask = mid * (1 + spread / 2)
        return max(0.01, bid), min(0.99, ask)

    yes_bid, yes_ask = bidask(yes_prices) if len(yes_prices) >= 2 else (None, None)
    no_bid, no_ask = bidask(no_prices) if len(no_prices) >= 2 else (None, None)

    # Complement: if we have YES but not NO, derive NO from YES
    if yes_ask and not no_ask:
        no_ask = round(1.0 - yes_bid, 4) if yes_bid else None
        no_bid = round(1.0 - yes_ask, 4) if yes_ask else None
    if no_ask and not yes_ask:
        yes_ask = round(1.0 - no_bid, 4) if no_bid else None
        yes_bid = round(1.0 - no_ask, 4) if no_ask else None

    return yes_bid, yes_ask, no_bid, no_ask


def simulate_day(target_date=date(2026, 5, 22)):
    """Run scanner + exit model for a given date."""
    print("=" * 72)
    print(f"{target_date.strftime('%B %d, %Y').upper()} — PAPER TRADE SIMULATION")
    print("=" * 72)

    # ── Scanner ──────────────────────────────────────────────────────────
    print("\n── SCANNER DECISIONS ──\n")

    entries = []

    for display, yahoo in TICKERS:
        sd = STOCK_DATA.get(display)
        if not sd:
            continue

        gap_bps = sd['gap_bps']
        gap_pct = gap_bps / 10000.0
        open_p = sd['open']
        prev_p = sd['prev']

        # Base win rate from historical data
        gap_up = gap_bps > 0
        yes_wr, no_wr, n_obs = load_base_wr(display, gap_up)

        decider = MultiScanDecider(display, gap_pct, open_p, prev_p, yes_wr, no_wr)

        # Build scan times 09:35→10:30 at 5-min intervals
        scan_count = 0
        for h in range(9, 11):
            for m in range(0, 60, 5):
                if h == 9 and m < 35:
                    continue
                if h == 10 and m > 30:
                    break

                # Interpolate GFR
                time_minutes = (h - 9) * 60 + m - 35  # minutes since 09:35
                total_window = 55  # 09:35→10:30
                frac = time_minutes / total_window

                gfr_start = sd.get('gfr_10_00', 0.0)
                gfr_end = sd.get('gfr_10_30', gfr_start)
                if h == 9:
                    # 09:35→10:00: interpolate from 0 to gfr_10_00
                    frac_9 = (m - 35) / 25
                    gfr = frac_9 * gfr_start
                else:
                    # 10:00→10:30: interpolate from gfr_10_00 to gfr_10_30
                    frac_10 = m / 30
                    gfr = gfr_start + frac_10 * (gfr_end - gfr_start)

                current_price = open_p + gfr * (open_p - prev_p)

                yes_bid, yes_ask, no_bid, no_ask = get_clob_snapshot(display, h, m)

                if yes_bid is None:
                    yes_bid, yes_ask = 0.48, 0.52
                if no_bid is None:
                    no_bid, no_ask = 0.48, 0.52

                decider.add_scan(
                    f"{h:02d}:{m:02d}", current_price,
                    yes_bid, yes_ask, no_bid, no_ask,
                    yes_depth=50000, no_depth=50000,
                )
                scan_count += 1

        decision = decider.decide(min_scans=4)

        status = "▶ ENTER" if decision.is_buy else "⊙ SKIP"
        print(f"  {display:6s}  gap={gap_bps:+4d} bps  base_wr={yes_wr if gap_up else no_wr:.1%}  "
              f"n={n_obs}  scans={scan_count}  →  {status}")

        if decision.is_buy:
            print(f"           SIDE={decision.side}  "
                  f"entry=¢{decision.price*100:.1f}  "
                  f"edge={decision.edge:.1%}  "
                  f"conviction={decision.conviction}  "
                  f"adj_wr={decision.win_rate:.1%}")
        print(f"           {decision.reason}")
        print()

        entries.append({
            'ticker': display,
            'gap_bps': gap_bps,
            'decision': decision,
            'stock_data': sd,
        })

    # ── Exit & P&L ───────────────────────────────────────────────────────
    print("── EXITS & P&L ──\n")

    total_pnl = 0.0
    wins = 0
    losses = 0

    for e in entries:
        d = e['decision']
        sd = e['stock_data']
        display = e['ticker']

        if not d.is_buy:
            continue

        entry_price = d.price
        position_size = MAX_POSITION_SIZE
        contracts = position_size / entry_price
        side = d.side
        gfr_14 = sd.get('gfr_14_00', 0.0)

        # Estimate token price at 2pm ET using calibrated model
        est_price, source = estimate_token_price("14:00", gfr_14, entry_price)

        exit_value = contracts * est_price
        pnl = exit_value - position_size

        close_up = sd['close_up']
        won = (side == "YES" and close_up) or (side == "NO" and not close_up)
        settle_value = contracts * 1.0 if won else 0.0
        settle_pnl = settle_value - position_size

        print(f"  {display:6s}  {side:4s}  entry=¢{entry_price*100:.1f}  "
              f"ctr={contracts:.0f}  gfr@2pm={gfr_14:+.2f}  "
              f"exit_est=¢{est_price*100:.1f} ({source})")
        print(f"           time_exit P&L: ${pnl:+.2f}  |  "
              f"settle P&L: ${settle_pnl:+.2f}  |  "
              f"{'WIN' if won else 'LOSS'} "
              f"({'▲' if close_up else '▼'}{'UP' if close_up else 'DOWN'})")
        print()

        total_pnl += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    n_trades = wins + losses
    print(f"{'─'*50}")
    print(f"  TOTAL P&L: ${total_pnl:+.2f}")
    print(f"  Wins: {wins}  Losses: {losses}  WR: {wins/n_trades*100:.0f}%" if n_trades else "  No trades executed")
    print(f"  Positions entered: {n_trades}  Max exposure: ${n_trades * MAX_POSITION_SIZE}")
    print(f"{'─'*50}")


if __name__ == "__main__":
    target = date.today()
    if len(sys.argv) > 2 and sys.argv[1] == '--date':
        target = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
    simulate_day(target)
