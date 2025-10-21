# Technical Reference Guide

*Quick lookup for schemas, APIs, configurations, and formulas*

---

## Database Schemas

### Markets Table
```sql
CREATE TABLE markets (
    market_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    category TEXT,
    yes_price REAL NOT NULL,
    no_price REAL NOT NULL,
    volume_24h REAL DEFAULT 0,
    liquidity_depth REAL DEFAULT 0,
    settlement_date DATETIME,
    resolution_criteria TEXT,
    resolution_clarity_score INTEGER CHECK(resolution_clarity_score >= 0 AND resolution_clarity_score <= 10),
    event_finality_score INTEGER CHECK(event_finality_score >= 0 AND event_finality_score <= 10),
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_markets_price ON markets(yes_price);
CREATE INDEX idx_markets_category ON markets(category);
CREATE INDEX idx_markets_settlement ON markets(settlement_date);
```

### Order Books Table
```sql
CREATE TABLE order_books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    bids JSON NOT NULL,
    asks JSON NOT NULL,
    spread_pct REAL,
    FOREIGN KEY (market_id) REFERENCES markets(market_id)
);

CREATE INDEX idx_orderbooks_market ON order_books(market_id);
CREATE INDEX idx_orderbooks_timestamp ON order_books(timestamp);
```

### Positions Table
```sql
CREATE TABLE positions (
    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    tokens INTEGER NOT NULL,
    position_size_usd REAL NOT NULL,
    stop_loss_price REAL NOT NULL,
    stop_loss_pct REAL NOT NULL,
    take_profit_1_price REAL,
    take_profit_2_price REAL,
    status TEXT CHECK(status IN ('active', 'stopped', 'settled', 'exited')) DEFAULT 'active',
    exit_price REAL,
    exit_time DATETIME,
    pnl_usd REAL,
    pnl_pct REAL,
    liquidity_at_entry REAL,
    volatility_at_entry REAL,
    FOREIGN KEY (market_id) REFERENCES markets(market_id)
);

CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_positions_market ON positions(market_id);
```

### News Events Table
```sql
CREATE TABLE news_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT,
    source TEXT NOT NULL,
    headline TEXT NOT NULL,
    url TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    sentiment_score REAL CHECK(sentiment_score >= -1 AND sentiment_score <= 1),
    FOREIGN KEY (market_id) REFERENCES markets(market_id)
);

CREATE INDEX idx_news_market ON news_events(market_id);
CREATE INDEX idx_news_timestamp ON news_events(timestamp);
```

---

## API Reference

### Polymarket API (py-clob-client)

**Base URL**: `https://clob.polymarket.com`

**Authentication**:
- Private key (Polygon wallet) stored in environment variable
- Format: `0x...` (64 hex characters)

**Rate Limits**:
- Unofficial: ~600 requests/minute
- Recommended polling: Every 5 minutes for markets
- Cost: Free

**Key Endpoints**:
```python
# Get all markets
client.get_markets()

# Get specific market
client.get_market(market_id)

# Get order book
client.get_order_book(market_id)

# Place order
client.create_order(
    market_id=market_id,
    side="BUY",  # or "SELL"
    price=0.93,
    size=350
)

# Cancel order
client.cancel_order(order_id)
```

### Claude API (Anthropic)

**Model**: `claude-3-5-sonnet-20241022`

**Authentication**:
- API Key: `sk-ant-...`
- Header: `x-api-key: {ANTHROPIC_API_KEY}`

**Usage Estimates**:
- Calls per day: 50-100 (opportunity evaluation)
- Tokens per call: ~1,000 input + 300 output
- Monthly cost: $80-150

**Rate Limits**:
- Tier 1: 50 requests/minute
- Tier 2: 1,000 requests/minute (if upgraded)

**Key Parameters**:
```python
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1000,
    temperature=0,  # Deterministic for trading decisions
    messages=[
        {"role": "user", "content": prompt}
    ]
)
```

### Telegram Bot API

**Authentication**: Bot token from @BotFather

**Mode**: Polling (not webhooks)

**Key Methods**:
```python
# Send message
bot.send_message(
    chat_id=TELEGRAM_CHAT_ID,
    text="Message here",
    parse_mode="Markdown"
)

# Send formatted message
bot.send_message(
    chat_id=TELEGRAM_CHAT_ID,
    text=f"*Bold* _italic_ `code`",
    parse_mode="Markdown"
)

# Handle commands
@bot.message_handler(commands=['approve', 'skip', 'positions'])
def handle_command(message):
    ...
```

### News RSS Feeds

**Sources** (All free, no API key):
- Reuters Business: `http://feeds.reuters.com/reuters/businessNews`
- ESPN: `https://www.espn.com/espn/rss/news`
- Federal Reserve: `https://www.federalreserve.gov/feeds/press_all.xml`

**Polling Frequency**: Every 15 minutes

---

## Configuration Parameters

### Entry Filters
```python
# Price range
PRICE_MIN = 0.92
PRICE_MAX = 0.97

# Liquidity requirements
MIN_VOLUME_24H = 50000  # $50k daily volume
MIN_BID_DEPTH = 20000   # $20k bid depth
MIN_LIQUIDITY_RATIO = 10  # 10x position size

# Spread
MAX_SPREAD_PCT = 0.03  # 3% max spread

# Settlement window
MIN_SETTLEMENT_HOURS = 6
MAX_SETTLEMENT_DAYS = 7

# Quality scores (0-10)
MIN_RESOLUTION_CLARITY = 8
MIN_EVENT_FINALITY = 8

# Profit threshold
MIN_TRUE_PROFIT_PCT = 0.04  # 4% after fees/slippage
```

### Position Sizing
```python
# Kelly Criterion
KELLY_FRACTION = 0.25  # Use 1/4 Kelly for safety

# Position limits
MIN_POSITION_SIZE = 100  # $100 minimum
MAX_POSITION_SIZE = 500  # $500 maximum
```

### Stop-Loss Settings
```python
# Base stop-loss
BASE_STOP_LOSS_PCT = 0.10  # 10% default

# Adaptive range
MIN_STOP_LOSS_PCT = 0.08   # 8% minimum
MAX_STOP_LOSS_PCT = 0.18   # 18% maximum

# Adjustments
VOLATILITY_MULTIPLIER = 1.5
LIQUIDITY_ADJUSTMENT = True
MANIPULATION_WINDOW_HOURS = 6
MANIPULATION_STOP_MULTIPLIER = 1.5
```

### Portfolio Limits
```python
# Position limits
MAX_POSITIONS = 8
MAX_SAME_DAY_SETTLEMENT = 3

# Exposure limits
MAX_CATEGORY_EXPOSURE_PCT = 0.40  # 40% per category
MIN_RESERVE_PCT = 0.20  # 20% always in reserve

# Risk limits
MAX_POSITION_RISK_PCT = 0.02  # 2% of portfolio per trade
PORTFOLIO_DRAWDOWN_REDUCE = 0.20  # Reduce sizes at 20% drawdown
PORTFOLIO_DRAWDOWN_STOP = 0.30  # Stop trading at 30% drawdown
```

### Monitoring Intervals
```python
# Polling frequencies
MARKET_POLL_INTERVAL_SEC = 300  # 5 minutes
PRICE_CHECK_INTERVAL_SEC = 60   # 1 minute
LIQUIDITY_CHECK_INTERVAL_MIN = 60  # 1 hour
NEWS_CHECK_INTERVAL_SEC = 60    # 1 minute (for open positions)

# Alert thresholds
SUDDEN_DROP_THRESHOLD_PCT = 0.03  # 3% sudden drop
LIQUIDITY_DECAY_WARNING_PCT = 0.50  # 50% decay warning
LIQUIDITY_DECAY_URGENT_PCT = 0.70   # 70% decay urgent alert
```

### Reporting Schedule
```python
MORNING_REPORT_HOUR = 8  # 8 AM daily report
EVENING_CHECK_HOUR = 17  # 5 PM status check
WEEKLY_REVIEW_DAY = 0    # Monday (0 = Monday, 6 = Sunday)
TOP_OPPORTUNITIES_SHOW = 5  # Show top 5 in morning report
```

---

## Filter Pipeline Specifications

### Stage 1: Price Range Filter
```python
def filter_price_range(markets):
    """
    Keep only markets where YES price is in tail-end range.

    Criteria: 0.92 ≤ YES price ≤ 0.97

    Expected rejection: ~70% of markets
    """
    return [m for m in markets if PRICE_MIN <= m['yes_price'] <= PRICE_MAX]
```

### Stage 2: Liquidity Filter
```python
def filter_liquidity(markets):
    """
    Ensure sufficient volume and depth for safe entry/exit.

    Criteria:
    - 24h volume ≥ $50,000
    - Bid depth ≥ $20,000

    Expected rejection: ~50% of remaining markets
    """
    return [m for m in markets
            if m['volume_24h'] >= MIN_VOLUME_24H
            and m['bid_depth'] >= MIN_BID_DEPTH]
```

### Stage 3: Settlement Window Filter
```python
def filter_settlement_window(markets):
    """
    Avoid markets settling too soon (manipulation risk) or too late (capital efficiency).

    Criteria: 6 hours ≤ time to settlement ≤ 7 days

    Expected rejection: ~30% of remaining markets
    """
    now = datetime.now()
    return [m for m in markets
            if MIN_SETTLEMENT_HOURS <= (m['settlement_date'] - now).total_seconds() / 3600 <= MAX_SETTLEMENT_DAYS * 24]
```

### Stage 4: Spread Filter
```python
def filter_spread(markets):
    """
    Wide spreads indicate poor liquidity or manipulation.

    Criteria: (ASK - BID) / BID ≤ 3%

    Expected rejection: ~20% of remaining markets
    """
    return [m for m in markets
            if (m['ask_price'] - m['bid_price']) / m['bid_price'] <= MAX_SPREAD_PCT]
```

### Stage 5: Exit Path Liquidity Filter
```python
def filter_exit_liquidity(markets, position_size=500):
    """
    Ensure we can exit without massive slippage.

    Criteria: Available liquidity ≥ 10x our position size

    Expected rejection: ~15% of remaining markets
    """
    return [m for m in markets
            if m['bid_depth'] / position_size >= MIN_LIQUIDITY_RATIO]
```

### Stage 6: Resolution Clarity Filter
```python
def filter_resolution_clarity(markets):
    """
    Subjective criteria lead to disputes and reversals.

    Criteria: Resolution clarity score ≥ 8/10

    Scoring guide:
    10/10: Objective data source (NBA score, Fed announcement)
    8/10: Clear criteria with official source
    6/10: Some subjectivity (expert judgment required)
    4/10: Highly subjective (public opinion polls)

    Expected rejection: ~10% of remaining markets
    """
    return [m for m in markets
            if m['resolution_clarity_score'] >= MIN_RESOLUTION_CLARITY]
```

### Stage 7: Event Finality Filter
```python
def filter_event_finality(markets):
    """
    Event must be concluded, not just "called" by media.

    Criteria: Event finality score ≥ 8/10

    Scoring guide:
    10/10: Event concluded, official confirmation (game ended, data released)
    8/10: Event effectively concluded, awaiting formality
    6/10: Event "called" by media, but could change
    4/10: Event in progress or preliminary results

    Expected rejection: ~10% of remaining markets
    """
    return [m for m in markets
            if m['event_finality_score'] >= MIN_EVENT_FINALITY]
```

### Stage 8: Portfolio Limit Filter
```python
def filter_portfolio_limits(markets, current_positions):
    """
    Diversification and risk management.

    Criteria:
    - No more than 40% in any category
    - No more than 3 positions settling same day
    - No more than 8 total positions

    Expected rejection: ~5% of remaining markets
    """
    # Calculate category exposure
    category_exposure = {}
    for pos in current_positions:
        category = pos['category']
        category_exposure[category] = category_exposure.get(category, 0) + pos['size_usd']

    # Calculate same-day settlements
    settlement_dates = [pos['settlement_date'].date() for pos in current_positions]

    filtered = []
    for market in markets:
        # Check category limit
        category = market['category']
        new_exposure = category_exposure.get(category, 0) + MAX_POSITION_SIZE
        if new_exposure / BANKROLL_USD > MAX_CATEGORY_EXPOSURE_PCT:
            continue

        # Check same-day settlement limit
        settlement_date = market['settlement_date'].date()
        if settlement_dates.count(settlement_date) >= MAX_SAME_DAY_SETTLEMENT:
            continue

        # Check total position limit
        if len(current_positions) >= MAX_POSITIONS:
            continue

        filtered.append(market)

    return filtered
```

---

## Scoring Formulas

### Overall Opportunity Score
```python
def calculate_final_score(market):
    """
    Risk-adjusted return per day.

    Higher score = better opportunity
    """
    true_profit = calculate_true_profit(market)
    certainty = market['event_finality_score'] / 10
    liquidity = min(market['liquidity_ratio'] / 20, 1.0)
    manipulation_risk = calculate_manipulation_risk(market)
    days_to_settlement = calculate_days_to_settlement(market)

    score = (true_profit * certainty * liquidity * (1 - manipulation_risk)) / days_to_settlement

    return score
```

### True Profit Calculation
```python
def calculate_true_profit(market):
    """
    Net profit after all costs.

    Returns: Decimal (e.g., 0.048 for 4.8%)
    """
    entry_price = market['yes_price']
    settlement_price = 1.00

    # Gross profit
    gross_profit = settlement_price - entry_price

    # Subtract fees (2% on Polymarket)
    fees = gross_profit * 0.02

    # Subtract estimated slippage (0.5% for good liquidity)
    slippage = entry_price * 0.005

    # Net profit
    net_profit = gross_profit - fees - slippage

    # Return as percentage
    return net_profit / entry_price
```

### Manipulation Risk Score
```python
def calculate_manipulation_risk(market):
    """
    0.0 = no risk, 1.0 = maximum risk

    Factors:
    - Time to settlement (< 6h = high risk)
    - Liquidity concentration
    - Recent price volatility
    """
    hours_to_settlement = (market['settlement_date'] - datetime.now()).total_seconds() / 3600

    # Time-based risk
    if hours_to_settlement < 6:
        time_risk = 0.3
    elif hours_to_settlement < 24:
        time_risk = 0.1
    else:
        time_risk = 0.05

    # Liquidity concentration risk
    # (If top 3 bids = 80% of depth, higher risk)
    concentration = market.get('liquidity_concentration', 0.5)
    concentration_risk = concentration * 0.2

    # Volatility risk
    volatility = market.get('price_volatility_6h', 0.02)
    volatility_risk = min(volatility * 5, 0.2)  # Cap at 0.2

    return min(time_risk + concentration_risk + volatility_risk, 1.0)
```

---

## Position Sizing Algorithm

### Kelly Criterion (1/4 Kelly)
```python
def calculate_position_size(market, bankroll, ai_certainty):
    """
    Calculate optimal position size using Kelly Criterion with safety margin.

    Args:
        market: Market data dict
        bankroll: Total available capital (USD)
        ai_certainty: AI-assessed probability (0.0-1.0)

    Returns:
        Position size in USD
    """
    # Step 1: Calculate edge
    market_price = market['yes_price']
    your_certainty = ai_certainty
    edge = your_certainty - market_price

    # Safety margin (3% discount)
    edge_adjusted = edge * 0.97

    # Step 2: Full Kelly
    full_kelly = edge_adjusted / (1 - market_price)

    # Step 3: Apply 1/4 Kelly for safety
    fraction = full_kelly * KELLY_FRACTION

    # Step 4: Calculate size
    size = bankroll * fraction

    # Step 5: Apply hard limits
    size = max(size, MIN_POSITION_SIZE)
    size = min(size, MAX_POSITION_SIZE)

    # Step 6: Apply portfolio constraints
    deployed = get_total_deployed_capital()
    max_deployable = bankroll * (1 - MIN_RESERVE_PCT)
    available = max_deployable - deployed

    size = min(size, available)

    return round(size, 2)
```

---

## Stop-Loss Calculation

### Adaptive Stop-Loss Algorithm
```python
def calculate_stop_loss(market, entry_price):
    """
    Calculate adaptive stop-loss based on volatility, liquidity, and time.

    Returns: Stop-loss price (USD)
    """
    # Step 1: Base stop (10%)
    base_stop_pct = BASE_STOP_LOSS_PCT

    # Step 2: Volatility adjustment
    price_history = get_price_history(market['market_id'], hours=6)
    volatility = calculate_volatility(price_history)
    volatility_adjustment = volatility * VOLATILITY_MULTIPLIER

    # Step 3: Liquidity adjustment
    liquidity_ratio = market['bid_depth'] / MAX_POSITION_SIZE
    if liquidity_ratio < 10:
        liquidity_adjustment = 0.05  # Widen stop by 5%
    elif liquidity_ratio < 20:
        liquidity_adjustment = 0.0  # No adjustment
    else:
        liquidity_adjustment = -0.02  # Tighten stop by 2%

    # Step 4: Time adjustment (manipulation window)
    hours_to_settlement = (market['settlement_date'] - datetime.now()).total_seconds() / 3600
    if hours_to_settlement <= MANIPULATION_WINDOW_HOURS:
        time_adjustment = base_stop_pct * (MANIPULATION_STOP_MULTIPLIER - 1)
    else:
        time_adjustment = 0.0

    # Step 5: Calculate final stop percentage
    final_stop_pct = base_stop_pct + volatility_adjustment + liquidity_adjustment + time_adjustment

    # Step 6: Apply bounds
    final_stop_pct = max(MIN_STOP_LOSS_PCT, min(final_stop_pct, MAX_STOP_LOSS_PCT))

    # Step 7: Calculate stop price
    stop_price = entry_price * (1 - final_stop_pct)

    return round(stop_price, 4), round(final_stop_pct, 4)
```

### Volatility Calculation
```python
def calculate_volatility(price_history):
    """
    Calculate price standard deviation over recent period.

    Returns: Volatility as decimal (e.g., 0.03 for 3%)
    """
    prices = [p['price'] for p in price_history]

    if len(prices) < 2:
        return 0.02  # Default 2% if insufficient data

    mean_price = sum(prices) / len(prices)
    variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
    std_dev = variance ** 0.5

    # Return as percentage of mean
    return std_dev / mean_price
```

---

## Environment Variables

### Required Variables
```bash
# Polymarket
POLYMARKET_PRIVATE_KEY=0x...  # 64 hex chars

# Claude API
ANTHROPIC_API_KEY=sk-ant-...

# Telegram
TELEGRAM_BOT_TOKEN=1234567890:ABC...
TELEGRAM_CHAT_ID=123456789

# Database
DATABASE_PATH=./data/polymarket.db

# Trading
BANKROLL_USD=5000
MAX_POSITION_SIZE=500
MAX_POSITIONS=8

# Logging
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
LOG_FILE=./logs/bot.log
```

### Loading Configuration
```python
import os
from dotenv import load_dotenv

load_dotenv()

# Validate required variables
REQUIRED_VARS = [
    'POLYMARKET_PRIVATE_KEY',
    'ANTHROPIC_API_KEY',
    'TELEGRAM_BOT_TOKEN',
    'TELEGRAM_CHAT_ID'
]

for var in REQUIRED_VARS:
    if not os.getenv(var):
        raise ValueError(f"Missing required environment variable: {var}")

# Load with defaults
BANKROLL_USD = float(os.getenv('BANKROLL_USD', 5000))
MAX_POSITION_SIZE = float(os.getenv('MAX_POSITION_SIZE', 500))
MAX_POSITIONS = int(os.getenv('MAX_POSITIONS', 8))
```

---

## Performance Calculation

### Win Rate
```python
def calculate_win_rate(positions):
    """
    Percentage of profitable closed positions.
    """
    closed = [p for p in positions if p['status'] in ['settled', 'exited', 'stopped']]

    if not closed:
        return 0.0

    wins = [p for p in closed if p['pnl_usd'] > 0]

    return len(wins) / len(closed)
```

### ROI Calculation
```python
def calculate_roi(positions, bankroll):
    """
    Return on investment over period.
    """
    total_pnl = sum(p['pnl_usd'] for p in positions if p['pnl_usd'])

    return total_pnl / bankroll
```

### Sharpe Ratio (Optional)
```python
def calculate_sharpe_ratio(positions, risk_free_rate=0.05):
    """
    Risk-adjusted return metric.

    Sharpe > 1.0 = good
    Sharpe > 2.0 = excellent
    """
    returns = [p['pnl_pct'] for p in positions if p['pnl_pct']]

    if not returns:
        return 0.0

    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    std_dev = variance ** 0.5

    if std_dev == 0:
        return 0.0

    return (mean_return - risk_free_rate) / std_dev
```
