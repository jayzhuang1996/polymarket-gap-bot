"""
Configuration and constants for Polymarket trading bot
Task 1.1.2: Create config.py with environment variables
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# API KEYS (Load from environment)
# ============================================================================

POLYMARKET_PRIVATE_KEY = os.getenv('POLYMARKET_PRIVATE_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# ============================================================================
# TRADING PARAMETERS
# ============================================================================

# Bankroll
BANKROLL_USD = float(os.getenv('BANKROLL_USD', 1000))  # Phase 1: Start small

# Position Sizing (Phase 1: Fixed sizes)
MIN_POSITION_SIZE = 100  # $100 minimum
MAX_POSITION_SIZE = 200  # $200 maximum (Phase 1)
DEFAULT_POSITION_SIZE = 200  # Fixed size for Phase 1

# Stop-Loss (Phase 1: Fixed)
STOP_LOSS_PCT = 0.10  # 10% fixed stop-loss

# ============================================================================
# FILTER THRESHOLDS
# ============================================================================

# Price Range
PRICE_MIN = 0.92  # 92% minimum certainty
PRICE_MAX = 0.97  # 97% maximum certainty

# Liquidity Requirements
MIN_VOLUME_24H = 50000  # $50k daily volume
MIN_BID_DEPTH = 20000   # $20k bid depth
MIN_LIQUIDITY_RATIO = 20  # 20x position size (updated from 10x)

# Spread
MAX_SPREAD_PCT = 0.03  # 3% max spread

# Settlement Window
MIN_SETTLEMENT_HOURS = 6  # Minimum 6 hours to settlement
MAX_SETTLEMENT_DAYS = 7   # Maximum 7 days to settlement

# Quality Scores
MIN_RESOLUTION_CLARITY = 8  # 8/10 minimum
MIN_EVENT_FINALITY = 8      # 8/10 minimum

# Profit Threshold
MIN_TRUE_PROFIT_PCT = 0.04  # 4% after fees/slippage

# ============================================================================
# PORTFOLIO LIMITS
# ============================================================================

MAX_POSITIONS = 3  # Phase 1: Max 3 concurrent positions
MAX_CATEGORY_EXPOSURE_PCT = 0.40  # 40% per category
MAX_SAME_DAY_SETTLEMENT = 3  # Max 3 settling same day
MIN_RESERVE_PCT = 0.20  # 20% always in reserve

# ============================================================================
# MONITORING SETTINGS
# ============================================================================

# Polling Intervals (seconds)
MARKET_POLL_INTERVAL_SEC = 300  # 5 minutes
PRICE_CHECK_INTERVAL_SEC = 60   # 1 minute
NEWS_CHECK_INTERVAL_SEC = 900   # 15 minutes (news)

# Alert Thresholds
SUDDEN_DROP_THRESHOLD_PCT = 0.03  # 3% sudden drop
LIQUIDITY_DECAY_WARNING_PCT = 0.50  # 50% decay warning
LIQUIDITY_DECAY_URGENT_PCT = 0.70   # 70% decay urgent

# ============================================================================
# DATABASE
# ============================================================================

DATABASE_PATH = os.getenv('DATABASE_PATH', './data/polymarket.db')

# ============================================================================
# LOGGING
# ============================================================================

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', './logs/bot.log')

# ============================================================================
# POLYMARKET API
# ============================================================================

POLYMARKET_HOST = "https://clob.polymarket.com"
POLYMARKET_CHAIN_ID = 137  # Polygon mainnet

# ============================================================================
# FEES & SLIPPAGE
# ============================================================================

TRADING_FEE_PCT = 0.02  # 2% trading fee
ESTIMATED_SLIPPAGE_PCT = 0.005  # 0.5% estimated slippage


# ============================================================================
# VALIDATION
# ============================================================================

def validate_config():
    """Validate that required environment variables are set"""

    errors = []

    # Check API keys (optional for now, required later)
    if not POLYMARKET_PRIVATE_KEY:
        errors.append("⚠️  POLYMARKET_PRIVATE_KEY not set (required for trading)")

    if not ANTHROPIC_API_KEY:
        errors.append("⚠️  ANTHROPIC_API_KEY not set (required for AI decisions)")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        errors.append("⚠️  TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set (required for alerts)")

    # Validate ranges
    if PRICE_MIN >= PRICE_MAX:
        errors.append("❌ PRICE_MIN must be less than PRICE_MAX")

    if MIN_POSITION_SIZE > MAX_POSITION_SIZE:
        errors.append("❌ MIN_POSITION_SIZE must be less than MAX_POSITION_SIZE")

    if errors:
        print("\n🔧 Configuration Issues:")
        for error in errors:
            print(f"  {error}")
        print("\n📝 See .env.example for required variables\n")
    else:
        print("✅ Configuration valid!")

    return len(errors) == 0


if __name__ == "__main__":
    """Test configuration loading"""

    print("=" * 60)
    print("Configuration Test")
    print("=" * 60)

    # Show loaded config (safe values only)
    print(f"\n💰 Trading Config:")
    print(f"  Bankroll: ${BANKROLL_USD:,.0f}")
    print(f"  Position Size: ${DEFAULT_POSITION_SIZE}")
    print(f"  Max Positions: {MAX_POSITIONS}")
    print(f"  Stop Loss: {STOP_LOSS_PCT:.0%}")

    print(f"\n🎯 Filters:")
    print(f"  Price Range: ${PRICE_MIN} - ${PRICE_MAX}")
    print(f"  Min Volume: ${MIN_VOLUME_24H:,}")
    print(f"  Min Liquidity Ratio: {MIN_LIQUIDITY_RATIO}x")

    print(f"\n🔑 API Keys:")
    if POLYMARKET_PRIVATE_KEY:
        print(f"  Polymarket: ...{POLYMARKET_PRIVATE_KEY[-4:]}")
    else:
        print(f"  Polymarket: Not set")

    if ANTHROPIC_API_KEY:
        print(f"  Anthropic: ...{ANTHROPIC_API_KEY[-4:]}")
    else:
        print(f"  Anthropic: Not set")

    if TELEGRAM_BOT_TOKEN:
        print(f"  Telegram: ...{TELEGRAM_BOT_TOKEN[-10:]}")
    else:
        print(f"  Telegram: Not set")

    print(f"\n📂 Paths:")
    print(f"  Database: {DATABASE_PATH}")
    print(f"  Logs: {LOG_FILE}")

    print("\n" + "=" * 60)
    validate_config()
    print("=" * 60)
