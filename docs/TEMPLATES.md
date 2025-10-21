# Message Templates & Code Examples

*Ready-to-use templates for Telegram messages, AI prompts, and code patterns*

---

## Telegram Message Templates

### 1. Morning Report Template

```python
def format_morning_report(opportunities, portfolio_status):
    """
    Daily opportunity summary sent at 8 AM.
    """
    msg = f"🎯 Top {len(opportunities)} Tail-End Opportunities ({datetime.now().strftime('%b %d, %I:%M %p')})\n\n"

    for i, opp in enumerate(opportunities, 1):
        # Risk indicator
        risk_emoji = "✅" if opp['risk_level'] == 'LOW' else "⚠️"

        msg += f"{i}. {risk_emoji} {opp['question']}\n"
        msg += f"   Price: ${opp['yes_price']} | True Profit: {opp['true_profit_pct']:.1f}%\n"
        msg += f"   Stop: {opp['stop_loss_pct']:.0f}% adaptive | Max Loss: ${opp['max_loss']:.0f}\n"
        msg += f"   Risk: {risk_emoji} {opp['risk_level']} (finality: {opp['finality_score']}/10, clarity: {opp['clarity_score']}/10)\n"
        msg += f"   AI: {opp['ai_certainty']:.0f}% certain | Settles: {opp['hours_to_settlement']:.0f} hours\n"
        msg += f"   Reasoning: \"{opp['ai_reasoning'][:60]}...\"\n"
        msg += f"   /approve_{i} ${opp['recommended_size']} | /skip_{i} | /details_{i}\n\n"

    # Portfolio status
    msg += "📊 Portfolio Status:\n"
    msg += f"   Active: {portfolio_status['active_positions']} positions | "
    msg += f"Deployed: ${portfolio_status['deployed']:.0f} ({portfolio_status['deployed_pct']:.1f}%)\n"
    msg += f"   Available: ${portfolio_status['available']:.0f} | Reserve: ${portfolio_status['reserve']:.0f}\n"

    # Category breakdown
    categories = portfolio_status.get('category_breakdown', {})
    if categories:
        cat_str = ", ".join([f"{cat} {pct:.0f}%" for cat, pct in categories.items()])
        msg += f"   Category: {cat_str} ✓\n"

    return msg
```

**Example Output**:
```
🎯 Top 5 Tail-End Opportunities (Nov 15, 08:00 AM)

1. ✅ Warriors beat Lakers
   Price: $0.93 | True Profit: 4.8%
   Stop: 15% adaptive | Max Loss: $52
   Risk: ✅ LOW (finality: 10/10, clarity: 10/10)
   AI: 98% certain | Settles: 18 hours
   Reasoning: "Game concluded, official score recorded..."
   /approve_1 $350 | /skip_1 | /details_1

2. ⚠️ Fed raises rates
   Price: $0.94 | True Profit: 3.2%
   Stop: 12% adaptive | Max Loss: $38
   Risk: ⚠️ MEDIUM (settlement in 16h)
   AI: 91% certain | Settles: 16 hours
   Reasoning: "Announcement made, no reversal path..."
   /approve_2 $280 | /skip_2 | /details_2

📊 Portfolio Status:
   Active: 5 positions | Deployed: $1,680 (33.6%)
   Available: $3,320 | Reserve: $1,000
   Category: Sports 40%, Econ 30%, Politics 30% ✓
```

---

### 2. Price Drop Alert Template

```python
def format_price_alert(position, current_price, previous_price, time_window="2 minutes"):
    """
    Alert when position drops significantly.
    """
    drop_pct = ((previous_price - current_price) / previous_price) * 100
    distance_to_stop = ((current_price - position['stop_loss_price']) / current_price) * 100

    msg = f"⚠️ PRICE ALERT: {position['market_question']}\n\n"
    msg += f"Dropped ${previous_price:.2f} → ${current_price:.2f} in {time_window} (-{drop_pct:.1f}%)\n"
    msg += f"Now {distance_to_stop:.0f}% from stop-loss @ ${position['stop_loss_price']:.2f}\n\n"

    msg += "Current Status:\n"
    msg += f"├─ P/L: ${position['current_pnl']:.0f} ({position['current_pnl_pct']:.1f}%)\n"
    msg += f"├─ Liquidity: ${position['liquidity_at_entry']/1000:.0f}k → ${position['current_liquidity']/1000:.0f}k"

    if position['liquidity_decaying']:
        msg += " (decaying ⚠️)\n"
    else:
        msg += "\n"

    msg += f"└─ Settlement: {position['hours_to_settlement']:.0f} hours\n\n"

    msg += "Options:\n"
    msg += f"/exit_{position['position_id']} (exit now at ~${current_price:.2f})\n"
    msg += f"/hold (wait for recovery or stop)\n"
    msg += f"/details_{position['position_id']} (view full position)"

    return msg
```

**Example Output**:
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

---

### 3. News Alert Template

```python
def format_news_alert(position, news_item):
    """
    Alert when negative news detected for open position.
    """
    msg = f"📰 NEWS ALERT: {position['market_question']}\n\n"
    msg += f"Headline: \"{news_item['headline']}\"\n"
    msg += f"Source: {news_item['source']}\n"
    msg += f"Sentiment: {'Negative' if news_item['sentiment'] < -0.3 else 'Neutral'} ({news_item['sentiment']:.1f})\n"
    msg += f"Time: {news_item['minutes_ago']} minutes ago\n\n"

    msg += "Your Position:\n"
    msg += f"Entry: ${position['entry_price']:.2f} | Now: ${position['current_price']:.2f} | "
    msg += f"P/L: ${position['current_pnl']:.0f}\n"
    msg += f"Stop: ${position['stop_loss_price']:.2f} | Settles: {position['hours_to_settlement']:.0f} hours\n\n"

    msg += "Options:\n"
    msg += f"/emergency_exit_{position['position_id']} (market order, exit now)\n"
    msg += f"/read_more_{position['position_id']} (full article)\n"
    msg += f"/hold (monitor closely)"

    return msg
```

**Example Output**:
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

---

### 4. Stop-Loss Executed Template

```python
def format_stop_loss_notification(position, exit_result):
    """
    Notification when stop-loss is triggered.
    """
    hold_hours = (exit_result['exit_time'] - position['entry_time']).total_seconds() / 3600

    msg = f"🛑 STOP-LOSS EXECUTED\n\n"
    msg += f"Position: {position['market_question']}\n"
    msg += f"Entry: ${position['entry_price']:.2f} @ {position['entry_time'].strftime('%I:%M %p')}\n"
    msg += f"Exit: ${exit_result['exit_price']:.2f} @ {exit_result['exit_time'].strftime('%I:%M %p')}\n"
    msg += f"Hold time: {hold_hours:.1f} hours\n\n"

    msg += "Result:\n"
    msg += f"├─ Loss: ${exit_result['pnl_usd']:.0f} ({exit_result['pnl_pct']:.1f}%)\n"
    msg += f"├─ Original stop: ${position['stop_loss_price']:.2f} ({position['stop_loss_pct']:.0f}%)\n"
    msg += f"├─ Actual fill: ${exit_result['exit_price']:.2f} "

    if exit_result.get('slippage'):
        msg += f"(slippage)\n"
    else:
        msg += "\n"

    msg += f"└─ Cause: {exit_result.get('cause', 'Price dropped below stop level')}\n\n"

    # Portfolio impact
    portfolio = exit_result.get('portfolio_impact', {})
    msg += "Portfolio Impact:\n"
    msg += f"├─ Today's P/L: ${portfolio.get('today_pnl', 0):.0f}\n"
    msg += f"├─ Week's P/L: ${portfolio.get('week_pnl', 0):.0f}\n"
    msg += f"└─ Month's P/L: ${portfolio.get('month_pnl', 0):.0f}\n\n"

    msg += "This is why we use stops. Loss contained."

    return msg
```

**Example Output**:
```
🛑 STOP-LOSS EXECUTED

Position: Fed Rate Decision
Entry: $0.94 @ 08:00 AM
Exit: $0.83 @ 02:47 PM
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

---

### 5. Take-Profit Executed Template

```python
def format_take_profit_notification(position, tp_result):
    """
    Notification when take-profit target is hit.
    """
    hold_hours = (tp_result['exit_time'] - position['entry_time']).total_seconds() / 3600

    msg = f"💰 TAKE-PROFIT HIT\n\n"
    msg += f"Position: {position['market_question']}\n"
    msg += f"Entry: ${position['entry_price']:.2f} @ {position['entry_time'].strftime('%I:%M %p')}\n"
    msg += f"Partial Exit: ${tp_result['exit_price']:.2f} @ {tp_result['exit_time'].strftime('%I:%M %p')} (TP{tp_result['tp_level']})\n"
    msg += f"Hold time: {hold_hours:.1f} hours\n\n"

    msg += "Result:\n"
    msg += f"├─ Sold: {tp_result['tokens_sold']} tokens ({tp_result['pct_of_position']:.0f}% of position)\n"
    msg += f"├─ Profit: +${tp_result['profit_usd']:.0f} ({tp_result['profit_pct']:.1f}%)\n"
    msg += f"└─ Remaining: {tp_result['tokens_remaining']} tokens riding to settlement\n\n"

    msg += "Portfolio Update:\n"
    msg += f"├─ Freed capital: ${tp_result['freed_capital']:.0f} (available for new trades)\n"
    msg += f"├─ Today's P/L: +${tp_result.get('today_pnl', 0):.0f}\n"
    msg += f"└─ Active positions: {tp_result.get('active_positions', 0)}\n\n"

    msg += "Good trade! 🎉"

    return msg
```

**Example Output**:
```
💰 TAKE-PROFIT HIT

Position: Warriors win
Entry: $0.93 @ 08:00 AM
Partial Exit: $0.97 @ 06:23 PM (TP1)
Hold time: 10.4 hours

Result:
├─ Sold: 115 tokens (33% of position)
├─ Profit: +$46 (4.3%)
└─ Remaining: 235 tokens riding to settlement

Portfolio Update:
├─ Freed capital: $111 (available for new trades)
├─ Today's P/L: +$46
└─ Active positions: 4

Good trade! 🎉
```

---

### 6. Position Dashboard Template

```python
def format_positions_dashboard(positions, summary):
    """
    Overview of all active positions (/positions command).
    """
    msg = f"📊 ACTIVE POSITIONS ({len(positions)})\n\n"
    msg += f"Total Deployed: ${summary['total_deployed']:.0f} ({summary['deployed_pct']:.1f}% of ${summary['bankroll']:.0f})\n\n"

    for i, pos in enumerate(positions, 1):
        # Status emoji
        if pos['current_pnl_pct'] > 2:
            status = "✅"
        elif pos['current_pnl_pct'] < -2:
            status = "⚠️"
        else:
            status = "➡️"

        msg += f"{i}. {pos['market_question']} | Entry ${pos['entry_price']:.2f} → Now ${pos['current_price']:.2f} {status}\n"
        msg += f"   P/L: ${pos['current_pnl']:.0f} ({pos['current_pnl_pct']:.1f}%)"

        if pos.get('partial_exit'):
            msg += f" | {pos['partial_exit_pct']:.0f}% already exited\n"
        else:
            msg += "\n"

        msg += f"   Stop: ${pos['stop_loss_price']:.2f} | Settles: {pos['hours_to_settlement']:.0f} hours"

        if pos['hours_to_settlement'] <= 6:
            msg += " (manipulation window!)\n"
        else:
            msg += "\n"

        # Risk indicator
        risk_level = pos.get('risk_level', 'Healthy')
        risk_emoji = "🟢" if risk_level == "Healthy" else "🟡" if risk_level == "Warning" else "🔴"
        msg += f"   Risk: {risk_emoji} {risk_level}\n"
        msg += f"   /exit_{i} | /details_{i}\n\n"

    # Weekly summary
    msg += "───────────────────────────────\n"
    msg += "Week Summary:\n"
    msg += f"├─ Trades: {summary['total_trades']} ({summary['wins']} wins, {summary['losses']} losses)\n"
    msg += f"├─ Win rate: {summary['win_rate']:.0f}%\n"
    msg += f"├─ Avg win: +${summary['avg_win']:.0f} ({summary['avg_win_pct']:.1f}%)\n"
    msg += f"├─ Avg loss: ${summary['avg_loss']:.0f} ({summary['avg_loss_pct']:.1f}%)\n"
    msg += f"└─ Net: ${summary['net_pnl']:.0f} ({summary['weekly_roi']:.1f}% weekly ROI)\n\n"

    msg += "/weekly_report for full analysis"

    return msg
```

---

## Claude AI Prompt Templates

### Opportunity Evaluation Prompt

```python
def build_evaluation_prompt(market, news_context, comments):
    """
    Prompt for Claude to evaluate trading opportunity.
    """
    prompt = f"""You are a risk analyst for prediction markets. Evaluate this trading opportunity.

Market: {market['question']}
Current Price: ${market['yes_price']:.2f} ({market['yes_price']*100:.0f}% implied probability)
Category: {market['category']}
Settlement: {market['hours_to_settlement']:.0f} hours away ({market['settlement_date'].strftime('%b %d, %I:%M %p')})

Event Status:
{news_context}

Polymarket Comments (sample):
{format_comments(comments[:3])}

Resolution Criteria:
{market['resolution_criteria']}

Risk Scores (0-10):
- Resolution Clarity: {market['resolution_clarity_score']}/10
- Event Finality: {market['event_finality_score']}/10
- Liquidity Health: {market['liquidity_ratio']:.1f}x position size

Tasks:
1. Is the outcome truly ≥92% certain? Consider ALL possible reversal scenarios.
2. Is the resolution criteria objective and verifiable?
3. Has the physical event concluded (not just "called" by media)?
4. List specific risks that could cause outcome reversal.
5. Recommend: ENTER / SKIP / HUMAN_REVIEW

Output as JSON:
{{
  "certainty_score": 0.0-1.0,
  "reasoning": "2-3 sentence explanation",
  "reversal_scenarios": ["scenario 1", "scenario 2", ...],
  "recommendation": "ENTER|SKIP|HUMAN_REVIEW",
  "confidence": "low|medium|high"
}}

Be conservative. When in doubt, recommend SKIP or HUMAN_REVIEW."""

    return prompt


def format_comments(comments):
    """Format Polymarket comments for context."""
    if not comments:
        return "No comments available."

    formatted = []
    for c in comments:
        formatted.append(f"- \"{c['text']}\" ({c['upvotes']} upvotes)")

    return "\n".join(formatted)
```

---

## Code Examples

### Example: Market Scanning Loop

```python
import time
from datetime import datetime
from collectors.polymarket_api import fetch_markets
from detectors.filters import run_filter_pipeline
from detectors.scorer import score_opportunities
from ai.decision_agent import evaluate_opportunities
from interface.telegram_bot import send_morning_report

def scan_markets_loop():
    """
    Main scanning loop - runs every 5 minutes.
    """
    logger.info("Starting market scanner...")

    while True:
        try:
            # Fetch all markets
            logger.info("Fetching markets from Polymarket...")
            markets = fetch_markets()
            logger.info(f"Found {len(markets)} total markets")

            # Run 8-stage filter pipeline
            filtered = run_filter_pipeline(markets)
            logger.info(f"After filtering: {len(filtered)} candidates")

            if not filtered:
                logger.info("No opportunities found this cycle")
                time.sleep(300)  # Wait 5 minutes
                continue

            # Score opportunities
            scored = score_opportunities(filtered)
            top_10 = sorted(scored, key=lambda x: x['score'], reverse=True)[:10]

            # AI evaluation
            evaluated = evaluate_opportunities(top_10)
            approved = [opp for opp in evaluated if opp['recommendation'] == 'ENTER']

            logger.info(f"AI approved {len(approved)} opportunities")

            # Send morning report (only at 8 AM)
            if datetime.now().hour == 8:
                send_morning_report(approved[:5])

            # Wait 5 minutes before next scan
            time.sleep(300)

        except Exception as e:
            logger.error(f"Error in scanning loop: {e}")
            time.sleep(60)  # Wait 1 minute on error
```

---

### Example: Executing a Trade

```python
from execution.sizer import calculate_position_size
from execution.stop_calculator import calculate_stop_loss
from execution.trader import place_order, verify_fill
from database.db_manager import save_position
from interface.telegram_bot import send_message

def execute_trade(opportunity):
    """
    Execute approved trade with all safety checks.
    """
    try:
        # Pre-flight checks
        if not pre_flight_checks(opportunity):
            logger.warning(f"Pre-flight checks failed for {opportunity['question']}")
            return None

        # Calculate position size
        size_usd = calculate_position_size(
            market=opportunity,
            bankroll=BANKROLL_USD,
            ai_certainty=opportunity['ai_certainty']
        )

        # Calculate stop-loss
        entry_price = opportunity['yes_price']
        stop_price, stop_pct = calculate_stop_loss(opportunity, entry_price)

        # Place entry order
        logger.info(f"Placing order: {opportunity['question']} @ ${entry_price}")
        order = place_order(
            market_id=opportunity['market_id'],
            side="BUY",
            price=entry_price,
            size=size_usd
        )

        # Wait for fill (max 60 seconds)
        filled = verify_fill(order['order_id'], timeout=60)

        if not filled:
            logger.error(f"Order not filled within 60 seconds")
            return None

        # Calculate tokens purchased
        tokens = int(size_usd / entry_price)

        # Place stop-loss order
        stop_order = place_order(
            market_id=opportunity['market_id'],
            side="SELL",
            price=stop_price,
            size=tokens,
            order_type="STOP_LOSS"
        )

        # Save position to database
        position = {
            'market_id': opportunity['market_id'],
            'entry_price': entry_price,
            'tokens': tokens,
            'position_size_usd': size_usd,
            'stop_loss_price': stop_price,
            'stop_loss_pct': stop_pct,
            'status': 'active',
            'liquidity_at_entry': opportunity['liquidity_ratio'],
            'volatility_at_entry': opportunity.get('volatility', 0.02)
        }

        position_id = save_position(position)

        # Notify user
        msg = f"""✅ Trade executed

Market: {opportunity['question']}
Entry: ${entry_price:.2f}
Size: {tokens} tokens (${size_usd:.0f})
Stop: ${stop_price:.2f} ({stop_pct:.0%})
Max loss: ${size_usd * stop_pct:.0f}

Monitoring started. You'll receive alerts."""

        send_message(msg)

        logger.info(f"Position {position_id} opened successfully")
        return position_id

    except Exception as e:
        logger.error(f"Error executing trade: {e}")
        send_message(f"⚠️ Trade execution failed: {str(e)}")
        return None


def pre_flight_checks(opportunity):
    """
    Final safety checks before order placement.
    """
    # Check 1: Price still in range
    current_price = get_current_price(opportunity['market_id'])
    if not (PRICE_MIN <= current_price <= PRICE_MAX):
        logger.warning(f"Price moved out of range: ${current_price}")
        return False

    # Check 2: Liquidity still sufficient
    current_liquidity = get_current_liquidity(opportunity['market_id'])
    if current_liquidity < MIN_BID_DEPTH:
        logger.warning(f"Liquidity dropped: ${current_liquidity}")
        return False

    # Check 3: No breaking news in last 5 min
    recent_news = fetch_news_since(minutes=5)
    if any(is_relevant(news, opportunity) for news in recent_news):
        logger.warning("Breaking news detected, aborting")
        return False

    # Check 4: Portfolio limits OK
    if not check_portfolio_limits():
        logger.warning("Portfolio limits reached")
        return False

    return True
```

---

### Example: Price Monitoring Loop

```python
def monitor_positions():
    """
    Check all open positions every 60 seconds.
    """
    logger.info("Starting position monitor...")

    while True:
        try:
            positions = get_active_positions()

            for pos in positions:
                current_price = get_current_price(pos['market_id'])
                previous_price = get_price_1min_ago(pos['market_id'])

                # Check 1: Sudden drop
                if previous_price > 0:
                    drop_pct = (previous_price - current_price) / previous_price
                    if drop_pct > SUDDEN_DROP_THRESHOLD_PCT:
                        alert_sudden_drop(pos, current_price, previous_price)

                # Check 2: Stop-loss trigger
                if current_price <= pos['stop_loss_price']:
                    execute_stop_loss(pos, current_price)

                # Check 3: Take-profit trigger
                if pos.get('take_profit_1_price') and current_price >= pos['take_profit_1_price']:
                    if not pos.get('tp1_executed'):
                        execute_take_profit(pos, current_price, level=1)

                # Check 4: Approaching stop
                distance_to_stop = (current_price - pos['stop_loss_price']) / current_price
                if distance_to_stop < 0.02:  # Within 2%
                    alert_approaching_stop(pos, current_price)

            time.sleep(60)  # Check every 60 seconds

        except Exception as e:
            logger.error(f"Error in position monitor: {e}")
            time.sleep(60)
```

---

## Bot Command Handlers

### Telegram Command Examples

```python
from telebot import TeleBot

bot = TeleBot(TELEGRAM_BOT_TOKEN)

@bot.message_handler(commands=['approve'])
def handle_approve(message):
    """
    Handle /approve_1, /approve_2, etc.
    """
    try:
        # Extract opportunity ID from command
        # Example: "/approve_1 $350" → id=1, size=350
        parts = message.text.split()
        opportunity_id = int(parts[0].split('_')[1])

        # Get opportunity from cache
        opportunity = get_cached_opportunity(opportunity_id)

        if not opportunity:
            bot.reply_to(message, "⚠️ Opportunity expired or not found")
            return

        # Execute trade
        position_id = execute_trade(opportunity)

        if position_id:
            bot.reply_to(message, f"✅ Trade #{position_id} executed. Monitoring started.")
        else:
            bot.reply_to(message, "❌ Trade execution failed. Check logs.")

    except Exception as e:
        logger.error(f"Error in /approve: {e}")
        bot.reply_to(message, f"⚠️ Error: {str(e)}")


@bot.message_handler(commands=['positions'])
def handle_positions(message):
    """
    Show all active positions.
    """
    try:
        positions = get_active_positions()
        summary = calculate_portfolio_summary()

        dashboard = format_positions_dashboard(positions, summary)
        bot.send_message(TELEGRAM_CHAT_ID, dashboard, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error in /positions: {e}")
        bot.reply_to(message, f"⚠️ Error: {str(e)}")


@bot.message_handler(commands=['exit'])
def handle_exit(message):
    """
    Handle /exit_1, /exit_2, etc.
    """
    try:
        # Extract position ID
        position_id = int(message.text.split('_')[1])
        position = get_position(position_id)

        if not position:
            bot.reply_to(message, "⚠️ Position not found")
            return

        # Ask for confirmation
        current_price = get_current_price(position['market_id'])
        pnl = calculate_current_pnl(position, current_price)

        confirmation_msg = f"""⚠️ Confirm exit?

Market: {position['market_question']}
Current P/L: ${pnl['pnl_usd']:.0f} ({pnl['pnl_pct']:.1f}%)
Estimated exit: ${current_price:.2f}

/confirm_exit_{position_id} | /cancel"""

        bot.send_message(TELEGRAM_CHAT_ID, confirmation_msg)

    except Exception as e:
        logger.error(f"Error in /exit: {e}")
        bot.reply_to(message, f"⚠️ Error: {str(e)}")


@bot.message_handler(commands=['confirm_exit'])
def handle_confirm_exit(message):
    """
    Execute confirmed exit.
    """
    try:
        position_id = int(message.text.split('_')[2])

        result = exit_position(position_id)

        if result:
            msg = f"""✅ Position closed

Exit price: ${result['exit_price']:.2f}
Final P/L: ${result['pnl_usd']:.0f} ({result['pnl_pct']:.1f}%)
Freed capital: ${result['freed_capital']:.0f}"""
            bot.send_message(TELEGRAM_CHAT_ID, msg)
        else:
            bot.send_message(TELEGRAM_CHAT_ID, "❌ Exit failed. Check logs.")

    except Exception as e:
        logger.error(f"Error in /confirm_exit: {e}")
        bot.reply_to(message, f"⚠️ Error: {str(e)}")


# Start bot
logger.info("Starting Telegram bot...")
bot.polling(none_stop=True)
```
