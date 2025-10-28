# Polymarket Tail-End Arbitrage Bot - Specification

*Business requirements and trading strategy*

---

## Project Overview

A semi-automated trading bot that identifies and executes tail-end arbitrage opportunities on Polymarket prediction markets. The system focuses on markets priced between $0.92-$0.97 where outcomes are highly certain (>92% probability) but not yet settled.

**Objective**: Achieve 8-15% monthly ROI on $5,000 capital through systematic tail-end arbitrage with minimal time commitment (<30 min/day active management).

**Timeline**: 4-week development, broken into 9 components

---

## What is Tail-End Arbitrage?

### Definition

Trading prediction markets where:
1. **Event outcome is essentially decided** (game ended, announcement made, data released)
2. **Market price reflects 92-97% certainty**
3. **Settlement occurs within 1-7 days**
4. **Profit comes from**: (Settlement_Value $1.00 - Entry_Price) / Entry_Price

### Example Trade

```
Market: "Will Warriors beat Lakers?"
Event Status: Game ended, Warriors won 121-115
Current Price: $0.93 (93% implied probability)
Settlement: Tomorrow 9 AM
Trade: Buy YES @ $0.93 → Settles @ $1.00 → 7.5% profit in 24 hours
```

### Why This Works

1. **Information Lag** - Event concluded but market hasn't settled yet
2. **Liquidity Preference** - Traders sell early to free capital for other opportunities
3. **Risk-Averse Pricing** - Market prices in small remaining uncertainty (reversals, disputes)
4. **Time Value** - Holders discount waiting period until settlement

---

## Trading Strategy

### Entry Requirements

**Price Range**:
- YES price between $0.92 and $0.97
- Represents 92-97% implied certainty

**Liquidity Thresholds**:
- Daily volume > $50,000
- Bid depth > $20,000
- Liquidity ratio > 10x position size (safe exit path)
- Spread < 3%

**Time Window**:
- Minimum: 6 hours to settlement (avoid manipulation window)
- Maximum: 7 days to settlement (capital efficiency)

**Quality Scores** (0-10 scale):
- Resolution clarity ≥ 8 (objective criteria, no subjective judgment)
- Event finality ≥ 8 (event concluded, not just "called" by media)

**Profitability**:
- True profit (after fees & slippage) ≥ 4%

### Position Sizing

**Kelly Criterion** with safety margin:
- Calculate edge: Your certainty - Market price
- Full Kelly: Edge / (1 - Market_Price)
- **Use 1/4 Kelly** for safety
- Hard caps: $100 min, $500 max per position

### Risk Management

**Stop-Loss** (Adaptive):
- Base: 10% below entry
- Adjust for volatility: +/- based on 6-hour price StdDev
- Adjust for liquidity: Widen if thin, tighten if deep
- Adjust for time: Widen 50% when <6h to settlement (manipulation window)
- Range: 8-18%

**Portfolio Limits**:
- Max positions: 8 concurrent
- Max category exposure: 40% of capital
- Max same-day settlements: 3 positions
- Reserve requirement: 20% always in cash

**Drawdown Protection**:
- At 20% drawdown: Reduce position sizes 50%
- At 30% drawdown: Stop trading for 1 week

---

## Human-in-Loop Decision Points

### MUST Be Human (Critical Judgment)

1. **Daily Entry Approval** (Morning, ~10 minutes)
   - Review top 3-5 opportunities in Telegram report
   - Command: `/approve_X` or `/skip_X`
   - **Why**: Final sanity check, apply intuition

2. **Emergency News Response** (As needed, ~5 minutes)
   - Bot alerts: "Negative news detected for [position]"
   - Command: `/emergency_exit` or `/hold`
   - **Why**: Context interpretation, severity assessment

3. **Stop-Loss Override** (Rare, ~2 minutes)
   - Bot suggests: "Consider exit? Price near stop"
   - Decide: Exit early or wait for auto-stop
   - **Why**: Market feel, additional information

4. **Weekly Strategy Review** (Sunday, ~15 minutes)
   - Review performance analytics
   - Adjust: Filter thresholds, category exclusions
   - **Why**: Strategic direction, continuous improvement

### Automated with Alert (Monitoring)

5. **Liquidity Decay** - Alert sent, human decides timing
6. **Price Drops** - Alert sent, human assesses severity
7. **News Sentiment** - Alert with headline, human interprets

### Fully Automated (No Human)

8. **Data Collection** - Scheduled polling every 8 hours
9. **Opportunity Scanning** - Pipeline runs automatically after each collection
10. **Stop-Loss Execution** - Auto-triggers at predetermined level
11. **Take-Profit Execution** - Auto-executes at target prices

**Total Daily Time**: <30 minutes
- Morning review: 10 min
- Alert responses: 10-15 min
- Evening check: 5 min

---

## Performance Targets

### Success Metrics

**Financial**:
- Win rate ≥ 70% (7 out of 10 trades profitable)
- Average win: 4-6% per trade
- Average loss: 4-8% per trade (stops working)
- Monthly ROI: 8-15% on deployed capital
- Max drawdown: <20% from peak

**Operational**:
- Daily opportunities found: 30-40 markets pass price filter
- Quality opportunities: 3-5 pass all filters
- Average positions per day: 2-3 new entries
- Average hold time: 1-3 days
- Capital velocity: 10-15 full cycles per month

**Time Commitment**:
- Daily active time: <30 minutes
- Weekly review: 15 minutes
- Monthly analysis: 30 minutes

---

## Risk Scenarios & Mitigation

### Scenario 1: Liquidity Evaporation
**Risk**: Stop-loss triggers but no buyers, slippage >5%

**Detection**: Monitor bid depth decay hourly

**Mitigation**:
- Only enter markets with >10x liquidity ratio
- Alert at 50% liquidity decay
- Urgent alert at 70% decay

---

### Scenario 2: Oracle Manipulation
**Risk**: Outcome disputes, incorrect settlement, reversals

**Detection**: Resolution clarity score <8

**Mitigation**:
- Skip markets with subjective criteria
- Track dispute rate per category
- Avoid high-dispute categories

---

### Scenario 3: Correlation Cascade
**Risk**: Multiple positions crash simultaneously (e.g., all NBA games)

**Detection**: Category exposure tracking

**Mitigation**:
- Max 40% per category
- Max 2-3 same-event-type positions
- Reject new positions if limits reached

---

### Scenario 4: Black Swan Reversal
**Risk**: "Certain" outcome gets overturned (game cancelled, recount)

**Detection**: Event finality score <8

**Mitigation**:
- Only trade post-event markets
- Require official confirmation, not media "calls"
- Wait for cooling-off period

---

### Scenario 5: Manipulation Window
**Risk**: Whales dump in final 6 hours to trigger stops

**Detection**: Time to settlement <6 hours

**Mitigation**:
- Don't enter <6 hours to settlement
- Auto-widen stops by 50% when entering final window
- Higher scrutiny for sub-24h markets

---

## Development Phases

### Phase 1: MVP (Weeks 1-2)
**Goal**: Manual trade execution via code

**Deliverables**:
- Connect to Polymarket API
- Fetch and filter markets
- Place one manual trade via code
- Basic position tracking

**Success**: Execute 5 manual trades profitably

---

### Phase 2: Automation (Weeks 3-4)
**Goal**: Bot finds opportunities, human approves via Telegram

**Deliverables**:
- Automated scanning every 5 min
- AI evaluation (Claude API)
- Telegram interface (/approve, /skip commands)
- Daily morning reports

**Success**: Bot operates 24/7, sends daily opportunities

---

### Phase 3: Monitoring (Weeks 5-6)
**Goal**: Real-time position tracking with alerts

**Deliverables**:
- Price monitoring (every 60s)
- Liquidity monitoring (every 60 min)
- News monitoring (keyword matching)
- Auto stop-loss execution
- Alert system via Telegram

**Success**: Saved from 1 bad trade via timely alert

---

### Phase 4: Optimization (Weeks 7-8)
**Goal**: Adaptive strategies and learning loop

**Deliverables**:
- Adaptive stop-loss (volatility + liquidity based)
- Weekly performance reports
- Parameter tuning (filters, thresholds)
- Category performance analysis

**Success**: 70%+ win rate over 20 trades

---

## Success Criteria

### Technical Requirements
- [ ] Bot runs 24/7 without crashes
- [ ] API calls stay under rate limits
- [ ] Database handles 1000+ markets efficiently
- [ ] Telegram responds within 5 seconds
- [ ] Stop-loss executes within 60 seconds of trigger

### Financial Requirements
- [ ] 70%+ win rate after 30 trades
- [ ] Average true profit ≥4% per winning trade
- [ ] Monthly ROI 8-15% (conservative target)
- [ ] Max drawdown <20% from peak
- [ ] Zero catastrophic losses (>30% portfolio)

### Operational Requirements
- [ ] Daily time commitment <30 minutes
- [ ] Quality opportunities found daily (3-5)
- [ ] Human approval rate >80% (indicates good filtering)
- [ ] False alerts <5% (avoid alert fatigue)
- [ ] Position fill rate >90% (good liquidity checking)

---

## System Components

*See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed component design*

1. **Data Collection** - Polymarket API polling, news scraping
2. **Opportunity Detection** - 8-stage filter pipeline, scoring
3. **AI Decision Engine** - Claude API evaluation
4. **Execution System** - Position sizing, order placement, stops
5. **Monitoring System** - Price/liquidity/news tracking, alerts
6. **Telegram Interface** - Human interaction layer
7. **Learning System** - Performance analytics, parameter tuning

---

## Technical Stack

### Core Dependencies
- **Python 3.10+**
- **py-clob-client** - Polymarket API wrapper
- **anthropic** - Claude API for AI agent
- **python-telegram-bot** - Telegram interface
- **pandas** - Data manipulation
- **sqlite3** - Local database
- **APScheduler** - Task scheduling
- **requests** - HTTP calls
- **feedparser** - RSS news scraping

### External APIs
- **Polymarket** - Trading (free, ~600 req/min)
- **Claude** - AI decisions (~$80-150/month)
- **Telegram** - User interface (free)
- **RSS Feeds** - News (free, no auth required)

*See [REFERENCE.md](REFERENCE.md) for API details and configuration*

---

## Configuration

### Environment Variables Required

```bash
# Trading
POLYMARKET_PRIVATE_KEY=0x...
BANKROLL_USD=5000
MAX_POSITION_SIZE=500
MAX_POSITIONS=8

# AI
ANTHROPIC_API_KEY=sk-ant-...

# Interface
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Database
DATABASE_PATH=./data/polymarket.db

# Logging
LOG_LEVEL=INFO
```

*See [REFERENCE.md](REFERENCE.md) for complete configuration parameters*

---

## Development Guidelines

### Incremental Development
- Write 10-50 lines at a time
- Test immediately with real data
- Show output to human before proceeding
- Never write large blocks without testing

### Testing Philosophy
- Every function tested before moving on
- Use real API calls where safe (read-only)
- Use dummy data for write operations initially
- Show clear test output

### Security First
- Never hardcode API keys
- Always load from environment variables
- Show only last 4 characters in logs
- Warn about security implications

*See [CLAUDE.md](CLAUDE.md) for complete development guidelines*

---

## Project Deliverables

### Documentation
- [x] SPEC.md - This file (business requirements)
- [x] ARCHITECTURE.md - System design
- [x] REFERENCE.md - Technical reference (APIs, schemas, formulas)
- [x] TEMPLATES.md - Code examples and message templates
- [x] RUNBOOK.md - Operational procedures
- [x] CLAUDE.md - Development guidelines
- [ ] TODO.md - Task breakdown
- [ ] README.md - Setup instructions

### Code
- [ ] Data collection modules
- [ ] Filter pipeline
- [ ] AI decision agent
- [ ] Execution system
- [ ] Monitoring system
- [ ] Telegram bot
- [ ] Database schema
- [ ] Tests (unit + integration)

### Deployment
- [ ] Environment configuration
- [ ] Database setup
- [ ] API key configuration
- [ ] Telegram bot setup
- [ ] Logging configuration
- [ ] Backup procedures

---

## Next Steps

1. **Review all documentation**:
   - Read [ARCHITECTURE.md](ARCHITECTURE.md) - System design
   - Read [REFERENCE.md](REFERENCE.md) - Technical details
   - Read [TEMPLATES.md](TEMPLATES.md) - Code examples
   - Read [CLAUDE.md](CLAUDE.md) - Development process

2. **Create development plan**:
   - See [TODO.md](TODO.md) for task breakdown

3. **Begin implementation**:
   - Start with Component 1: Data Collection
   - Follow incremental development principles
   - Test continuously

4. **Maintain discipline**:
   - Small steps (10-50 lines)
   - Constant testing
   - Clear communication
   - Human approval before proceeding

---

## Questions & Clarifications

If anything in this specification is unclear or ambiguous:
1. Ask clarifying questions
2. Point out conflicts or inconsistencies
3. Suggest alternatives
4. Wait for human decision before proceeding

**This is real money. Code quality, testing, and safety are paramount.**
