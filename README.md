# Polymarket Tail-End Arbitrage Bot

A semi-automated trading bot for identifying and executing tail-end arbitrage opportunities on Polymarket prediction markets.

**Target**: 8-15% monthly ROI with <30 minutes daily time commitment

---

## Quick Start

### Prerequisites
- Python 3.10+
- Polymarket account with funded wallet
- Anthropic API key (Claude)
- Telegram account

### Installation

```bash
# Clone repository
git clone <repo-url>
cd polymarket_bot

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Configuration

```bash
# Required environment variables
POLYMARKET_PRIVATE_KEY=0x...
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
BANKROLL_USD=5000
```

### Run

```bash
# Start the bot
python main.py

# Or run in background
nohup python main.py > /dev/null 2>&1 &
```

---

## Project Structure

```
polymarket_bot/
├── config.py              # Configuration and environment variables
├── collectors/            # Data collection modules
│   └── polymarket_api.py  # Polymarket API wrapper
├── tests/                 # Test scripts
│   ├── test_api_stability.py
│   └── test_polymarket_connection.py
├── docs/                  # Documentation
│   ├── SPEC.md
│   ├── ARCHITECTURE.md
│   ├── REFERENCE.md
│   ├── TEMPLATES.md
│   └── RUNBOOK.md
├── .env.example           # Environment variables template
├── requirements.txt       # Python dependencies
├── CLAUDE.md             # Development guidelines
├── TODO.md               # Task breakdown (103 tasks)
└── README.md             # This file
```

---

## Documentation Structure

This project follows a 7-document structure for clarity:

### 📘 Core Documents (Read These First)

1. **[docs/SPEC.md](docs/SPEC.md)** - Business requirements and trading strategy
   - What is tail-end arbitrage?
   - Entry requirements and risk management
   - Performance targets
   - Human-in-loop decision points

2. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - High-level system design
   - Component overview with diagrams
   - Data flow between modules
   - 7-layer architecture explanation
   - Project structure

3. **[CLAUDE.md](CLAUDE.md)** - Development guidelines
   - Incremental development principles
   - Testing philosophy
   - Communication protocols
   - Code style guidelines

4. **[TODO.md](TODO.md)** - Detailed task breakdown
   - 185+ granular tasks across 9 components
   - Estimated time for each task
   - Sequential development order

### 📚 Reference Documents (Lookup When Needed)

5. **[docs/REFERENCE.md](docs/REFERENCE.md)** - Technical reference
   - Database schemas (SQL)
   - API endpoints and authentication
   - Configuration parameters
   - Filter specifications
   - Position sizing formulas
   - Stop-loss calculations

6. **[docs/TEMPLATES.md](docs/TEMPLATES.md)** - Code & message templates
   - Telegram message templates (morning reports, alerts)
   - Claude AI prompt templates
   - Code examples (scanning, executing, monitoring)
   - Bot command handlers

7. **[docs/RUNBOOK.md](docs/RUNBOOK.md)** - Operational procedures
   - Daily operations checklist
   - Weekly/monthly maintenance
   - Troubleshooting guide
   - Emergency procedures
   - Useful commands reference

---

## How It Works

### 1. Data Collection (Every 5 minutes)
- Polls Polymarket API for all markets
- Scrapes news from RSS feeds
- Stores in SQLite database

### 2. Opportunity Detection (Every 5 minutes)
- 8-stage filter pipeline (price → liquidity → risk)
- Scores opportunities by risk-adjusted return
- Returns top 10 candidates

### 3. AI Evaluation (Per opportunity)
- Claude API evaluates each opportunity
- Assesses certainty, risks, reversal scenarios
- Returns: ENTER / SKIP / HUMAN_REVIEW

### 4. Human Approval (Morning, ~10 min)
- Telegram sends top 3-5 opportunities at 8 AM
- Human reviews and approves/skips each
- Commands: `/approve_1`, `/skip_2`, etc.

### 5. Execution (On approval)
- Calculates position size (1/4 Kelly Criterion)
- Calculates adaptive stop-loss (8-18% based on volatility/liquidity)
- Places entry order + stop-loss + take-profit orders
- Stores position in database

### 6. Monitoring (Every 60 seconds)
- Tracks prices, liquidity, news for open positions
- Auto-executes stop-loss and take-profit orders
- Sends Telegram alerts for issues
- Human decides on emergencies

---

## Daily Workflow

**Morning (8:00 AM)**:
1. Receive Telegram morning report with top opportunities
2. Review each opportunity (question, price, risk, AI reasoning)
3. Approve or skip each one: `/approve_1 $350` or `/skip_1`

**Throughout Day (As needed)**:
- Respond to alerts (price drops, news, liquidity issues)
- Decide: `/exit_1` (close position) or `/hold` (wait)

**Evening (5:00 PM)**:
- Check position dashboard: `/positions`
- Review day's P/L

**Weekly (Sunday)**:
- Review performance report: `/weekly_report`
- Adjust filter parameters if needed

**Total Time**: <30 minutes per day

---

## System Architecture

```
HUMAN (Telegram) ←→ BOT ←→ POLYMARKET
        ↓              ↓
    Commands      Monitoring
        ↓              ↓
    Approval ←→ Opportunities ←→ Data Collection
        ↓              ↓
    Execution ←→ AI Decision ←→ News/Prices
        ↓              ↓
    Positions ←→ Database ←→ History
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed component design.

---

## Tech Stack

- **Python 3.10+** - Main language
- **py-clob-client** - Polymarket API wrapper
- **anthropic** - Claude AI for decision-making
- **python-telegram-bot** - User interface
- **SQLite** - Local database
- **APScheduler** - Task scheduling
- **pandas** - Data manipulation
- **feedparser** - News scraping

See [docs/REFERENCE.md](docs/REFERENCE.md) for complete API details.

---

## Project Status

**Current Phase**: Documentation complete, ready for development

**Next Steps**:
1. Review all documentation
2. Begin Component 1: Data Collection (see [TODO.md](TODO.md))
3. Follow incremental development approach (see [CLAUDE.md](CLAUDE.md))

**Timeline**: 4 weeks (80-100 hours total)
- Week 1: Data collection + Database
- Week 2: Filters + Scoring + AI
- Week 3: Execution + Monitoring
- Week 4: Telegram + Integration + Deployment

---

## Key Features

✅ **Semi-Automated** - Human approves trades, bot executes and monitors
✅ **AI-Powered** - Claude evaluates opportunities for hidden risks
✅ **Risk Management** - Adaptive stop-losses, portfolio limits, category diversification
✅ **Real-Time Monitoring** - Price, liquidity, and news tracking every 60 seconds
✅ **Telegram Interface** - All interactions via mobile app
✅ **Comprehensive Testing** - Unit, integration, and smoke tests
✅ **Production-Ready** - Error handling, logging, backups, recovery procedures

---

## Performance Targets

**Financial**:
- Win rate: ≥70%
- Monthly ROI: 8-15%
- Max drawdown: <20%
- Average trade: 4-6% profit, 1-3 day hold

**Operational**:
- Daily opportunities: 3-5 quality candidates
- Time commitment: <30 min/day
- Bot uptime: 99%+

See [docs/SPEC.md](docs/SPEC.md) for detailed success criteria.

---

## Risk Scenarios

The system mitigates 5 key risk scenarios:

1. **Liquidity Evaporation** - Only enter markets with 10x liquidity, alert on decay
2. **Oracle Manipulation** - Skip subjective criteria, track dispute rates
3. **Correlation Cascade** - Limit category exposure to 40%
4. **Black Swan Reversal** - Require event finality, official confirmation
5. **Manipulation Window** - Don't enter <6h to settlement, widen stops

See [docs/SPEC.md](docs/SPEC.md#risk-scenarios--mitigation) for detailed mitigation strategies.

---

## Development Guidelines

**Follow these principles** (see [CLAUDE.md](CLAUDE.md)):

1. ✅ **Incremental** - Write 10-50 lines, test, then proceed
2. ✅ **Test Everything** - Every function tested before moving on
3. ✅ **Ask When Uncertain** - Don't guess, clarify requirements
4. ✅ **Security First** - Never hardcode API keys, always use .env
5. ✅ **Follow TODO** - Complete tasks in exact order: 1.1.1 → 1.1.2 → 1.1.3

**This is real money. Code quality, testing, and safety are paramount.**

---

## Troubleshooting

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for:
- Common issues and solutions
- Bot not running
- No opportunities found
- Orders not executing
- Stop-loss not triggering
- Database corruption recovery

---

## Maintenance

**Daily**: Check morning report, respond to alerts
**Weekly**: Review performance, adjust parameters
**Monthly**: Financial analysis, cost review, dependency updates

See [docs/RUNBOOK.md](docs/RUNBOOK.md#maintenance-schedule) for detailed procedures.

---

## Contributing

This is a personal trading bot. For questions or issues:

1. Check [docs/RUNBOOK.md](docs/RUNBOOK.md) troubleshooting section
2. Review logs: `tail -f logs/bot.log`
3. Consult relevant documentation

---

## Resources

- **Polymarket**: https://polymarket.com
- **Polymarket Docs**: https://docs.polymarket.com
- **Anthropic (Claude)**: https://console.anthropic.com
- **Telegram Bot API**: https://core.telegram.org/bots/api

---

## License

Private project. All rights reserved.

---

## Version History

**v1.0** - Documentation complete (Current)
- 7-document structure
- 185+ task breakdown
- Ready for development

**v2.0** - MVP (Target: Week 2)
- Data collection working
- Manual trade execution

**v3.0** - Automation (Target: Week 4)
- Full automation with Telegram interface
- Ready for paper trading

**v4.0** - Production (Target: Week 6+)
- Live trading with real money
- Monitoring and optimization

---

## Getting Started

1. **Read documentation in this order**:
   - [docs/SPEC.md](docs/SPEC.md) - Understand the strategy
   - [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - Understand the system
   - [CLAUDE.md](CLAUDE.md) - Understand development approach
   - [TODO.md](TODO.md) - See task breakdown

2. **Set up environment**:
   - Install Python 3.10+
   - Create virtual environment
   - Install dependencies
   - Configure .env file

3. **Start development**:
   - Begin with TODO Task 1.1.1
   - Follow incremental approach
   - Test after each task
   - Mark tasks complete as you go

4. **Questions?**
   - Reference [docs/REFERENCE.md](docs/REFERENCE.md) for technical details
   - Reference [docs/TEMPLATES.md](docs/TEMPLATES.md) for code examples
   - Reference [docs/RUNBOOK.md](docs/RUNBOOK.md) for operations

---

**Ready to build? Start with Task 1.1.1 in [TODO.md](TODO.md)!** 🚀
