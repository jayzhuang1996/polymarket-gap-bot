"""
Backtest: what would our strategy have done on May 20, 2026?

Two approaches:
  A. Using CLOB prices from the Gamma events API (bestBid/bestAsk fields).
  B. Using empirical average YES prices from our HF dataset analysis.

Compares both approaches and shows the strategy's P&L.
"""

import sys
import json
import time
import requests
import yfinance as yf
import pandas as pd

sys.path.insert(0, ".")
from config import GAP_THRESHOLD_YES, GAP_THRESHOLD_NO, NFLX_MIN_GAP, TRADING_FEE_PCT

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

TICKERS = [
    ("SPX", "^GSPC"),
    ("NVDA", "NVDA"),
    ("TSLA", "TSLA"),
    ("AAPL", "AAPL"),
    ("AMZN", "AMZN"),
    ("GOOGL", "GOOGL"),
    ("META", "META"),
    ("MSFT", "MSFT"),
    ("NFLX", "NFLX"),
]

# Empirical avg YES prices by gap bucket (from HF dataset analysis)
# Buckets: gap < -2%, -2% to -1%, -1% to -0.5%, -0.5% to +0.5%, +0.5% to +1%, +1% to +2%, > +2%
EMPIRICAL_PRICES = {
    "lt_-2pct": 0.52,
    "-2_to_-1": 0.52,
    "-1_to_-0.5": 0.53,
    "flat": 0.545,
    "+0.5_to_+1": 0.55,
    "+1_to_+2": 0.56,
    "gt_+2pct": 0.57,
}

# Empirical WR by gap bucket
EMPIRICAL_WR = {
    "lt_-2pct": 0.17,
    "-2_to_-1": 0.32,
    "-1_to_-0.5": 0.41,
    "flat": 0.50,
    "+0.5_to_+1": 0.57,
    "+1_to_+2": 0.65,
    "gt_+2pct": 0.76,
}


def gap_bucket(gap_pct):
    """Classify gap into a bucket."""
    if gap_pct is None:
        return None
    if gap_pct < -0.02:
        return "lt_-2pct"
    if gap_pct < -0.01:
        return "-2_to_-1"
    if gap_pct < -0.005:
        return "-1_to_-0.5"
    if gap_pct < 0.005:
        return "flat"
    if gap_pct < 0.01:
        return "+0.5_to_+1"
    if gap_pct < 0.02:
        return "+1_to_+2"
    return "gt_+2pct"


def data_between(df, col, row1, row2):
    """Safely get value from a MultiIndex DataFrame."""
    try:
        return df.loc[row1, (col, ticker)]
    except (KeyError, IndexError):
        return df.loc[row2, (col, ticker)]


# ── Step 1: Download yfinance data ──
print("=" * 80)
print("  BACKTEST: May 20, 2026")
print("=" * 80)

# Download 3 days (May 18-20) to get May 19 close and May 20 open/close
yahoo_symbols = [t[1] for t in TICKERS]
stock = yf.download(yahoo_symbols, start="2026-05-18", end="2026-05-21", progress=False)

results = []

for display_name, yahoo_ticker in TICKERS:
    print(f"\n── {display_name} ({yahoo_ticker}) ──")

    # ── Gap ──
    try:
        prev_close = stock.loc["2026-05-19", ("Close", yahoo_ticker)]
        today_open = stock.loc["2026-05-20", ("Open", yahoo_ticker)]
        today_close = stock.loc["2026-05-20", ("Close", yahoo_ticker)]
        gap_pct = (today_open - prev_close) / prev_close
    except (KeyError, TypeError) as e:
        print(f"  Data error: {e}")
        continue

    gap_bps = gap_pct * 10000
    bucket = gap_bucket(gap_pct)

    # ── Outcome ──
    close_up = today_close > prev_close
    outcome = "UP" if close_up else "DOWN"

    # ── Strategy decision ──
    if gap_pct is not None and GAP_THRESHOLD_NO < gap_pct < GAP_THRESHOLD_YES:
        decision = "SKIP"
        side = None
        reason = f"neutral gap {gap_bps:+.0f} bps"
    elif gap_pct >= GAP_THRESHOLD_YES:
        decision = "BUY YES"
        side = "YES"
        reason = f"gapped higher {gap_bps:+.0f} bps"
    elif gap_pct <= GAP_THRESHOLD_NO:
        decision = "BUY NO"
        side = "NO"
        reason = f"gapped lower {gap_bps:+.0f} bps"
    else:
        decision = "SKIP"
        side = None
        reason = f"no data"

    # ── NFLX deprioritized ──
    if display_name == "NFLX" and side and abs(gap_pct) < NFLX_MIN_GAP:
        decision = "SKIP"
        side = None
        reason = f"NFLX gap {gap_bps:.0f} bps < 150 threshold"

    # ── Estimate entry price ──
    emp_price = EMPIRICAL_PRICES.get(bucket, 0.55)
    if side == "YES":
        entry_price = emp_price
    elif side == "NO":
        entry_price = 1 - emp_price
    else:
        entry_price = None

    # ── Edge ── (1% settlement fee applied, matching scanner.py)
    payout = 1.0 - TRADING_FEE_PCT  # 0.99
    wr = EMPIRICAL_WR.get(bucket, 0.50)
    if side == "YES":
        edge = wr * payout - entry_price
    elif side == "NO":
        edge = (1 - wr) * payout - entry_price
    else:
        edge = None

    # ── P&L ──
    contracts = 100 / entry_price if entry_price and entry_price > 0 else 0
    if side == "YES":
        pnl = round(contracts * (1 - entry_price), 2) if close_up else -100.0
        correct = close_up
    elif side == "NO":
        pnl = round(contracts * (1 - entry_price), 2) if not close_up else -100.0
        correct = not close_up
    else:
        pnl = 0
        correct = None

    result = {
        "ticker": display_name,
        "gap_bps": round(gap_bps, 0),
        "bucket": bucket,
        "side": side or "—",
        "entry": round(entry_price, 2) if entry_price else None,
        "edge_pct": round(edge * 100, 1) if edge else None,
        "outcome": outcome,
        "correct": correct,
        "pnl": pnl,
        "decision": decision,
        "reason": reason,
    }
    results.append(result)

    direction = "higher" if gap_pct >= 0 else "lower"
    print(f"  Gap: {gap_bps:+.0f} bps (gapped {direction})")
    print(f"  Decision: {decision} ({reason})")
    if side:
        print(f"  Entry: ~${entry_price:.2f} (bucket avg), outcome: {outcome}")
        print(f"  Correct: {'✅' if correct else '❌'}  P&L: ${pnl:.2f}")
    else:
        print(f"  Outcome: {outcome} (no trade)")

    time.sleep(0.3)

# ── Summary ──
print(f"\n{'='*80}")
print(f"  SUMMARY — May 20, 2026")
print(f"{'='*80}")

total_pnl = 0
trades = 0
wins = 0
skips = 0

print(f"\n  {'Ticker':<8} {'Gap bps':<10} {'Side':<6} {'Entry':<8} {'Edge':<8} {'Outcome':<10} {'P&L':<10}")
print(f"  {'-'*65}")
for r in results:
    gap_str = f"{r['gap_bps']:.0f}" if r['gap_bps'] else "N/A"
    entry_str = f"${r['entry']:.2f}" if r['entry'] else "—"
    edge_str = f"{r['edge_pct']}%" if r['edge_pct'] else "—"
    pnl_str = f"${r['pnl']:.2f}" if r['pnl'] else "—"

    if r['side'] != "—":
        trades += 1
        total_pnl += r['pnl']
        if r['correct']:
            wins += 1
    else:
        skips += 1

    icon = "✅" if r.get('correct') else "❌" if r['side'] != "—" else "—"
    print(f"  {r['ticker']:<8} {gap_str:<10} {r['side']:<6} {entry_str:<8} {edge_str:<8} {r['outcome']:<10} {pnl_str:<10} {icon}")

print(f"  {'-'*65}")
print(f"  TOTAL: {trades} trades, {wins}W / {trades-wins}L, ${total_pnl:.2f}, "
      f"{wins/trades*100:.0f}% WR" if trades > 0 else "  0 trades")
print()

# Breakdown
print(f"  Trades by direction:")
yes_trades = [r for r in results if r['side'] == 'YES']
no_trades = [r for r in results if r['side'] == 'NO']
if yes_trades:
    yes_pnl = sum(r['pnl'] for r in yes_trades)
    yes_w = sum(1 for r in yes_trades if r['correct'])
    print(f"    YES (stock gapped higher): {len(yes_trades)} trades, {yes_w}W, ${yes_pnl:.2f}")
if no_trades:
    no_pnl = sum(r['pnl'] for r in no_trades)
    no_w = sum(1 for r in no_trades if r['correct'])
    print(f"    NO  (stock gapped lower): {len(no_trades)} trades, {no_w}W, ${no_pnl:.2f}")
print(f"    SKIP (neutral gap): {skips} tickers")
print(f"{'='*80}")
