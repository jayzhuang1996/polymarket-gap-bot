# System Architecture

## Overview Diagram
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

## Component Details

### 1. Data Collection Module

**Purpose**: Gather all necessary data for decision-making

**Sub-components**:
```
collectors/
├── polymarket_api.py
│   ├─ fetch_markets() → List[Market]
│   ├─ fetch_order_book(market_id) → OrderBook
│   └─ fetch_historical_prices(market_id, hours) → List[Price]
│
└── news_scraper.py
    ├─ fetch_rss_feeds() → List[NewsItem]
    ├─ match_to_markets(news, markets) → Dict[market_id, List[News]]
    └─ analyze_sentiment(headline) → float [-1, 1]
```

**Data Flow**:
1. Scheduler triggers every 5 min
2. Fetch all markets from Polymarket
3. For each market, fetch order book
4. Store in database with timestamp
5. Scrape news feeds (every 15 min)
6. Match news to markets via keywords
7. Store news with sentiment score

**Output**: Database populated with current market state

---

### 2. Opportunity Detection Module

**Purpose**: Filter markets, score opportunities, rank by attractiveness

**Sub-components**:

detectors/
├── scanner.py
│   └─ scan_opportunities() → List[Opportunity]
│       ├─ Loads markets from DB
│       ├─ Applies filters
│       ├─ Calculates scores
│       └─ Returns ranked list
│
├── filters.py
│   ├─ filter_price_range(markets) → List[Market]
│   ├─ filter_liquidity(markets) → List[Market]
│   ├─ filter_settlement_window(markets)
│   ├─ filter_price_range(markets) → List[Market]
│   ├─ filter_liquidity(markets) → List[Market]
│   ├─ filter_settlement_window(markets) → List[Market]
│   ├─ filter_resolution_clarity(markets) → List[Market]
│   ├─ filter_event_finality(markets) → List[Market]
│   ├─ filter_portfolio_limits(markets, positions) → List[Market]
│   └─ calculate_true_profit(market) → float
│
└── scorer.py
    ├─ calculate_certainty_factor(market) → float
    ├─ calculate_liquidity_score(market) → float
    ├─ calculate_manipulation_risk(market) → float
    └─ calculate_final_score(market) → float


Input: All markets (500-1000)
   ↓
Stage 1: Price Range ($0.92-$0.97)
   → Rejects ~700 markets
   ↓
Stage 2: Liquidity (volume >$50k, depth >$20k)
   → Rejects ~150 markets
   ↓
Stage 3: Settlement Window (6h - 7d)
   → Rejects ~80 markets
   ↓
Stage 4: Spread (<3%)
   → Rejects ~30 markets
   ↓
Stage 5: Exit Path Liquidity (>10x position)
   → Rejects ~20 markets
   ↓
Stage 6: Resolution Clarity (score ≥8)
   → Rejects ~10 markets
   ↓
Stage 7: Event Finality (score ≥8)
   → Rejects ~5 markets
   ↓
Stage 8: Portfolio Limits (category/time exposure)
   → Rejects ~2 markets
   ↓
Output: 3-8 quality opportunities


score = (true_profit × certainty × liquidity × (1 - manipulation_risk)) / days_to_settlement

Where:
- true_profit = (1.00 - entry_price) - slippage - fees
- certainty = event_finality_score / 10
- liquidity = min(liquidity_ratio / 20, 1.0)
- manipulation_risk = 0.1 if >24h, 0.3 if <6h
- days_to_settlement = hours / 24
```

**Output**: Top 10 scored opportunities passed to AI agent

---

### 3. AI Decision Engine

**Purpose**: LLM evaluation of opportunities for final filtering

**Sub-component**:
```
ai/
└── decision_agent.py
    ├─ evaluate_opportunity(market, context) → Decision
    ├─ build_prompt(market, news, comments) → str
    └─ parse_response(llm_output) → Dict
```

**Prompt Structure**:
```
System: You are a risk analyst for prediction markets.

User: 
Market: {question}
Current Price: ${price} ({price}% implied probability)
Category: {category}
Settlement: {hours}h away

Event Status:
{news_summary}

Polymarket Comments (sample):
{top_3_comments}

Resolution Criteria:
{criteria}

Risk Scores (0-10):
- Resolution Clarity: {clarity_score}/10
- Event Finality: {finality_score}/10
- Liquidity Health: {liquidity_ratio}x position size

Tasks:
1. Is the outcome truly ≥92% certain? Consider ALL reversal scenarios.
2. Is the resolution criteria objective and verifiable?
3. Has the physical event concluded (not just "called" by media)?
4. List specific risks that could cause outcome reversal.
5. Recommend: ENTER / SKIP / HUMAN_REVIEW

Output as JSON:
{
  "certainty_score": 0.0-1.0,
  "reasoning": "...",
  "reversal_scenarios": ["...", "..."],
  "recommendation": "ENTER|SKIP|HUMAN_REVIEW",
  "confidence": "low|medium|high"
}



if recommendation == "ENTER" and certainty_score >= 0.92:
    → Add to approved list
elif recommendation == "HUMAN_REVIEW":
    → Flag for manual review
else:
    → Reject opportunity
```

**Output**: 3-5 approved opportunities (or flagged for human review)

---

### 4. Execution Module

**Purpose**: Calculate position size, place orders, set stops/TPs

**Sub-components**:
```
execution/
├── sizer.py
│   ├─ calculate_kelly(edge, odds, bankroll) → float
│   ├─ apply_uncertainty_adjustment(kelly, certainty) → float
│   └─ apply_portfolio_constraints(size, positions) → float
│
├── stop_calculator.py
│   ├─ calculate_base_stop(entry_price) → float
│   ├─ adjust_for_volatility(base, price_history) → float
│   ├─ adjust_for_liquidity(stop, liquidity_ratio) → float
│   └─ adjust_for_time(stop, hours_to_settlement) → float
│
└── trader.py
    ├─ place_entry_order(market_id, size, price) → Order
    ├─ place_stop_loss(tokens, stop_price) → Order
    ├─ place_take_profit(tokens, tp_prices) → List[Order]
    └─ verify_order_filled(order_id) → bool
```

**Position Sizing Flow**:
```
1. Calculate edge:
   - Your certainty: 95% (from AI)
   - Market price: 93%
   - Edge: 95% - 93% = 2%
   - Apply safety margin: 2% × 0.97 = 1.94%

2. Kelly Criterion:
   - Full Kelly = Edge / (1 - Market_Price)
   - Full Kelly = 0.0194 / 0.07 = 27.7% of bankroll
   - 1/4 Kelly (safety) = 6.9% of bankroll
   - With $5,000 bankroll = $345

3. Apply constraints:
   - Hard cap: $500 max → $345 OK ✓
   - Portfolio limit: Max 80% deployed
   - Current deployed: $2,800 (56%)
   - Can deploy: $1,200 more
   - $345 OK ✓

4. Final position: $345 (rounded to $350)
```

**Stop-Loss Calculation Flow**:
```
1. Base stop: 10% below entry

2. Volatility adjustment:
   - Price StdDev last 6h: 3%
   - Adjustment: +3% × 1.5 = +4.5%
   - New stop: 10% + 4.5% = 14.5%

3. Liquidity adjustment:
   - Liquidity ratio: 12x
   - If 10-20x: No adjustment (1.0x)
   - Stop remains: 14.5%

4. Time adjustment:
   - Hours to settlement: 18h
   - If <6h: Multiply by 1.5
   - Currently >6h: No adjustment (1.0x)
   - Stop remains: 14.5%

5. Final stop: 15% below entry (rounded up)
   - Entry: $0.93
   - Stop: $0.79
```

**Order Placement Sequence**:
```
1. Pre-flight checks:
   ✓ Current price still within range?
   ✓ Liquidity still sufficient?
   ✓ No breaking news last 5 min?
   ✓ Portfolio limits OK?

2. Place entry order:
   → Limit buy @ $0.93

3. Wait for fill (max 60 seconds)
   → FILLED at $0.93 ✓

4. Immediately place exit orders:
   → Stop-loss: Sell 350 tokens @ $0.79 (GTC)
   → TP1: Sell 115 tokens @ $0.97 (GTC)
   → TP2: Sell 115 tokens @ $0.99 (GTC)

5. Store position in database:
   → All parameters logged

6. Notify user via Telegram:
   → "✅ Entered Warriors @ $0.93 | $350 deployed"
```

**Output**: Position opened, tracked in database, user notified

---

### 5. Monitoring System

**Purpose**: Track open positions, detect issues, execute exits

**Sub-components**:
```
monitoring/
├── price_monitor.py
│   ├─ check_positions() → List[Alert]  (runs every 60s)
│   ├─ detect_sudden_drop(position) → bool
│   ├─ check_stop_loss_trigger(position) → bool
│   └─ check_take_profit_trigger(position) → bool
│
├── liquidity_monitor.py
│   ├─ check_liquidity_health() → List[Alert]  (runs every 60min)
│   ├─ calculate_decay_rate(position) → float
│   └─ estimate_exit_slippage(position) → float
│
└── news_monitor.py
    ├─ monitor_position_news() → List[Alert]  (runs every 60s)
    ├─ extract_keywords(position) → List[str]
    ├─ match_news_to_keywords(news, keywords) → List[Match]
    └─ assess_sentiment(matched_news) → float
```

**Price Monitoring Loop** (every 60 seconds):
```
FOR each open position:
    
    current_price = get_current_price(market_id)
    previous_price = get_price_1min_ago(market_id)
    
    # Check 1: Sudden drop
    IF (previous_price - current_price) / previous_price > 0.03:
        ALERT: "⚠️ {market} dropped {drop}% in 60 seconds"
    
    # Check 2: Stop-loss trigger
    IF current_price <= position.stop_loss_price:
        EXECUTE: Sell position at market
        ALERT: "🛑 Stop-loss hit: {market} @ ${current_price}"
        UPDATE: Position status = 'stopped_out'
    
    # Check 3: Take-profit trigger
    IF current_price >= position.tp1_price AND not position.tp1_executed:
        EXECUTE: Sell 33% of position
        ALERT: "💰 Take-profit-1 hit: {market} @ ${current_price}"
        UPDATE: position.tokens_remaining
    
    # Check 4: Approaching stop
    IF current_price < position.stop_loss_price * 1.02:
        ALERT: "🚨 Within 2% of stop-loss: {market}"
```

**Liquidity Monitoring Loop** (every 60 minutes):
```
FOR each open position:
    
    current_depth = calculate_bid_depth(market_id, stop_loss_price)
    entry_depth = position.liquidity_at_entry
    
    decay_pct = (entry_depth - current_depth) / entry_depth
    
    IF decay_pct > 0.50:
        ALERT: "⚠️ Liquidity decaying: {market} (down {decay_pct}%)"
        PROMPT: "/exit_now or /hold"
    
    IF decay_pct > 0.70:
        ALERT: "🚨 CRITICAL: Liquidity crisis for {market}"
        PROMPT: "Consider immediate exit"
    
    # Calculate decay velocity
    decay_rate = (current_depth - depth_1h_ago) / depth_1h_ago
    
    IF decay_rate < -0.30:  # Dropping 30%/hour
        ALERT: "⚠️ Liquidity rapidly decaying: {market}"
```

**News Monitoring Loop** (every 60 seconds for open positions):
```
FOR each open position:
    
    keywords = extract_keywords(position.market_question)
    # Example: "Warriors" + "Lakers" + "game" + "cancelled|reversed"
    
    recent_news = fetch_news_since(last_check_time)
    
    matches = []
    FOR article in recent_news:
        IF any(keyword in article.headline for keyword in keywords):
            sentiment = analyze_sentiment(article.headline)
            matches.append((article, sentiment))
    
    FOR article, sentiment in matches:
        IF sentiment < -0.5:  # Negative news
            ALERT: "📰 Negative news: {article.headline}"
            PROMPT: "/emergency_exit or /read_more or /hold"
```

**Manipulation Window Detection**:
```
FOR each open position:
    
    hours_to_settlement = (settlement_date - now) / 3600
    
    IF hours_to_settlement <= 6 AND not position.in_manipulation_window:
        ALERT: "⚠️ Entering manipulation window (<6h): {market}"
        
        # Auto-tighten stop-loss
        new_stop = position.stop_loss_price * 0.85  # Widen by 15%
        UPDATE position.stop_loss_price = new_stop
        
        NOTIFY: "Stop-loss widened to ${new_stop} (manipulation protection)"
        UPDATE position.in_manipulation_window = True
```

**Output**: Real-time alerts, auto-executed exits, position updates

---

### 6. Telegram Interface

**Purpose**: Human interaction layer for approvals, alerts, commands

**Sub-component**:
```
interface/
└── telegram_bot.py
    ├─ send_morning_report(opportunities) → None
    ├─ handle_approve_command(message) → None
    ├─ handle_skip_command(message) → None
    ├─ handle_positions_command(message) → None
    ├─ handle_exit_command(message) → None
    ├─ send_alert(alert_type, message) → None
    └─ format_opportunity(opportunity) → str
```

**Message Types**:

**1. Morning Report** (8:00 AM daily):
```
🎯 Top 5 Tail-End Opportunities (Nov 15, 8:00 AM)

1. ⭐ Warriors beat Lakers
   Price: $0.93 | True Profit: 4.8%
   Stop: 15% adaptive | Max Loss: $52
   Risk: ✅ LOW (finality: 10/10, clarity: 10/10)
   AI: 98% certain | Settles: 18 hours
   Reasoning: "Game concluded, official score recorded"
   /approve_1 $350 | /skip_1 | /details_1

2. ⭐ Fed raises rates
   Price: $0.94 | True Profit: 3.2%
   Stop: 12% adaptive | Max Loss: $38
   Risk: ⚠️ MEDIUM (settlement in 16h)
   AI: 91% certain | Settles: 16 hours
   Reasoning: "Announcement made, no reversal path"
   /approve_2 $280 | /skip_2 | /details_2

3. ⚠️ GDP exceeds 3%
   Price: $0.92 | True Profit: 5.1%
   Stop: 18% adaptive | Max Loss: $65
   Risk: ⚠️ MEDIUM (clarity: 7/10)
   AI: HUMAN_REVIEW - Subjective resolution criteria
   /details_3 | /skip_3

📊 Portfolio Status:
   Active: 5 positions | Deployed: $1,680 (33.6%)
   Available: $3,320 | Reserve: $1,000
   Category: Sports 40%, Econ 30%, Politics 30% ✓
```

**2. Price Drop Alert**:
```
⚠️ PRICE ALERT: Warriors Position

Dropped $0.93 → $0.89 in 2 minutes (-4.3%)
Now 1% from stop-loss @ $0.87

Current Status:
├─ P/L: -$14 (-4%)
├─ Liquidity: $28k → $18k (decaying ⚠️)
└─ Settlement: 14 hours

Options:
/exit_1 (exit now at ~$0.89)
/hold (wait for recovery or stop)
/details_1 (view full position)
```

**3. News Alert**:
```
📰 NEWS ALERT: Warriors Position

Headline: "NBA investigating game score irregularity"
Source: ESPN
Sentiment: Negative (-0.7)
Time: 2 minutes ago

Your Position:
Entry: $0.93 | Now: $0.91 | P/L: -$7
Stop: $0.87 | Settles: 12 hours

Options:
/emergency_exit_1 (market order, exit now)
/read_more_1 (full article)
/hold (monitor closely)
```

**4. Stop-Loss Executed**:
```
🛑 STOP-LOSS EXECUTED

Position: Fed Rate Decision
Entry: $0.94 @ 8:00 AM
Exit: $0.83 @ 2:47 PM
Hold time: 6.7 hours

Result:
├─ Loss: -$38 (-11.7%)
├─ Original stop: $0.85 (10%)
├─ Actual fill: $0.83 (slippage)
└─ Cause: Unexpected Fed statement reversal

Portfolio Impact:
├─ Today's P/L: -$38
├─ Week's P/L: +$142
└─ Month's P/L: +$687

This is why we use stops. Loss contained.
```

**5. Take-Profit Executed**:
```
💰 TAKE-PROFIT HIT

Position: Warriors win
Entry: $0.93 @ 8:00 AM
Partial Exit: $0.97 @ 6:23 PM (TP1)
Hold time: 10.4 hours

Result:
├─ Sold: 115 tokens (33% of position)
├─ Profit: +$46 (4.3%)
├─ Remaining: 235 tokens riding to settlement

Portfolio Update:
├─ Freed capital: $111 (available for new trades)
├─ Today's P/L: +$46
└─ Active positions: 4

Good trade! 🎉
```

**6. Position Dashboard** (on /positions command):
```
📊 ACTIVE POSITIONS (4)

Total Deployed: $1,340 (26.8% of $5,000)

1. Warriors | Entry $0.93 → Now $0.97 ✅
   P/L: +$46 (4.8%) | 33% already exited
   Stop: $0.87 | Settles: 2 hours
   Risk: 🟢 Healthy
   /exit_1 | /details_1

2. GDP Report | Entry $0.92 → Now $0.92 ➡️
   P/L: $0 (0%) | No change
   Stop: $0.78 | Settles: 18 hours
   Risk: 🟢 Healthy
   /exit_2 | /details_2

3. Election Result | Entry $0.95 → Now $0.91 ⚠️
   P/L: -$18 (-4.2%)
   Stop: $0.81 | Settles: 6 hours (manipulation window!)
   Risk: 🟡 Near stop, liquidity decaying
   /exit_3 | /tighten_stop_3

4. Tech Earnings | Entry $0.94 → Now $0.96 ✅
   P/L: +$8 (2.1%)
   Stop: $0.85 | Settles: 1 day
   Risk: 🟢 Healthy
   /exit_4 | /details_4

───────────────────────────────
Week Summary:
├─ Trades: 12 (9 wins, 3 losses)
├─ Win rate: 75%
├─ Avg win: +$52 (5.8%)
├─ Avg loss: -$41 (4.6%)
└─ Net: +$327 (6.5% weekly ROI)

/weekly_report for full analysis



@bot.command("approve_1")
def handle_approve(message):
    opportunity_id = extract_id(message)  # "1"
    opportunity = get_opportunity(opportunity_id)
    
    # Execute trade
    position = execute_trade(opportunity)
    
    # Confirm to user
    send_message(
        f"✅ Trade executed\n"
        f"Market: {opportunity.question}\n"
        f"Entry: ${position.entry_price}\n"
        f"Size: {position.tokens} tokens (${position.size_usd})\n"
        f"Stop: ${position.stop_loss_price}\n"
        f"Max loss: ${position.max_loss}\n\n"
        f"Monitoring started. You'll receive alerts."
    )

@bot.command("positions")
def handle_positions(message):
    positions = get_active_positions()
    formatted = format_positions_dashboard(positions)
    send_message(formatted)

@bot.command("exit_1")
def handle_exit(message):
    position_id = extract_id(message)
    position = get_position(position_id)
    
    # Confirm before executing
    send_message(
        f"⚠️ Confirm exit?\n\n"
        f"Market: {position.market_question}\n"
        f"Current P/L: ${position.current_pnl} ({position.pnl_pct}%)\n"
        f"Estimated exit: ${position.current_price}\n\n"
        f"/confirm_exit_1 | /cancel"
    )

@bot.command("confirm_exit_1")
def handle_confirm_exit(message):
    position_id = extract_id(message)
    
    # Execute market sell
    result = exit_position(position_id)
    
    send_message(
        f"✅ Position closed\n"
        f"Exit price: ${result.exit_price}\n"
        f"Final P/L: ${result.pnl} ({result.pnl_pct}%)\n"
        f"Freed capital: ${result.freed_capital}"
    )