# TODO - Polymarket Tail-End Arbitrage Bot

## Component 1: Foundation (Week 1)

### Phase 1.1: Project Setup
- [ ] 1.1.1: Create directory structure (all folders)
- [ ] 1.1.2: Create requirements.txt with dependencies
- [ ] 1.1.3: Create .env.example template
- [ ] 1.1.4: Create config.py (load env vars, define constants)
- [ ] 1.1.5: Setup logging in utils/logger.py

### Phase 1.2: Database
- [ ] 1.2.1: Write schema.sql (6 tables)
- [ ] 1.2.2: Create db_manager.py (connection, init)
- [ ] 1.2.3: Write markets CRUD functions
- [ ] 1.2.4: Write positions CRUD functions
- [ ] 1.2.5: Test database operations

---

## Component 2: Data Collection (Week 1)

### Phase 2.1: Polymarket API
- [ ] 2.1.1: Create polymarket_api.py wrapper
- [ ] 2.1.2: Test connection to Polymarket
- [ ] 2.1.3: Write fetch_markets() function
- [ ] 2.1.4: Write fetch_order_book() function
- [ ] 2.1.5: Write collect_and_store() function

### Phase 2.2: News Scraping
- [ ] 2.2.1: Create news_scraper.py
- [ ] 2.2.2: Add RSS feed sources (Reuters, ESPN, Fed)
- [ ] 2.2.3: Write keyword matching function
- [ ] 2.2.4: Store news in database

---

## Component 3: Opportunity Detection (Week 2)

### Phase 3.1: Filter Pipeline
- [ ] 3.1.1: Create filters.py
- [ ] 3.1.2: Write price_range filter (Stage 1)
- [ ] 3.1.3: Write liquidity filters (Stage 2)
- [ ] 3.1.4: Write settlement_window filter (Stage 3)
- [ ] 3.1.5: Write resolution_clarity filter (Stage 6)
- [ ] 3.1.6: Write event_finality filter (Stage 7)
- [ ] 3.1.7: Write portfolio_limits filter (Stage 8)

### Phase 3.2: Scoring System
- [ ] 3.2.1: Create scorer.py
- [ ] 3.2.2: Write calculate_true_profit() (after fees/slippage)
- [ ] 3.2.3: Write calculate_liquidity_score()
- [ ] 3.2.4: Write calculate_certainty_factor()
- [ ] 3.2.5: Write calculate_final_score()

### Phase 3.3: Scanner
- [ ] 3.3.1: Create scanner.py
- [ ] 3.3.2: Write scan_opportunities() (runs full pipeline)
- [ ] 3.3.3: Test scanner with real data

---

## Component 4: AI Decision Engine (Week 2)

### Phase 4.1: Claude Integration
- [ ] 4.1.1: Create decision_agent.py
- [ ] 4.1.2: Write build_prompt() function
- [ ] 4.1.3: Write call_claude_api() function
- [ ] 4.1.4: Write parse_response() function
- [ ] 4.1.5: Test with 3 sample opportunities

---

## Component 5: Telegram Bot (Week 2)

### Phase 5.1: Basic Bot
- [ ] 5.1.1: Create telegram_bot.py
- [ ] 5.1.2: Setup bot with BotFather, get token
- [ ] 5.1.3: Write send_message() function
- [ ] 5.1.4: Test bot sends message

### Phase 5.2: Commands
- [ ] 5.2.1: Write handle_approve() command
- [ ] 5.2.2: Write handle_skip() command
- [ ] 5.2.3: Write handle_positions() command
- [ ] 5.2.4: Write handle_exit() command

### Phase 5.3: Reports
- [ ] 5.3.1: Write format_opportunity() function
- [ ] 5.3.2: Write send_morning_report() function
- [ ] 5.3.3: Write send_alert() function

---

## Component 6: Execution (Week 3)

### Phase 6.1: Position Sizing
- [ ] 6.1.1: Create sizer.py
- [ ] 6.1.2: Write calculate_kelly() function
- [ ] 6.1.3: Write apply_uncertainty_adjustment()
- [ ] 6.1.4: Write apply_portfolio_constraints()

### Phase 6.2: Stop-Loss Calculator
- [ ] 6.2.1: Create stop_calculator.py
- [ ] 6.2.2: Write calculate_volatility() from price history
- [ ] 6.2.3: Write adjust_for_volatility()
- [ ] 6.2.4: Write adjust_for_liquidity()
- [ ] 6.2.5: Write adjust_for_time() (manipulation window)

### Phase 6.3: Order Execution
- [ ] 6.3.1: Create trader.py
- [ ] 6.3.2: Write place_entry_order()
- [ ] 6.3.3: Write place_stop_loss()
- [ ] 6.3.4: Write place_take_profit()
- [ ] 6.3.5: Test with SMALL real trade ($50-100)

---

## Component 7: Monitoring (Week 3)

### Phase 7.1: Price Monitor
- [ ] 7.1.1: Create price_monitor.py
- [ ] 7.1.2: Write check_positions() loop
- [ ] 7.1.3: Write detect_sudden_drop()
- [ ] 7.1.4: Write check_stop_loss_trigger()
- [ ] 7.1.5: Write check_take_profit_trigger()

### Phase 7.2: Liquidity Monitor
- [ ] 7.2.1: Create liquidity_monitor.py
- [ ] 7.2.2: Write check_liquidity_health()
- [ ] 7.2.3: Write calculate_decay_rate()
- [ ] 7.2.4: Send alerts if decay >50%

### Phase 7.3: News Monitor
- [ ] 7.3.1: Create news_monitor.py
- [ ] 7.3.2: Write monitor_position_news()
- [ ] 7.3.3: Write extract_keywords() from position
- [ ] 7.3.4: Write match_news_to_keywords()

---

## Component 8: Orchestration (Week 4)

### Phase 8.1: Main Loop
- [ ] 8.1.1: Create main.py
- [ ] 8.1.2: Setup APScheduler
- [ ] 8.1.3: Schedule collect_markets (every 5 min)
- [ ] 8.1.4: Schedule scan_opportunities (every 5 min)
- [ ] 8.1.5: Schedule monitor_positions (every 60 sec)
- [ ] 8.1.6: Schedule morning_report (daily 8 AM)
- [ ] 8.1.7: Schedule weekly_review (Sunday 8 AM)

### Phase 8.2: Integration Testing
- [ ] 8.2.1: Test full pipeline end-to-end
- [ ] 8.2.2: Test with 3-5 real opportunities
- [ ] 8.2.3: Verify all alerts working
- [ ] 8.2.4: Test stop-loss execution
- [ ] 8.2.5: Test take-profit execution

---

## Component 9: Production Ready (Week 4)

### Phase 9.1: Error Handling
- [ ] 9.1.1: Add try/except to all API calls
- [ ] 9.1.2: Add retry logic with exponential backoff
- [ ] 9.1.3: Add error alerts to Telegram

### Phase 9.2: Deployment
- [ ] 9.2.1: Test locally for 48 hours
- [ ] 9.2.2: Deploy to VPS (DigitalOcean/Railway)
- [ ] 9.2.3: Setup systemd service
- [ ] 9.2.4: Setup hourly database backups
- [ ] 9.2.5: Monitor for 1 week

### Phase 9.3: Documentation
- [ ] 9.3.1: Write README.md (setup instructions)
- [ ] 9.3.2: Document all configuration options
- [ ] 9.3.3: Create troubleshooting guide