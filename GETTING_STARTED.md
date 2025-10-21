# Getting Started - Quick Guide

**Welcome!** This guide will get you started with building the Polymarket trading bot in 4 weeks.

---

## ⚠️ Important First Steps

### 1. Understand the Revised Plan

**We're building a SIMPLIFIED MVP** (103 tasks, not 185):
- **Realistic targets**: 3-5% monthly ROI (not 8-15%)
- **Phase 1 position sizes**: $100-200 (not $500-1000)
- **Prove the edge first**, then scale up

**Key simplifications**:
- ❌ No adaptive stop-loss (fixed 10% for now)
- ❌ No Kelly Criterion (fixed $200 positions for now)
- ✅ News scraping kept (your must-have)
- ✅ Liquidity monitoring kept (your must-have)
- ✅ Take-profit laddering kept (your must-have)

See [TODO_SIMPLIFIED.md](TODO_SIMPLIFIED.md) for the full 103-task plan.

---

## 📚 Read These Documents First (30 minutes)

**In this order**:

1. **[docs/SPEC.md](docs/SPEC.md)** (10 min)
   - Understand what tail-end arbitrage is
   - Learn the entry criteria
   - See risk scenarios

2. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** (10 min)
   - High-level system design
   - How components interact
   - Data flow

3. **[CLAUDE.md](CLAUDE.md)** (5 min)
   - Development principles
   - How we'll work together
   - Testing philosophy

4. **[TODO_SIMPLIFIED.md](TODO_SIMPLIFIED.md)** (5 min)
   - Skim the 103 tasks
   - See weekly milestones
   - Understand the flow

---

## 🛠️ Set Up Your Environment (30 minutes)

### 1. Install Python

```bash
# Check Python version (need 3.10+)
python --version

# If not installed or <3.10, install from https://www.python.org/
```

### 2. Create Project Directory

```bash
cd ~/Desktop
mkdir polymarket_bot
cd polymarket_bot

# Initialize git
git init
```

### 3. Create Virtual Environment

```bash
# Create virtualenv
python -m venv venv

# Activate it
# On Mac/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Your prompt should now show (venv)
```

### 4. Create .env File

```bash
# Create .env file (don't commit this!)
touch .env

# Add to .gitignore
echo "venv/" >> .gitignore
echo ".env" >> .gitignore
echo "*.db" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore
```

**Edit .env and add** (leave values blank for now):
```bash
# Polymarket
POLYMARKET_PRIVATE_KEY=

# Claude AI
ANTHROPIC_API_KEY=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Trading
BANKROLL_USD=1000
MAX_POSITION_SIZE=200
MAX_POSITIONS=3

# Database
DATABASE_PATH=./data/polymarket.db

# Logging
LOG_LEVEL=INFO
LOG_FILE=./logs/bot.log
```

### 5. Create Directory Structure

```bash
mkdir -p data logs collectors detectors ai execution monitoring interface database utils tests docs
```

---

## 🔑 Get API Keys (60 minutes)

### 1. Polymarket Account

1. Go to https://polymarket.com
2. Create account (connect wallet)
3. Fund wallet with small test amount ($500-1000 for Phase 1)
4. Get your private key:
   - **IMPORTANT**: Keep this SECRET
   - Add to .env: `POLYMARKET_PRIVATE_KEY=0x...`

### 2. Anthropic (Claude) API

1. Go to https://console.anthropic.com
2. Sign up for account
3. Add $20-50 credit (will last 1-2 months)
4. Create API key
5. Add to .env: `ANTHROPIC_API_KEY=sk-ant-...`

**Cost estimate**: ~$80-120/month for 50-100 evaluations/day

### 3. Telegram Bot

1. Open Telegram app
2. Search for `@BotFather`
3. Send: `/newbot`
4. Follow prompts (choose name and username)
5. Copy the bot token
6. Add to .env: `TELEGRAM_BOT_TOKEN=123456789:ABC...`

**Get your Chat ID**:
1. Search for `@userinfobot` on Telegram
2. Start conversation
3. It will send your chat ID
4. Add to .env: `TELEGRAM_CHAT_ID=123456789`

---

## 🧪 Test Your Setup (15 minutes)

### 1. Test Python

```bash
python -c "print('Python works!')"
# Should print: Python works!
```

### 2. Install Test Dependencies

```bash
pip install py-clob-client anthropic python-telegram-bot
```

### 3. Test Polymarket API

Create `test_polymarket.py`:
```python
import os
from dotenv import load_dotenv
from py_clob_client import Client

load_dotenv()
private_key = os.getenv('POLYMARKET_PRIVATE_KEY')

if not private_key:
    print("❌ POLYMARKET_PRIVATE_KEY not set in .env")
else:
    print(f"✅ API key loaded: ...{private_key[-4:]}")
    # Add test API call here once you have the client set up
```

Run: `python test_polymarket.py`

### 4. Test Claude API

Create `test_claude.py`:
```python
import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
api_key = os.getenv('ANTHROPIC_API_KEY')

if not api_key:
    print("❌ ANTHROPIC_API_KEY not set in .env")
else:
    print(f"✅ API key loaded: ...{api_key[-4:]}")
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=100,
        messages=[{"role": "user", "content": "Say hello!"}]
    )
    print(f"✅ Claude response: {response.content[0].text}")
```

Run: `python test_claude.py`

### 5. Test Telegram Bot

Create `test_telegram.py`:
```python
import os
from dotenv import load_dotenv
from telebot import TeleBot

load_dotenv()
bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
chat_id = os.getenv('TELEGRAM_CHAT_ID')

if not bot_token or not chat_id:
    print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
else:
    print(f"✅ Bot token: ...{bot_token[-10:]}")
    print(f"✅ Chat ID: {chat_id}")
    bot = TeleBot(bot_token)
    bot.send_message(chat_id, "✅ Telegram bot working!")
    print("✅ Message sent! Check your Telegram")
```

Run: `python test_telegram.py`

**Expected**: You receive a message on Telegram

---

## 📋 Your First Week Plan

### Week 1: Foundation + Manual Trading

**Your Tasks** (parallel with bot development):

**Day 1-2**: Environment setup (above) + Read docs
**Day 3-7**: Manual trading to validate strategy

**Manual Trading Checklist**:
1. Find 20-30 markets on Polymarket
2. Apply filters manually:
   - Price: $0.92-0.97
   - Volume: >$50k daily
   - Liquidity: Deep order book
   - Settlement: 6 hours - 7 days
   - Event: Already concluded
3. Identify 3-5 opportunities
4. Execute 3-5 small trades ($100-200 each)
5. Track results in spreadsheet:

| Date | Market | Entry | Exit | Hold Time | P/L | P/L % | Notes |
|------|--------|-------|------|-----------|-----|-------|-------|
| 11/15 | Warriors win | $0.93 | $1.00 | 18h | +$7 | +7.5% | Smooth |
| 11/16 | Fed rate hike | $0.94 | $0.88 | 6h | -$6 | -6.4% | Hit stop |

**Success Criteria** (after 5 trades):
- Win rate ≥50% (at least break-even)
- No catastrophic losses (>15%)
- Found enough opportunities (3-5/day)

**If not met**: Strategy needs revision before building bot

---

## 🚀 Start Building (Week 1, While You Trade)

**Once environment is set up, start Task 1.1.1**:

See [TODO_SIMPLIFIED.md](TODO_SIMPLIFIED.md#week-1-foundation-20-tasks)

**First task**: Install py-clob-client and test connection
- This takes 10 minutes
- Tests your Polymarket API access
- If it works → proceed to next task
- If it fails → debug API keys

**Development approach**:
1. Read task description
2. Write 10-50 lines of code
3. Test immediately
4. Show results
5. Ask: "Proceed to next task?"
6. Mark task complete: `[✓]`

---

## ⚠️ Critical Reminders

### 1. Position Sizes

**Phase 1** (Weeks 1-4):
- $100-200 per position
- Max 3 concurrent positions
- Total at risk: $300-600

**Why**: Prove the strategy works before risking more

**If you start with $500-1000 positions**:
- You need $5,000-10,000 bankroll
- Risk of losing $500+ in one bad week
- Better to scale gradually

### 2. Win Rate Expectations

**Realistic**:
- 60-70% win rate (6-7 winners out of 10)
- 30-40% will hit stops (this is NORMAL)
- 3-5% monthly ROI initially

**Unrealistic**:
- 80%+ win rate (too optimistic)
- 8-15% monthly ROI from day 1 (unlikely)
- No losing weeks (impossible)

### 3. Time Commitment

**Realistic**:
- Morning: 15 min (review opportunities)
- Alerts: 15-30 min (respond to issues)
- Evening: 5 min (check positions)
- **Total: 35-50 min/day**

Plus:
- Debugging bot: 1-2 hours/week
- Manual trades: 30 min/week (Phase 1)

### 4. Strategy Validation

**Before deploying Phase 2**:
- Minimum 20 trades completed
- Win rate ≥60%
- Monthly ROI ≥3%
- Max drawdown <15%

**If not met**: Don't scale up, revise strategy

---

## 📞 Need Help?

**During development**:
1. Check [docs/TEMPLATES.md](docs/TEMPLATES.md) for code examples
2. Check [docs/REFERENCE.md](docs/REFERENCE.md) for technical details
3. Check [docs/RUNBOOK.md](docs/RUNBOOK.md) for troubleshooting

**When stuck**:
1. Read error message carefully
2. Check logs: `tail -f logs/bot.log`
3. Google the error
4. Ask specific questions

---

## ✅ Pre-Flight Checklist

Before starting Task 1.1.1, verify:

- [ ] Python 3.10+ installed
- [ ] Virtual environment created and activated
- [ ] .env file created with API keys
- [ ] Polymarket account funded ($500-1000)
- [ ] Claude API account funded ($20-50)
- [ ] Telegram bot created and tested
- [ ] Directory structure created
- [ ] Read SPEC.md, ARCHITECTURE.md, CLAUDE.md
- [ ] Understand the 4-week plan
- [ ] Ready to test-trade manually

---

**All set? Let's build!** 🚀

**Next step**: Open [TODO_SIMPLIFIED.md](TODO_SIMPLIFIED.md) and start with Task 1.1.1!
