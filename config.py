"""
Configuration for daily stock gap mispricing bot.

Strategy: Trade daily "Up or Down" binary markets on Polymarket for 9 tickers.
Exploit the gap between market pricing (~50-57¢ at 9:30am regardless of gap size)
and actual close probability. Gap > 0.5% -> buy YES. Gap < -0.5% -> buy NO.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# API KEYS
# ============================================================================

POLYMARKET_PRIVATE_KEY = os.getenv('POLYMARKET_PRIVATE_KEY', '')

# Set to "true" in .env to place real orders. Any other value = dry-run (log only).
LIVE_TRADING = os.getenv('LIVE_TRADING', 'false').lower() == 'true'

# ============================================================================
# TICKERS
# ============================================================================

# (display_name, yahoo_ticker)
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

# Per-ticker GFR exit thresholds — calibrated from full_session_2min.csv WR analysis.
# Shallow threshold: first warning (60% sell). Deep = shallow × 1.6 (90% sell).
# Logic: high-beta tickers can flush -50% intraday and still close in gap direction.
# Re-run tools/validate_gap_mispricing.py periodically as data grows.
#
# WR at [-0.8, -0.5) zone that drove these values:
#   SPX 2.7%, AMZN 38%, NFLX 44%, AAPL 47%, META 50%  → keep -0.5
#   MSFT 68%, NVDA 70%, TSLA 71%                        → raise to -1.0
#   GOOGL 84%                                            → raise to -1.5
# GFR exit thresholds — flat defaults until ≥50 first-trigger events per ticker.
# Per-ticker raises attempted May 24 but reverted: earlier 68-84% WR finding was
# inflated by repeated zone hits (avg 7.9 per day). First-trigger dedup gives
# n≈10 per ticker — insufficient for per-ticker calibration.
# Revisit when live data accumulates enough trigger events.
TICKER_GFR_EXIT_SHALLOW: dict[str, float] = {t: -0.5 for t, _ in TICKERS}
TICKER_GFR_EXIT_DEEP:    dict[str, float] = {t: -0.8 for t, _ in TICKERS}

# NO entry GFR gate — skip if stock has bounced past yesterday's close at entry time.
# GFR < -0.3 means the stock is 30%+ of gap-size above prev_close when you try to enter.
# Data: filtered NO WR = 83.6% (n=128) vs unfiltered 76.0% (n=192).
# Skipped sessions (GFR < -0.3): only 60.9% WR — structural edge survives but badly eroded.
GFR_NO_ENTRY_MIN = -0.3

# Limit order repricing — entry orders only.
# If a buy order sits unfilled past ORDER_TTL_SEC and the signal is still GO,
# cancel and resubmit at the current ask. Cap retries so we don't chase a
# moving market indefinitely (each attempt = ~2 min, so 3 = ~6 min max chase).
MAX_REPRICE_ATTEMPTS = 3
REPRICE_DRIFT_THRESHOLD = 0.02   # reprice if ask has moved more than 2¢ from last order price

# GFR exit fractions by trade direction — calibrated from tools/backtest_sell_fractions.py
# (May 24 2026, 1,149 sessions). Key insight: GFR signal is asymmetric by direction.
#   YES WR at gfr < -0.5: 18%  → exit fully on first GFR signal
#   NO  WR at gfr < -0.5: 43%  → GFR dip is noise; time exits handle position
# P&L gain: YES +0.6%, NO +8.1% (largest single improvement in the exit model).
GFR_EXIT_FRAC_YES_SHALLOW = 1.00   # full exit when gfr < -0.5 for YES trades
GFR_EXIT_FRAC_YES_DEEP    = 0.00   # deep trigger unused (subsumed by shallow=100%)
GFR_EXIT_FRAC_NO_SHALLOW  = 0.00   # GFR exits disabled for NO trades
GFR_EXIT_FRAC_NO_DEEP     = 0.00   # GFR exits disabled for NO trades

# NO trade intraday protection — choppy session handling.
# YES trades have GFR exits to protect against reversals; NO trades have none.
# These two mechanisms fill that gap without touching YES trade logic.
#
# Fix A — Profit lock: when NO token has gained ≥12¢ from entry, sell half.
#   Threshold from calibration data: median intraday peak gain before first bounce ≈ 10–13¢.
#   Captures the 11:30am win without waiting for a full-session time exit.
NO_PROFIT_LOCK_GAIN = 0.12    # gain in cents from entry_price to trigger partial exit
NO_PROFIT_LOCK_FRAC = 0.50    # sell 50% of position on profit lock
#
# Fix B — Trailing stop: after the NO token has appreciated meaningfully and then
#   retraces ≥8¢ from its session peak, exit the remaining position.
#   Only activates when peak is ≥10¢ above entry (prevents triggering on flat/losing trades).
NO_TRAIL_STOP_DROP  = 0.08    # exit remaining when token falls ≥8¢ from peak
NO_TRAIL_STOP_FRAC  = 1.00    # exit full remaining position
NO_TRAIL_MIN_PEAK   = 0.10    # minimum peak appreciation above entry to arm the trail stop

# Per-ticker beta vs SPX — used for conviction threshold scaling
# Formula: confirm_pct = 0.15 + 0.15 * beta
# Higher beta → more intraday noise → more confirmations needed for STRONG conviction
TICKER_BETA = {
    "SPX":   1.0,
    "NVDA":  1.5,
    "TSLA":  2.0,
    "AAPL":  1.2,
    "AMZN":  1.3,
    "GOOGL": 1.1,
    "META":  1.4,
    "MSFT":  1.1,
    "NFLX":  1.3,
}

# Per-ticker gap threshold — scaled by beta so high-volatility tickers require a
# larger overnight gap before the signal is meaningful.
# Rationale: a 0.5% gap on TSLA (avg daily range ~2%) is inside noise; the same
# 0.5% on SPX (avg daily range ~0.5%) is a full-sigma event.
# Formula: threshold = BASE_GAP_THRESHOLD * beta
# NFLX override: Polymarket data too thin (inconsistent) below 1.5%.
BASE_GAP_THRESHOLD = 0.005  # baseline for β=1.0 (SPX)
TICKER_GAP_THRESHOLD: dict[str, float] = {
    ticker: round(BASE_GAP_THRESHOLD * beta, 4)
    for ticker, beta in TICKER_BETA.items()
}
TICKER_GAP_THRESHOLD["NFLX"] = 0.015  # data-driven override

# ============================================================================
# TRADING PARAMETERS
# ============================================================================

# Bankroll
BANKROLL_USD = float(os.getenv('BANKROLL_USD', 5000))

# Position Sizing — Kelly Criterion
# f* = (p × b - q) / b, then clamp to [MIN, MAX]
# Applied to full bankroll, not per-slot allocation.
KELLY_FRACTION = 0.25           # quarter-Kelly (conservative)
MAX_POSITION_SIZE = 100.0       # Hard cap: 2% of $5K bankroll
                                # 6 positions × $100 = $600 = 12% max exposure
                                # (previously $200 × 6 = $1,200 = 24% — violated stated 12% limit)
MIN_POSITION_SIZE = 20.0        # Below this, skip (not worth the trade)

POSITION_SIZE_USD = 100         # Fallback if Kelly can't compute
MAX_POSITIONS_SIMULTANEOUS = 6  # Max 6 open positions (6 × $100 = $600 = 12% of $5K)
MAX_POSITIONS_PER_DAY = 12      # Max 12 trades per day (capital recycling)

# Loss limits
MAX_LOSS_PER_TRADE_PCT = 1.0   # 100% (binary trade — you can lose it all)
MAX_LOSS_PER_DAY_USD = 500     # Stop trading for the day after losing $500

# ============================================================================
# ENTRY RULES — Gap Mispricing
# ============================================================================

# Gap thresholds
GAP_THRESHOLD_YES = BASE_GAP_THRESHOLD    # SPX baseline — use TICKER_GAP_THRESHOLD for per-ticker
GAP_THRESHOLD_NO = -BASE_GAP_THRESHOLD   # SPX baseline — use TICKER_GAP_THRESHOLD for per-ticker

# Entry timing (ET)
ENTRY_WINDOW_START = "09:35"   # Start scanning at 9:35am ET (first 5m candle closes)
ENTRY_WINDOW_END = "14:00"     # Stop entering at 2:00pm ET (edge decays)
MARKET_CLOSE_HOUR_ET = 16      # 4:00 PM ET market close

# Per-ticker optimal entry windows (ET)
# Format: "HH:MM" — ticker is only actionable if current time is within its window.
# Derived from historical edge decay analysis (lesson.md section 14).
ENTRY_WINDOWS = {
    # Entry window extended to 14:00 with tiered edge floors:
    #   09:35–10:30 → 5% floor (standard)
    #   10:30–12:00 → 8% floor (late-entry)
    #   12:00–13:30 → 15% floor (tier 1)
    #   13:30–14:00 → 20% floor (tier 2)
    "SPX":   ("09:35", "14:00"),
    "NVDA":  ("09:35", "14:00"),
    "TSLA":  ("09:55", "14:00"),
    "AMZN":  ("09:35", "14:00"),
    "AAPL":  ("09:35", "14:00"),
    "GOOGL": ("09:35", "14:00"),
    "META":  ("09:35", "14:00"),
    "MSFT":  ("09:35", "14:00"),
    "NFLX":  ("09:35", "14:00"),
}

# After this time, no new entries regardless of signal (freeze window)
ENTRY_FREEZE_TIME = "14:00"

# Tighter thresholds for late entries (after 10:30am — less ladder time)
LATE_ENTRY_MAX_SPREAD_PCT = 10.0   # vs 15% standard
LATE_ENTRY_MIN_EDGE = 0.08         # vs 5% standard (NEUTRAL_EDGE_MIN)
LATE_ENTRY_CUTOFF = "10:30"        # entries after this time use late thresholds

# Price filters
MIN_YES_PRICE = 0.40   # Minimum YES price to consider (below this, too much edge extracted)
MAX_YES_PRICE = 0.70   # Maximum YES price to consider (above this, too little edge)
MAX_SPREAD_PCT = 10.0  # 10% max bid-ask spread (exits into wider spreads lose edge)

# Book depth (minimum contracts on top level)
MIN_BOOK_DEPTH = 1000  # Minimum 1,000 contracts on entry side

# Edge thresholds by conviction bucket (applied by scanner.py)
# STRONG → gap confirmed, use GAP_EDGE_MIN (lowest threshold)
# MODERATE → no clear trend, use NEUTRAL_EDGE_MIN
# WEAK → gap fading, use FADE_EDGE_MIN (must be high — betting against the gap)
GAP_EDGE_MIN = 0.03      # 3% min edge for gap-confirmed trades
NEUTRAL_EDGE_MIN = 0.05  # 5% min edge when trend is unclear
FADE_EDGE_MIN = 0.15     # 15% min edge for fade trades (betting against the gap)

# Scanner timing
MIN_SCANS_FOR_DECISION = 4  # Minimum 5-min snapshots before making a call

# ============================================================================
# EXIT RULES
# ============================================================================

# Target exit
TARGET_EXIT_PRICE = 0.90  # Sell at $0.90 (edge above this is too thin)

# Time exit
TIME_EXIT = "14:00"  # Exit all remaining at 2pm ET market price (before decay kills edge)

# Canary stop (stock price monitoring)
CANARY_ENABLED = True
CANARY_POLL_INTERVAL_SEC = 30     # Poll stock price every 30s during trading
CANARY_DROP_PCT = 0.005           # 0.5% drop in 5 min triggers sell
CANARY_WINDOW_SEC = 300           # 5-minute window for drop detection

# Exit ladder — CLOB exit price discount
# The paper trade estimates token price from stock path. In reality, you sell at the
# CLOB bid (not the midpoint). This discount approximates the gap between mid and bid.
# 0.05 = 5% haircut on every estimated exit price. Conservative for 10% avg spread.
CLOB_EXIT_DISCOUNT = 0.05

# Pre-placed stop levels (GTC limit orders placed at entry)
STOP_LEVELS = [0.85, 0.70, 0.50]  # Sell if price drops to these levels

# ============================================================================
# SETTLEMENT MODEL ENTRY THRESHOLDS
# ============================================================================

# Direction gate: enter YES when model P(YES) ≥ this; enter NO when P(YES) ≤ 1 - this.
# At 0.55, both YES and NO require the model to predict at least 55% probability.
# The dead-zone 0.45–0.55 is skipped — model isn't confident enough to trade.
SETTLEMENT_YES_THRESHOLD = 0.55

# ============================================================================
# SPRT ENTRY (retained for reference — no longer used in live strategy)
# ============================================================================

# Replaced by model-driven direction + settlement probability gate.
# Kept here so any legacy code that imports these symbols doesn't break.
SPRT_YES_PARAMS: dict[str, tuple[float, float]] = {
    "AMZN": (0.430, 0.282),
    "TSLA": (0.257, 0.194),
}
SPRT_ENTER_LR = 5.0
SPRT_ABORT_LR = 0.2

# ============================================================================
# VIX REGIME
# ============================================================================

# Pulled once at 9:35am ET via yfinance — VIX open vs previous day's close.
# Used as (a) directional prior and (b) edge threshold adjustment in _check_entry().

VIX_HIGH_THRESHOLD = 20.0        # VIX close > 20 → high-vol regime

# VIX change = today's open − yesterday's close (computed at session start).
# Bullish zone: VIX quietly declining → 88.4% YES-WR on gap-up days (n=95).
# Bearish zone: VIX spiking → gap-up wins drop sharply; favor NO setups.
VIX_CHANGE_BULLISH_LO  = -2.0    # lower bound of high-confidence YES zone
VIX_CHANGE_BULLISH_HI  = -0.5    # upper bound of high-confidence YES zone
VIX_CHANGE_BEARISH_MIN =  0.5    # VIX rising above this → penalize YES entries

# Edge threshold adjustments applied inside _check_entry().
VIX_BULLISH_EDGE_DISCOUNT = 0.02  # lower edge_min by 2% on bullish VIX signal
VIX_BEARISH_EDGE_PENALTY  = 0.03  # raise  edge_min by 3% for YES when VIX rising

# ============================================================================
# DAY-OF-WEEK ADJUSTMENTS
# ============================================================================

# Day-of-week WR from full_session_analysis.py (Polymarket-specific):
#   Mon: 74.1%  Tue: 64.0%  Wed: 71.2%  Thu: 58.7%  Fri: 38.5%  (gap-up)
import datetime as _dt
THURSDAY_EDGE_MIN   = 0.10        # vs standard 5% NEUTRAL / 8% late-entry
THURSDAY_CONVICTION = "STRONG"    # only STRONG conviction trades on Thursdays
FRIDAY_SKIP_GAP_UP  = False       # Data too thin (n≈9 events) to hard-block — use higher thresholds instead
FRIDAY_EDGE_MIN     = 0.10        # Same as Thursday until n≥50 Friday events to re-evaluate

def is_thursday() -> bool:
    return _dt.datetime.now().weekday() == 3

def is_friday() -> bool:
    return _dt.datetime.now().weekday() == 4

# ============================================================================
# PRIORITY RULES
# ============================================================================

# SPX gap-down gets priority (best edge: 12-14% NO edge, ~80% WR)
SPX_PRIORITY = True

# NFLX deprioritized (weakest signal)
NFLX_MIN_GAP = 0.015  # Only trade NFLX if gap > 1.5%

# ============================================================================
# PORTFOLIO LIMITS
# ============================================================================

MIN_RESERVE_PCT = 0.80  # Keep 80% in reserve at all times
MAX_CATEGORY_EXPOSURE_PCT = 0.12  # Max 12% total capital deployed

# ============================================================================
# MONITORING SETTINGS
# ============================================================================

BOOK_POLL_INTERVAL_SEC = 60       # Poll CLOB books every 60 seconds
MARKET_HOURS_START = "09:30"      # ET
MARKET_HOURS_END = "16:00"        # ET

# ============================================================================
# POLYMARKET API
# ============================================================================

POLYMARKET_HOST = "https://clob.polymarket.com"
POLYMARKET_CHAIN_ID = 137  # Polygon mainnet
GAMMA_API_HOST = "https://gamma-api.polymarket.com"

# Aliases used in server.py and other consumers
CLOB_API  = POLYMARKET_HOST
GAMMA_API = GAMMA_API_HOST

# ============================================================================
# SLUG HELPERS (used in server.py to build Polymarket market slugs)
# ============================================================================

MONTH_NAMES: list[str] = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
SLUG_OVERRIDES: dict[str, str] = {"^GSPC": "spx"}

# ============================================================================
# INTRADAY REVERSAL TRADES
# ============================================================================

# Per-ticker NO win rate when a gap-UP day fully reverses (GFR first crosses -1.0).
# Source: tools/reversal_analysis.py — 338 reversal events, Oct 2025–May 2026.
# Used in _check_reversal_entry() instead of the stale cache no_wr (which is
# 1 − gap_up_yes_wr ≈ 0.17 and meaningless for this scenario).
REVERSAL_NO_WR: dict[str, float] = {
    "NVDA":  0.848,
    "AAPL":  0.711,
    "GOOGL": 0.692,
    "AMZN":  0.686,
    "TSLA":  0.667,
    "SPX":   0.658,
    "NFLX":  0.609,
    "META":  0.606,
    "MSFT":  0.595,
}
REVERSAL_NO_WR_DEFAULT = 0.67   # overall average; fallback for unknown tickers

# Edge floor for reversal entries — higher than standard because this is a
# counter-direction bet with ~7 months of calibration data (vs 5-year gap priors).
REVERSAL_EDGE_MIN = 0.12        # 12% floor; standard early-session floor is 5%

# ============================================================================
# BAYESIAN WR ADJUSTMENT
# ============================================================================

BAYES_LAMBDA = 0.15        # WR adjustment per GFR unit when stock is above prev_close
BAYES_STEEP_LAMBDA = 0.35  # WR adjustment per GFR unit once stock crosses prev_close (GFR < -1.0)
                           # Two-slope formula: shallow above the breakpoint, steep below.
                           # Calibrated so base_wr=0.75 at GFR=-2.12 yields adj_wr≈21%,
                           # matching observed market pricing at extreme reversals.

# ============================================================================
# LOGGING
# ============================================================================

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', './logs/bot.log')

# ============================================================================
# DATABASE
# ============================================================================

DATABASE_PATH = os.getenv('DATABASE_PATH', './data/polymarket.db')

# ============================================================================
# FEES
# ============================================================================

TRADING_FEE_PCT = 0.01  # 1% protocol fee at settlement (maker/taker)

if __name__ == "__main__":
    from engine.sizer import validate_config
    print("=" * 50)
    print("Config — Daily Stock Gap Mispricing Bot")
    print("=" * 50)
    print(f"Tickers: {[t[0] for t in TICKERS]}")
    print(f"Bankroll: ${BANKROLL_USD}")
    print(f"Position: ${POSITION_SIZE_USD}")
    print(f"Max concurrent: {MAX_POSITIONS_SIMULTANEOUS}")
    print(f"Gap threshold: YES > {GAP_THRESHOLD_YES*100:.1f}%, NO < {GAP_THRESHOLD_NO*100:.1f}%")
    print(f"Entry window: {ENTRY_WINDOW_START} - {ENTRY_WINDOW_END} ET")
    print(f"Time exit: {TIME_EXIT} ET")
    print(f"Canary stop: {'ON' if CANARY_ENABLED else 'OFF'}")
    print()
    validate_config()
