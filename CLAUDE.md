# Instructions for Claude Code

## Your Role

You are building a Polymarket tail-end arbitrage trading bot with a human operator. This is a semi-automated system where:
- You build the automation
- Human makes final trading decisions
- System assists with data collection, filtering, monitoring

## Critical Principles

### 1. Incremental Development
**NEVER write large blocks of code at once.**

For every task:
1. Write minimal code (10-50 lines)
2. Test immediately
3. Explain what you built
4. Wait for human approval before continuing

Example:
- ❌ BAD: "I'll build the entire scanner module (500 lines)"
- ✅ GOOD: "First, let's connect to Polymarket API and fetch one market (15 lines)"

### 2. Test Before Proceed
After writing ANY code:
1. Run it
2. Show output/results
3. Explain: "This works because..."
4. Ask: "Should I proceed to next step?"

Never assume code works. Always verify.

### 3. Explain as You Go
When you write code, explain:
- What this code does
- Why you made this design choice
- What could go wrong
- How to verify it's working

Think of human as learning partner, not just client.

### 4. Ask When Uncertain
If SPEC.md is ambiguous:
- Don't guess
- Ask: "Should I implement X or Y?"
- Wait for clarification

If requirements conflict:
- Point out the conflict
- Suggest resolution
- Wait for decision

---

## Project Structure You'll Create
```
polymarket_bot/
├── config.py              # All settings, API keys
├── main.py               # Orchestrator (run this)
│
├── data/
│   ├── polymarket.db     # SQLite database
│   └── backups/          # Hourly DB backups
│
├── collectors/
│   ├── polymarket_api.py # API wrapper
│   └── news_scraper.py   # RSS feed scraper
│
├── detectors/
│   ├── scanner.py        # Market scanner
│   ├── filters.py        # 8-stage filter pipeline
│   └── scorer.py         # Opportunity scoring
│
├── ai/
│   └── decision_agent.py # Claude API integration
│
├── execution/
│   ├── sizer.py          # Position sizing (Kelly)
│   ├── stop_calculator.py# Adaptive stop-loss
│   └── trader.py         # Order execution
│
├── monitoring/
│   ├── price_monitor.py  # Track positions
│   ├── liquidity_monitor.py
│   └── news_monitor.py   # Keyword alerts
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
│   └── bot.log           # Daily logs
│
├── docs/
│   ├── SPEC.md           # This file
│   ├── ARCHITECTURE.md   # System design
│   └── TODO.md           # Task breakdown
│
├── requirements.txt      # Dependencies
└── README.md            # Setup instructions
```

---

## Development Workflow

### Step 1: Read Documentation
Before writing ANY code:
1. Read SPEC.md (full specification)
2. Read ARCHITECTURE.md (system design)
3. Read TODO.md (task breakdown)
4. Ask human: "I've read the docs. Should I start with Component 1, Task 1.1?"

### Step 2: Confirm Task
Before each task:
1. State: "I'm about to build [X]. This will take ~[Y] lines of code."
2. Explain approach
3. Wait for: "Proceed" or feedback

### Step 3: Build Minimally
Write the SMALLEST code that works:
- Start with hardcoded values
- Test with one example
- Ignore error handling initially
- Focus on: "Does core logic work?"

### Step 4: Test & Show
- Run the code
- Show output
- Explain: "This output means..."
- Ask: "Does this match expectations?"

### Step 5: Improve
After human confirms:
- Add error handling
- Add logging
- Add documentation
- Refactor if needed

### Step 6: Integration Test
Before moving to next component:
- Test with previous components
- Verify end-to-end flow works
- Show: "Component A + B now working together"

---

## Code Style Guidelines

### Minimal & Readable
```python
# ❌ BAD: Over-engineered
class AbstractMarketDataProvider:
    def get_data(self) -> Union[Market, None]:
        ...

# ✅ GOOD: Simple & clear
def fetch_markets():
    """Get all active markets from Polymarket."""
    response = requests.get(API_URL)
    return response.json()
```

### Comments for Clarity
```python
# ❌ BAD: No explanation
if ratio > 10:
    return True

# ✅ GOOD: Explains "why"
# Liquidity must be 10x position size for safe exit
if liquidity_ratio > 10:
    return True
```

### Error Handling
```python
# ❌ BAD: Silent failure
try:
    data = api.get()
except:
    pass

# ✅ GOOD: Informative error
try:
    data = api.get_markets()
except requests.HTTPError as e:
    logger.error(f"API failed: {e}")
    return []  # Return empty, don't crash
```

---

## Testing Protocol

### For Every Function
1. Write function
2. Write test case (even if informal)
3. Run test
4. Show result: "Test passed: function returns X"

Example:
```python
# Function
def calculate_true_profit(entry, exit, fees):
    gross = exit - entry
    net = gross * (1 - fees)
    return net / entry

# Test
assert abs(calculate_true_profit(0.93, 1.0, 0.02) - 0.0538) < 0.001
print("✓ True profit calculation correct")
```

### For Integration
Test with real API (small requests):
```python
# Test Polymarket connection
markets = fetch_markets()
print(f"✓ Fetched {len(markets)} markets")
print(f"✓ Sample: {markets[0]['question']}")
```

---

## Common Pitfalls to Avoid

### 1. Building Too Much At Once
- ❌ "I'll build the entire scanner with all 8 filters"
- ✅ "I'll build filter 1 (price range) first"

### 2. Not Testing Immediately
- ❌ Write 200 lines, then test
- ✅ Write 20 lines, test, then continue

### 3. Assuming Requirements
- ❌ "I think they want X, so I'll build X"
- ✅ "SPEC says Y, but I'm unsure. Asking..."

### 4. Ignoring Errors
- ❌ API fails, code crashes, move on
- ✅ API fails, handle gracefully, log error, continue

### 5. Over-Engineering
- ❌ Abstract factory pattern for simple function
- ✅ Simple function that works

---

## Communication Protocol

### Starting a Task
```
Claude: "Starting Task 2.1: Build price range filter

I'll write a function that:
1. Takes a market dict
2. Checks if YES price between 0.92-0.97
3. Returns True/False

Estimated: 10 lines, 2 min

Proceed?"
```

### After Completing
```
Claude: "✓ Price filter complete

Code written: 12 lines in filters.py
Tested with: 5 sample markets
Results: 
  - Market A ($0.95): PASS
  - Market B ($0.85): REJECT
  - Market C ($0.98): REJECT

All tests passed. This filter will reject ~70% of markets.

Ready for Task 2.2 (volume filter)?"
```

### When Stuck
```
Claude: "⚠ Issue with liquidity calculation

Problem: API returns bid depth as array, but SPEC assumes single number.

Options:
A) Sum all bids in array (my recommendation)
B) Use only top bid
C) Ask human for clarification

Which approach should I use?"
```

---

## Security Reminders

### API Keys
- NEVER commit API keys to code
- Load from environment variables
- Show in example: `os.getenv('POLYMARKET_PRIVATE_KEY')`

### Private Key Handling
- Warn: "Store private key securely"
- Never log full private key
- If must log: Show only last 4 chars

### Database
- Use parameterized queries (prevent SQL injection)
- Backup before migrations
- Test on copy, not production DB

---

## Completion Criteria

A task is "done" when:
1. ✅ Code written and tested
2. ✅ Tests pass
3. ✅ Documented (docstrings)
4. ✅ Logged appropriately
5. ✅ Human approves
6. ✅ Integrated with previous components
7. ✅ No console errors

Don't move forward until ALL criteria met.

---

## Final Reminders

- **Small steps**: 10-50 lines at a time
- **Test everything**: Never assume it works
- **Explain clearly**: Human is learning too
- **Ask when unsure**: Better than guessing wrong
- **Human approves**: Wait for "proceed" signal

You're not just building code. You're teaching a human to trade systematically.

Start slow, build correctly, explain thoroughly.