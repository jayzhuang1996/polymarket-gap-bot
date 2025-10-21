# Polymarket Tail-End Arbitrage Bot - Technical Specification

## Project Overview

A semi-automated trading bot that identifies and executes tail-end arbitrage opportunities on Polymarket prediction markets. The system focuses on markets priced between $0.92-$0.97 where outcomes are highly certain (>92% probability) but not yet settled.

## Core Objective

Achieve 8-15% monthly ROI on $X capital through systematic tail-end arbitrage with minimal time commitment (<30 min/day active management).

---

## Strategy Definition

### What is Tail-End Arbitrage?

Trading prediction markets where:
1. Event outcome is essentially decided (game ended, announcement made, data released)
2. Market price reflects 92-97% certainty
3. Settlement occurs within 1-7 days
4. Profit comes from: (Settlement_Value $1.00 - Entry_Price) / Entry_Price

Example:
- Market: "Warriors beat Lakers?"
- Game ended: Warriors won 121-115
- Current price: $0.93 (93% implied probability)
- Settlement: Tomorrow 9 AM
- Trade: Buy YES @ $0.93 → Settles @ $1.00 → 7.5% profit

### Why This Works

- Information lag: Event concluded but market hasn't settled
- Liquidity preference: Traders sell early to free capital
- Risk-averse pricing: Market prices in small remaining uncertainty
- Time value: Holders discount waiting period

---

## Risk Parameters

### Position Limits
- Max position size: $500 per market
- Max concurrent positions: 8
- Max category exposure: 40% of capital
- Max same-day settlement: 3 positions
- Required reserve: 20% of capital (never fully deployed)

### Loss Protection
- Stop-loss: Adaptive 8-18% based on volatility + liquidity
- Position risk: Max 2% of portfolio per trade
- Portfolio drawdown trigger: If down 20%, reduce sizes 50%
- Emergency stop: If down 30%, cease trading for 1 week

### Entry Requirements
- Price range: $0.92 ≤ YES ≤ $0.97
- Daily volume: >$50,000
- Bid depth: >$20,000
- Liquidity ratio: >10x position size (exit path)
- Spread: <3%
- Settlement window: 6 hours to 7 days
- Resolution clarity score: ≥8/10
- Event finality score: ≥8/10
- True profit (after fees/slippage): ≥4%

---

## System Architecture

### Layer 1: Data Collection (Continuous)
- Poll Polymarket API every 5 minutes
- Store: Markets, order books, historical prices
- Scrape: News (RSS feeds), Polymarket comments
- Database: SQLite (local persistence)

### Layer 2: Opportunity Detection (Every 5 min)
- Filter pipeline: 8 stages (price → liquidity → risk)
- Scoring system: Risk-adjusted return per day
- Output: Top 10 ranked opportunities

### Layer 3: AI Decision Engine (Per opportunity)
- LLM evaluation: Claude API
- Risk assessment: Certainty scoring, reversal scenarios
- Output: ENTER / SKIP / HUMAN_REVIEW + reasoning

### Layer 4: Execution (On approval)
- Position sizing: Kelly Criterion (1/4 Kelly for safety)
- Adaptive stop-loss: 8-18% based on volatility/liquidity
- Order placement: Entry + stop-loss + take-profit levels
- Verification: Pre-flight checks before execution

### Layer 5: Monitoring (Every 60 sec)
- Price tracking: Detect >3% sudden drops
- Liquidity health: Track bid depth decay
- News monitoring: Keyword alerts for open positions
- Auto-execution: Stop-loss and take-profit triggers

### Layer 6: User Interface (Telegram)
- Morning report: Top 3-5 opportunities (8 AM)
- Approval mechanism: /approve_X commands
- Real-time alerts: Price drops, news, stops hit
- Position dashboard: /positions command
- Emergency controls: /exit_now, /hold

### Layer 7: Learning System (Weekly)
- Performance analytics: Win rate, avg profit/loss, ROI
- Pattern recognition: Which markets/categories profitable
- Parameter adjustment: Update filters, thresholds
- Human review: Strategic decisions

---

## Data Schema

### Markets Table
```
market_id (TEXT PRIMARY KEY)
question (TEXT)
category (TEXT)
yes_price (REAL)
no_price (REAL)
volume_24h (REAL)
liquidity_depth (REAL)
settlement_date (DATETIME)
resolution_criteria (TEXT)
resolution_clarity_score (INTEGER 0-10)
event_finality_score (INTEGER 0-10)
last_updated (DATETIME)
```

### Order Books Table
```
id (INTEGER PRIMARY KEY)
market_id (TEXT)
timestamp (DATETIME)
bids (JSON)
asks (JSON)
spread_pct (REAL)
```

### Positions Table
```
position_id (INTEGER PRIMARY KEY)
market_id (TEXT)
entry_price (REAL)
entry_time (DATETIME)
tokens (INTEGER)
position_size_usd (REAL)
stop_loss_price (REAL)
stop_loss_pct (REAL)
take_profit_1_price (REAL)
take_profit_2_price (REAL)
status (TEXT: active/stopped/settled/exited)
exit_price (REAL)
exit_time (DATETIME)
pnl_usd (REAL)
pnl_pct (REAL)
liquidity_at_entry (REAL)
volatility_at_entry (REAL)
```

### News Events Table
```
id (INTEGER PRIMARY KEY)
market_id (TEXT)
source (TEXT)
headline (TEXT)
url (TEXT)
timestamp (DATETIME)
sentiment_score (REAL -1 to 1)
```

---

## Technical Stack

### Required
- Python 3.10+
- py-clob-client (Polymarket API)
- anthropic (Claude API for AI agent)
- python-telegram-bot (Telegram interface)
- pandas (data manipulation)
- sqlite3 (database)
- APScheduler (task scheduling)
- requests (HTTP calls)
- feedparser (RSS news scraping)

### Optional (Future)
- scikit-learn (ML for adaptive stops)
- pytorch (if adding LSTM models)
- FastAPI (if building web dashboard)
- PostgreSQL (if scaling beyond SQLite)

---

## External APIs

### Polymarket (py-clob-client)
- Base URL: https://clob.polymarket.com
- Authentication: Private key (Polygon wallet)
- Rate limit: ~600 requests/minute (unofficial)
- Cost: Free

### Claude (Anthropic)
- Model: claude-3-5-sonnet-20241022
- Usage: ~50-100 calls/day for opportunity evaluation
- Cost: ~$80-150/month
- Prompt length: ~1,000 tokens per evaluation

### Telegram Bot API
- Authentication: Bot token from @BotFather
- Webhooks: Not needed (polling mode)
- Cost: Free

### News Sources (RSS)
- Reuters Business: Free
- ESPN (sports): Free
- Federal Reserve releases: Free
- No API key required (public RSS feeds)

---

## Performance Targets

### Success Metrics
- Win rate: ≥70% of positions profitable
- Average win: 4-6% per trade
- Average loss: 4-8% per trade (stops working)
- Monthly ROI: 8-15% on deployed capital
- Max drawdown: <20% from peak
- Time commitment: <30 minutes daily

### Operational Metrics
- Daily opportunities found: 30-40 markets
- Quality opportunities (post-filter): 3-5 markets
- Average positions per day: 2-3 entries
- Average hold time: 1-3 days
- Capital velocity: 10-15 full cycles per month

---

## Risk Scenarios & Mitigation

### Scenario 1: Liquidity Evaporation
- Risk: Stop-loss triggers but no buyers, slippage >5%
- Detection: Monitor bid depth decay hourly
- Mitigation: Only enter markets with >10x liquidity ratio
- Action: Alert at 50% decay, urgent alert at 70%

### Scenario 2: Oracle Manipulation
- Risk: Outcome disputes, incorrect settlement
- Detection: Resolution clarity score <8
- Mitigation: Skip markets with subjective criteria
- Action: Track dispute rate per category, avoid high-dispute types

### Scenario 3: Correlation Cascade
- Risk: Multiple positions crash simultaneously (e.g., all NBA games)
- Detection: Category exposure tracking
- Mitigation: Max 40% per category, max 2-3 same type
- Action: Reject new positions if limits reached

### Scenario 4: Black Swan Reversal
- Risk: "Certain" outcome gets overturned (game cancelled, recount)
- Detection: Event finality score <8
- Mitigation: Only trade post-event, wait cooling period
- Action: Require official confirmation, not just media "calls"

### Scenario 5: Manipulation Window
- Risk: Whales dump in final 6 hours to trigger stops
- Detection: Time to settlement tracking
- Mitigation: Don't enter <6 hours, tighten stops in final window
- Action: Auto-increase stop to 15-18% when <6h remaining

---

## Human-in-Loop Decision Points

### MUST be Human (Critical Judgment)
1. **Daily Entry Approval** (Morning)
   - Review top 3-5 opportunities
   - Click /approve_X or /skip_X
   - Why: Final sanity check, intuition overlay

2. **Emergency News Response** (As needed)
   - Bot alerts: "Negative news detected"
   - Decide: /emergency_exit or /hold
   - Why: Context interpretation, severity assessment

3. **Stop-Loss Override** (Rare)
   - Price near stop, bot suggests "Consider exit?"
   - Decide: Exit early or wait for stop trigger
   - Why: Market feel, additional information

4. **Weekly Strategy Review** (Sunday)
   - Review performance report
   - Adjust: Categories to avoid, filter thresholds
   - Why: Strategic direction, continuous improvement

### Automated with Alert (Monitoring)
5. **Liquidity Decay** - Alert, human decides exit timing
6. **Price Drops** - Alert, human assesses severity
7. **Manipulation Window Entry** - Alert, automatic stop tightening
8. **News Sentiment** - Alert with headline, human interprets

### Fully Automated (No Human)
9. **Data Collection** - Continuous polling
10. **Scanning/Filtering** - Pipeline runs automatically
11. **Stop-Loss Execution** - Auto-triggers at predetermined level
12. **Take-Profit Execution** - Auto-executes at target prices

---

## Development Phases

### Phase 1: MVP (Weeks 1-2)
- Goal: Manual trade execution via code
- Deliverable: Can scan markets, place 1 trade manually
- Success: Execute 5 manual trades profitably

### Phase 2: Automation (Weeks 3-4)
- Goal: Bot finds opportunities, human approves
- Deliverable: Daily Telegram reports, /approve command works
- Success: Bot operates 24/7, sends daily opportunities

### Phase 3: Monitoring (Weeks 5-6)
- Goal: Position tracking with alerts
- Deliverable: Real-time price/news alerts, auto stop-loss
- Success: Saved from 1 bad trade via alert

### Phase 4: Optimization (Weeks 7-8)
- Goal: Adaptive stops, learning loop
- Deliverable: Weekly performance reports, parameter tuning
- Success: 70%+ win rate over 20 trades

---

## Success Criteria

### Technical
- [ ] Bot runs 24/7 without crashes
- [ ] API calls stay under rate limits
- [ ] Database handles 1000+ markets efficiently
- [ ] Telegram responds within 5 seconds
- [ ] Stop-loss executes within 60 seconds of trigger

### Financial
- [ ] 70%+ win rate after 30 trades
- [ ] Average true profit ≥4% per trade
- [ ] Monthly ROI 8-15% (conservative)
- [ ] Max drawdown <20%
- [ ] Zero catastrophic losses (>30% portfolio)

### Operational
- [ ] Daily time commitment <30 minutes
- [ ] Opportunities found daily (3-5 quality)
- [ ] Human approval rate >80% (good filtering)
- [ ] False alerts <5% (no alert fatigue)
- [ ] Position fill rate >90% (good liquidity checking)

---

## Failure Modes & Handling

### Mode 1: API Outage (Polymarket down)
- Detection: HTTP 500/503 errors
- Response: Retry with exponential backoff
- Alert: "API down, monitoring paused"
- Fallback: Hold existing positions, manual monitoring

### Mode 2: Telegram Delivery Failure
- Detection: Message send timeout
- Response: Queue messages, retry 3x
- Alert: Log to file, check logs manually
- Fallback: Discord webhook backup

### Mode 3: Database Corruption
- Detection: SQLite integrity check fails
- Response: Restore from hourly backup
- Alert: "DB issue, restoring backup"
- Prevention: Hourly backups to separate file

### Mode 4: Stop-Loss Not Executing
- Detection: Price below stop but position still active
- Response: Emergency market order
- Alert: "Stop-loss failed, manual intervention"
- Why happens: Extreme liquidity crash

### Mode 5: False Entry Signal
- Detection: Human notices error in /approve review
- Response: /skip_X command
- Prevention: Always show reasoning in report
- Learning: Log rejected opportunities for filter improvement

---

## Configuration

### Environment Variables Required
```
POLYMARKET_PRIVATE_KEY=0x...
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DATABASE_PATH=./data/polymarket.db
LOG_LEVEL=INFO
BANKROLL_USD=5000
MAX_POSITION_SIZE=500
MAX_POSITIONS=8
```

### Adjustable Parameters (config.py)
```python
# Entry filters
PRICE_MIN = 0.92
PRICE_MAX = 0.97
MIN_VOLUME_24H = 50000
MIN_BID_DEPTH = 20000
MAX_SPREAD_PCT = 0.03
MIN_LIQUIDITY_RATIO = 10
MIN_SETTLEMENT_HOURS = 6
MAX_SETTLEMENT_DAYS = 7
MIN_RESOLUTION_CLARITY = 8
MIN_EVENT_FINALITY = 8
MIN_TRUE_PROFIT_PCT = 0.04

# Position sizing
KELLY_FRACTION = 0.25  # Use 1/4 Kelly
MIN_POSITION_SIZE = 100
MAX_POSITION_SIZE = 500

# Stop-loss
BASE_STOP_LOSS_PCT = 0.10
MIN_STOP_LOSS_PCT = 0.08
MAX_STOP_LOSS_PCT = 0.18
VOLATILITY_MULTIPLIER = 1.5
LIQUIDITY_ADJUSTMENT = True
MANIPULATION_WINDOW_HOURS = 6
MANIPULATION_STOP_MULTIPLIER = 1.5

# Portfolio limits
MAX_POSITIONS = 8
MAX_CATEGORY_EXPOSURE_PCT = 0.40
MAX_SAME_DAY_SETTLEMENT = 3
MIN_RESERVE_PCT = 0.20

# Monitoring
PRICE_CHECK_INTERVAL_SEC = 60
LIQUIDITY_CHECK_INTERVAL_MIN = 60
NEWS_CHECK_INTERVAL_SEC = 60
SUDDEN_DROP_THRESHOLD_PCT = 0.03
LIQUIDITY_DECAY_WARNING_PCT = 0.50
LIQUIDITY_DECAY_URGENT_PCT = 0.70

# Reporting
MORNING_REPORT_HOUR = 8
EVENING_CHECK_HOUR = 17
WEEKLY_REVIEW_DAY = 0  # Monday
TOP_OPPORTUNITIES_SHOW = 5
```

---

## Testing Requirements

### Unit Tests
- Filter pipeline: Each stage rejects expected inputs
- Scoring system: Known inputs produce expected scores
- Position sizing: Kelly calculation accuracy
- Stop-loss calculation: Adaptive logic correctness
- Risk checks: Portfolio limits enforced

### Integration Tests
- API calls: Polymarket connection works
- Database: CRUD operations succeed
- Telegram: Messages send/receive properly
- AI agent: Returns structured JSON responses
- Order execution: Mock orders place correctly

### Smoke Tests (Before Each Deploy)
- [ ] Poll markets successfully
- [ ] Store in database
- [ ] Run filter pipeline
- [ ] Generate Telegram message
- [ ] Calculate position size
- [ ] Verify portfolio limits

### Production Monitoring
- Daily: Check logs for errors
- Daily: Verify opportunities generated
- Weekly: Review win rate, ROI
- Monthly: Database size check
- Monthly: API cost review

---

## Maintenance Schedule

### Daily (Automated)
- Poll Polymarket API every 5 min
- Monitor positions every 60 sec
- Generate morning report at 8 AM
- Log all activities

### Weekly (Human)
- Review performance report (Sunday 8 AM)
- Adjust parameters if win rate <70%
- Check error logs
- Backup database

### Monthly (Human)
- Review API costs (Claude, others)
- Analyze category performance
- Update news sources if needed
- Review code for improvements

### Quarterly (Human)
- Full system audit
- Update dependencies
- Review strategy performance
- Consider new features