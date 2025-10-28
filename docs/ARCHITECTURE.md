# System Architecture

*High-level design of the Polymarket tail-end arbitrage bot*

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        HUMAN OPERATOR                        │
│                     (Telegram Interface)                     │
└────────────┬──────────────────────────────────┬─────────────┘
             │ Approvals                         │ Alerts
             │ Commands                          │ Reports
             ▼                                   ▼
┌─────────────────────────────────────────────────────────────┐
│                   TELEGRAM BOT LAYER                         │
│  • Receives commands (/approve, /skip, /positions)          │
│  • Sends reports (morning, alerts, updates)                 │
│  • Formats data for human readability                       │
└────────────┬──────────────────────────────────┬─────────────┘
             │                                   │
             ▼                                   ▼
┌──────────────────────────┐      ┌──────────────────────────┐
│   ORCHESTRATOR (main.py) │      │  MONITORING SYSTEM       │
│  • Schedules tasks       │◄────►│  • Price tracking (60s)  │
│  • Coordinates components│      │  • Liquidity checks      │
│  • Manages workflow      │      │  • News monitoring       │
└────────┬─────────────────┘      └──────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    CORE PIPELINE                             │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐ │
│  │   COLLECT    │───►│    DETECT    │───►│   DECIDE     │ │
│  │              │    │              │    │              │ │
│  │ • Poll API   │    │ • Filter     │    │ • AI Agent   │ │
│  │ • Scrape news│    │ • Score      │    │ • Risk check │ │
│  │ • Store DB   │    │ • Rank       │    │ • Recommend  │ │
│  └──────────────┘    └──────────────┘    └──────┬───────┘ │
│                                                   │          │
│                                                   ▼          │
│                                          ┌──────────────┐   │
│                                          │   EXECUTE    │   │
│                                          │              │   │
│                                          │ • Size       │   │
│                                          │ • Order      │   │
│                                          │ • Track      │   │
│                                          └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
         │                                   │
         ▼                                   ▼
┌──────────────────────────┐      ┌──────────────────────────┐
│   DATABASE (SQLite)      │      │  EXTERNAL APIS           │
│  • Markets               │      │  • Polymarket (trades)   │
│  • Positions             │      │  • Claude (AI)           │
│  • History               │      │  • News (RSS)            │
└──────────────────────────┘      └──────────────────────────┘
```

---

## System Layers

### Layer 1: Data Collection
**Purpose**: Continuously gather market data and news

**Components**:
- `polymarket_api.py` - Fetch markets, order books, prices
- `news_scraper.py` - Scrape RSS feeds, match to markets

**Schedule**: Every 8 hours (markets), every 4 hours (news)

**Output**: Database populated with current state

---

### Layer 2: Opportunity Detection
**Purpose**: Filter and rank trading opportunities

**Components**:
- `scanner.py` - Orchestrates scanning workflow
- `filters.py` - 8-stage filter pipeline
- `scorer.py` - Risk-adjusted return scoring

**Filter Pipeline**:
```
Input: 500-1000 markets
  ↓
Stage 1: Price Range (0.92-0.97) → ~300 remain
Stage 2: Liquidity (volume, depth) → ~150 remain
Stage 3: Settlement Window (6h-7d) → ~120 remain
Stage 4: Spread (<3%) → ~90 remain
Stage 5: Exit Liquidity (10x) → ~70 remain
Stage 6: Resolution Clarity (≥8) → ~60 remain
Stage 7: Event Finality (≥8) → ~50 remain
Stage 8: Portfolio Limits → ~3-8 remain
  ↓
Output: Top 10 scored opportunities
```

**Scoring Formula**:
```
score = (true_profit × certainty × liquidity × (1 - manipulation_risk)) / days_to_settlement
```

---

### Layer 3: AI Decision Engine
**Purpose**: LLM-based risk evaluation

**Component**: `decision_agent.py`

**Process**:
1. Build prompt with market data, news, comments
2. Send to Claude API
3. Parse JSON response
4. Return: ENTER / SKIP / HUMAN_REVIEW + reasoning

**Decision Logic**:
- `ENTER` → Add to approved list for human
- `SKIP` → Reject opportunity
- `HUMAN_REVIEW` → Flag for manual review

---

### Layer 4: Execution System
**Purpose**: Size positions, place orders, set stops

**Components**:
- `sizer.py` - Kelly Criterion position sizing
- `stop_calculator.py` - Adaptive stop-loss
- `trader.py` - Order placement and verification

**Execution Flow**:
```
1. Pre-flight checks (price, liquidity, news, limits)
2. Calculate position size (1/4 Kelly)
3. Calculate adaptive stop-loss
4. Place entry order (limit buy)
5. Wait for fill (max 60s)
6. Place exit orders (stop-loss, take-profits)
7. Store position in database
8. Notify user via Telegram
```

---

### Layer 5: Monitoring System
**Purpose**: Track positions, detect issues, execute exits

**Components**:
- `price_monitor.py` - Check prices every 60s
- `liquidity_monitor.py` - Check depth every 60min
- `news_monitor.py` - Match news to positions every 60s

**Monitoring Checks**:
- Sudden price drops (>3% in 60s)
- Stop-loss triggers
- Take-profit triggers
- Approaching stop (<2% away)
- Liquidity decay (>50% drop)
- Negative news sentiment
- Manipulation window entry (<6h)

**Actions**:
- Alerts → Telegram notifications
- Auto-execute → Stop-loss, take-profit orders
- Recommendations → Suggest exit or hold

---

### Layer 6: Telegram Interface
**Purpose**: Human-in-the-loop interaction

**Component**: `telegram_bot.py`

**Message Types**:
- **Morning Report** (8 AM) - Top 5 opportunities
- **Price Alerts** - Sudden drops, approaching stops
- **News Alerts** - Negative sentiment detected
- **Execution Confirmations** - Stops/TPs hit
- **Position Dashboard** - `/positions` command

**Commands**:
- `/approve_N $amount` - Execute trade
- `/skip_N` - Reject opportunity
- `/positions` - Show active positions
- `/exit_N` - Request exit
- `/confirm_exit_N` - Confirm exit
- `/details_N` - Full opportunity details

---

## Data Flow

### Morning Workflow (8:00 AM)
```
1. Scanner runs automatically
2. Filters 500+ markets → Top 5-10
3. AI evaluates each opportunity
4. Telegram sends morning report
5. Human reviews and approves/skips
6. Approved trades execute immediately
7. Monitoring begins for new positions
```

### Continuous Monitoring (All Day)
```
Every 60 seconds:
1. Check all position prices
2. Detect sudden drops, trigger stops/TPs
3. Send alerts if needed

Every 60 minutes:
4. Check liquidity health
5. Alert if decaying

Every 8 hours:
6. Scan for new opportunities
7. Update database
```

### Alert Response Flow
```
1. Monitor detects issue (price drop, news, liquidity)
2. Telegram alert sent to human
3. Human decides: /exit or /hold
4. If /exit: Execute market order, close position
5. If /hold: Continue monitoring
```

---

## Component Interactions

### Data Collection → Detection
- Collector stores markets in database
- Scanner reads from database
- Filters process markets sequentially
- Scorer ranks filtered results

### Detection → AI Decision
- Top 10 scored opportunities passed to AI
- AI fetches additional context (news, comments)
- AI returns recommendations
- Only "ENTER" recommendations shown to human

### AI Decision → Execution
- Human approves via Telegram command
- Execution module sizes position
- Calculates adaptive stop-loss
- Places orders via Polymarket API
- Stores position in database

### Execution → Monitoring
- New position triggers monitoring
- Price monitor checks every 60s
- Liquidity monitor checks every 60min
- News monitor scans continuously
- Alerts sent via Telegram

---

## Database Schema

### Core Tables
- **markets** - All Polymarket markets (updated every 5 min)
- **order_books** - Order book snapshots (historical tracking)
- **positions** - Active and closed positions
- **news_events** - Scraped news matched to markets

*See [REFERENCE.md](REFERENCE.md) for detailed schemas*

---

## External Dependencies

### APIs
- **Polymarket** - Trading (free, ~600 req/min limit)
- **Claude** - AI decisions (~$100/month)
- **Telegram** - User interface (free)
- **RSS Feeds** - News (free, no auth)

*See [REFERENCE.md](REFERENCE.md) for API details*

---

## Scheduling

### APScheduler Jobs

```python
# Market scanning (every 8 hours)
scheduler.add_job(scan_markets, 'interval', hours=8)

# Price monitoring (every 60 sec)
scheduler.add_job(monitor_prices, 'interval', seconds=60)

# Liquidity monitoring (every 60 min)
scheduler.add_job(monitor_liquidity, 'interval', minutes=60)

# News scraping (every 4 hours)
scheduler.add_job(scrape_news, 'interval', hours=4)

# News monitoring (every 60 sec for active positions only)
scheduler.add_job(monitor_news, 'interval', seconds=60)

# Morning report (8 AM daily)
scheduler.add_job(send_morning_report, 'cron', hour=8, minute=0)

# Evening check (5 PM daily)
scheduler.add_job(send_evening_summary, 'cron', hour=17, minute=0)

# Weekly review (Monday 8 AM)
scheduler.add_job(send_weekly_report, 'cron', day_of_week='mon', hour=8, minute=0)

# Database backup (hourly)
scheduler.add_job(backup_database, 'interval', hours=1)
```

---

## Project Structure

```
polymarket_bot/
├── config.py              # Configuration & constants
├── main.py               # Orchestrator (entry point)
│
├── data/
│   ├── polymarket.db     # SQLite database
│   └── backups/          # Hourly backups
│
├── collectors/
│   ├── polymarket_api.py # Market data fetching
│   └── news_scraper.py   # RSS feed scraping
│
├── detectors/
│   ├── scanner.py        # Scanning orchestration
│   ├── filters.py        # 8-stage filter pipeline
│   └── scorer.py         # Opportunity scoring
│
├── ai/
│   └── decision_agent.py # Claude API integration
│
├── execution/
│   ├── sizer.py          # Position sizing (Kelly)
│   ├── stop_calculator.py# Adaptive stops
│   └── trader.py         # Order execution
│
├── monitoring/
│   ├── price_monitor.py  # Price tracking
│   ├── liquidity_monitor.py
│   └── news_monitor.py   # News matching
│
├── interface/
│   └── telegram_bot.py   # User interface
│
├── database/
│   ├── schema.sql        # Table definitions
│   └── db_manager.py     # CRUD operations
│
├── utils/
│   ├── logger.py         # Logging setup
│   └── helpers.py        # Shared utilities
│
├── tests/
│   ├── test_filters.py
│   ├── test_scoring.py
│   └── test_sizer.py
│
├── logs/
│   └── bot.log           # Application logs
│
├── docs/
│   ├── SPEC.md           # Business requirements
│   ├── ARCHITECTURE.md   # This file
│   ├── REFERENCE.md      # Technical reference
│   ├── TEMPLATES.md      # Code & message templates
│   └── RUNBOOK.md        # Operations guide
│
├── requirements.txt      # Python dependencies
├── CLAUDE.md            # Development guidelines
├── TODO.md              # Task breakdown
└── README.md            # Setup instructions
```

---

## Error Handling Strategy

### API Failures
- Retry with exponential backoff (3 attempts)
- Log error and continue
- Send alert if persistent (>5 failures)

### Database Issues
- Integrity check on startup
- Restore from hourly backup if corrupted
- Alert human immediately

### Order Execution Failures
- Cancel partial orders
- Don't create position in database
- Alert human with error details
- Log for manual review

### Monitor Failures
- Log errors but continue monitoring other positions
- Alert if >3 consecutive failures for same position
- Manual intervention required

*See [RUNBOOK.md](RUNBOOK.md) for detailed procedures*

---

## Security Considerations

### API Key Management
- Store in environment variables only
- Never log full keys (show last 4 chars only)
- Use separate keys for dev/prod

### Database Security
- SQLite file permissions (600)
- Hourly encrypted backups
- No sensitive data in logs

### Order Validation
- Pre-flight checks before every order
- Position size limits enforced
- Portfolio exposure limits checked

### Rate Limiting
- Respect API limits (600 req/min for Polymarket)
- Queue requests if approaching limit
- Exponential backoff on rate limit errors

---

## Performance Targets

### Latency
- Market scan cycle: <30 seconds
- Price check cycle: <5 seconds
- Alert delivery: <10 seconds
- Order execution: <60 seconds

### Throughput
- Handle 1000+ markets per scan
- Monitor up to 8 positions simultaneously
- Process 50+ news items per hour

### Reliability
- 99%+ uptime (allow for deployments)
- Zero data loss (backups every hour)
- <5% false alert rate

---

## Scaling Considerations

### Current Design (MVP)
- SQLite database (single file)
- Single-threaded polling
- ~8 concurrent positions max

### Future Scaling (If Needed)
- PostgreSQL for multi-user access
- Async/await for concurrent API calls
- Redis for caching market data
- WebSocket for real-time price updates
- Web dashboard (FastAPI + React)

---

## Testing Strategy

### Unit Tests
- Each filter function tested independently
- Scoring logic verified with known inputs
- Position sizing accuracy validated
- Stop-loss calculation correctness

### Integration Tests
- End-to-end pipeline (collect → detect → decide)
- Database CRUD operations
- API connections (with mocks)
- Telegram message delivery

### Smoke Tests (Pre-Deploy)
- Fetch markets successfully
- Database read/write works
- Telegram sends message
- No Python errors on startup

*See [TODO.md](TODO.md) for test task breakdown*

---

## Deployment

### Development Mode
```bash
# Set environment to development
export ENV=development
export LOG_LEVEL=DEBUG

# Run with test bankroll
export BANKROLL_USD=1000

python main.py
```

### Production Mode
```bash
# Set environment to production
export ENV=production
export LOG_LEVEL=INFO

# Use real bankroll
export BANKROLL_USD=5000

# Run with nohup for background
nohup python main.py > /dev/null 2>&1 &
```

### Monitoring Production
```bash
# Tail logs
tail -f logs/bot.log

# Check database
sqlite3 data/polymarket.db "SELECT COUNT(*) FROM positions WHERE status='active'"

# Check process
ps aux | grep main.py
```

---

## Next Steps

1. **Read [SPEC.md](SPEC.md)** - Understand business requirements
2. **Read [REFERENCE.md](REFERENCE.md)** - Review technical details
3. **Read [TODO.md](TODO.md)** - See development tasks
4. **Read [CLAUDE.md](CLAUDE.md)** - Follow development guidelines
5. **Start building** - Begin with Component 1, Task 1.1
