# Operational Runbook

*Day-to-day operations, troubleshooting, and maintenance procedures*

---

## Daily Operations

### Morning Routine (8:00 AM - 8:15 AM)

**1. Check Telegram Morning Report**
```
Expected: Top 3-5 opportunities listed
Actions:
- Review each opportunity
- Check AI reasoning
- Verify settlement times
- Approve or skip each one

Commands:
/approve_1 $amount  → Execute trade
/skip_1             → Reject opportunity
/details_1          → See full analysis
```

**2. Review Active Positions**
```
Command: /positions

Check:
- Current P/L on each position
- Hours to settlement
- Risk levels (🟢/🟡/🔴)
- Any alerts overnight

Action: None required unless risk is 🔴
```

**3. Check Bot Health**
```bash
# SSH into server (if remote)
ssh user@server

# Check bot process
ps aux | grep main.py

# Check recent logs
tail -n 50 logs/bot.log | grep ERROR

# Check database size
ls -lh data/polymarket.db
```

**Expected**: No errors, bot running, database <100MB

---

### Throughout the Day (As Alerts Arrive)

**Alert Type 1: Price Drop**
```
⚠️ PRICE ALERT: [Position] dropped X% in Y minutes

Decision Matrix:
- Drop <5% + >12h to settlement → /hold (likely noise)
- Drop 5-8% + <6h to settlement → /exit_X (manipulation risk)
- Drop >8% → /exit_X immediately (protect capital)
```

**Alert Type 2: Negative News**
```
📰 NEWS ALERT: Negative news detected

Actions:
1. /read_more_X to see full article
2. Assess: Is this material to outcome?
   - Yes → /emergency_exit_X
   - No → /hold
3. Check other news sources manually if uncertain
```

**Alert Type 3: Liquidity Decay**
```
⚠️ Liquidity decaying: [Position] down X%

Decision Matrix:
- Decay 50-70% + >6h to settlement → /hold (monitor)
- Decay >70% → /exit_X (exit while still possible)
- Decay >70% + rapid (30%/hour) → /exit_X immediately
```

**Alert Type 4: Approaching Stop**
```
🚨 Within 2% of stop-loss: [Position]

Actions:
1. Check if temporary dip or trend
2. Look at order book depth
3. Usually → /hold (let stop work)
4. If obvious manipulation → /exit_X early
```

---

### Evening Check (5:00 PM - 5:10 PM)

**1. Review Day's Activity**
```
Command: /positions

Check:
- Any positions closed today?
- Today's P/L
- New positions entered
```

**2. Prepare for Overnight**
```
Verify:
- All stops in place
- No positions <2h to settlement (high risk)
- Alert notifications working

Command: Send yourself test alert
```

**3. Check Logs for Warnings**
```bash
grep WARNING logs/bot.log | tail -20
```

---

## Weekly Maintenance (Sunday, 8:00 AM)

### 1. Performance Review

**Run Weekly Report**
```
Command: /weekly_report

Analyze:
- Win rate (target: ≥70%)
- Average win vs. average loss
- Weekly ROI (target: 2-4%)
- Which categories performed best/worst
- Any patterns in losses?
```

**Questions to Ask**:
- Are we hitting target metrics?
- Any category consistently losing? → Exclude it
- Any filter letting bad trades through? → Tighten it
- Win rate <70%? → Be more selective

---

### 2. Parameter Adjustment

**Based on performance, adjust config.py:**

```python
# If win rate <70%: Be more selective
MIN_RESOLUTION_CLARITY = 9  # Was 8
MIN_EVENT_FINALITY = 9      # Was 8
MIN_TRUE_PROFIT_PCT = 0.05  # Was 0.04 (require 5% profit)

# If missing good opportunities: Be less selective
MIN_VOLUME_24H = 30000      # Was 50000
MIN_RESOLUTION_CLARITY = 7  # Was 8

# If stops hit too often: Widen stops
BASE_STOP_LOSS_PCT = 0.12   # Was 0.10
VOLATILITY_MULTIPLIER = 2.0 # Was 1.5

# If not deploying enough capital: Allow more positions
MAX_POSITIONS = 10          # Was 8
MAX_CATEGORY_EXPOSURE_PCT = 0.50  # Was 0.40
```

**After adjustments**:
```bash
# Restart bot to load new config
pkill -f main.py
nohup python main.py > /dev/null 2>&1 &
```

---

### 3. Database Maintenance

**Check Database Size**
```bash
ls -lh data/polymarket.db

# If >500MB, archive old data
sqlite3 data/polymarket.db
```

```sql
-- Archive markets older than 30 days
DELETE FROM order_books WHERE timestamp < datetime('now', '-30 days');
DELETE FROM news_events WHERE timestamp < datetime('now', '-30 days');
DELETE FROM markets WHERE last_updated < datetime('now', '-30 days');

-- Vacuum to reclaim space
VACUUM;
```

**Verify Backup**
```bash
ls -lh data/backups/ | tail -10

# Should see hourly backups
# Keep last 7 days, delete older
find data/backups/ -name "*.db" -mtime +7 -delete
```

---

### 4. Update Dependencies

**Check for updates (monthly)**
```bash
pip list --outdated

# Update if any critical updates
pip install --upgrade py-clob-client anthropic python-telegram-bot
```

**Test after updates**
```bash
python -c "from collectors.polymarket_api import fetch_markets; print(len(fetch_markets()))"

# Expected: Should print number >0
```

---

## Monthly Review (1st Sunday of Month)

### 1. Financial Analysis

**Calculate Monthly Metrics**
```sql
-- Run in sqlite3 data/polymarket.db

-- Monthly P/L
SELECT
    COUNT(*) as total_trades,
    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN pnl_usd < 0 THEN 1 ELSE 0 END) as losses,
    AVG(CASE WHEN pnl_usd > 0 THEN pnl_pct END) as avg_win_pct,
    AVG(CASE WHEN pnl_usd < 0 THEN pnl_pct END) as avg_loss_pct,
    SUM(pnl_usd) as total_pnl
FROM positions
WHERE exit_time >= datetime('now', '-30 days')
  AND status IN ('settled', 'exited', 'stopped');
```

**Compare to Targets**:
- Win rate ≥ 70%? ✓/✗
- Monthly ROI 8-15%? ✓/✗
- Max drawdown <20%? ✓/✗

---

### 2. Strategy Review

**Category Performance**
```sql
SELECT
    category,
    COUNT(*) as trades,
    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
    AVG(pnl_pct) as avg_return
FROM positions p
JOIN markets m ON p.market_id = m.market_id
WHERE p.exit_time >= datetime('now', '-30 days')
GROUP BY category
ORDER BY avg_return DESC;
```

**Actions**:
- Exclude categories with <50% win rate
- Increase exposure to best-performing categories

---

### 3. Cost Review

**API Costs**
```
Anthropic Dashboard: https://console.anthropic.com/usage

Check:
- Total API calls this month
- Total cost
- Average cost per evaluation

Expected: ~$80-150/month for 50-100 calls/day
```

**If costs too high**:
- Reduce calls by raising filter thresholds
- Cache AI evaluations for similar markets

---

## Troubleshooting Guide

### Problem: Bot Not Running

**Symptoms**: No morning report, no alerts

**Diagnosis**:
```bash
ps aux | grep main.py
# If no output → bot is down
```

**Solution**:
```bash
# Check logs for crash reason
tail -100 logs/bot.log

# Restart bot
cd /path/to/polymarket_bot
nohup python main.py > /dev/null 2>&1 &

# Verify started
ps aux | grep main.py
tail -f logs/bot.log  # Watch for startup messages
```

---

### Problem: No Opportunities in Morning Report

**Symptoms**: Morning report shows 0 opportunities for several days

**Diagnosis**:
```bash
# Check if markets are being fetched
grep "Fetched.*markets" logs/bot.log | tail -5

# Check filter results
grep "After filtering" logs/bot.log | tail -5
```

**Possible Causes**:

**1. API Down**
```bash
grep "API failed" logs/bot.log | tail -10

# Solution: Wait for Polymarket to recover
# Usually resolves within 1-2 hours
```

**2. Filters Too Strict**
```bash
# Temporarily relax filters in config.py
PRICE_MIN = 0.90  # Was 0.92
MIN_VOLUME_24H = 30000  # Was 50000

# Restart bot
```

**3. No Good Markets Today**
```
# Check Polymarket manually
https://polymarket.com

# If generally low volume day → Normal
# Wait for next cycle
```

---

### Problem: Orders Not Executing

**Symptoms**: Approve trade, but no position created

**Diagnosis**:
```bash
grep "Order not filled" logs/bot.log | tail -10
grep "Pre-flight checks failed" logs/bot.log | tail -10
```

**Possible Causes**:

**1. Price Moved Out of Range**
```
Message: "Price moved out of range"

Solution: Market moved too fast, try next opportunity
```

**2. Insufficient Liquidity**
```
Message: "Liquidity dropped"

Solution: Market liquidity evaporated, skip this trade
```

**3. Portfolio Limits Reached**
```
Message: "Portfolio limits reached"

Solution: Wait for existing position to close, or manually exit one
```

**4. API Error**
```
Message: "API error: [details]"

Solution: Check Polymarket status, may be temporary issue
Retry in 5 minutes
```

---

### Problem: Stop-Loss Not Executing

**Symptoms**: Price below stop, but position still active

**CRITICAL**: This needs immediate action

**Diagnosis**:
```bash
grep "Stop-loss.*failed" logs/bot.log | tail -10

# Check position status
sqlite3 data/polymarket.db "SELECT * FROM positions WHERE status='active' AND current_price < stop_loss_price"
```

**Solution**:
```
1. Immediate: Exit position manually
   Command: /emergency_exit_X

2. Root cause: Check logs for error
   Possible: Liquidity crash, API failure

3. Prevention: Monitor liquidity more closely
```

---

### Problem: Telegram Not Receiving Messages

**Symptoms**: No morning report, no alerts

**Diagnosis**:
```bash
grep "Telegram.*failed" logs/bot.log | tail -10
```

**Solution 1: Check bot token**
```bash
# Verify token is correct
echo $TELEGRAM_BOT_TOKEN

# Test manually
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"

# Should return bot info
```

**Solution 2: Check chat ID**
```bash
# Verify chat ID
echo $TELEGRAM_CHAT_ID

# Test send
python -c "
from telebot import TeleBot
import os
bot = TeleBot(os.getenv('TELEGRAM_BOT_TOKEN'))
bot.send_message(os.getenv('TELEGRAM_CHAT_ID'), 'Test')
"
```

**Solution 3: Check internet**
```bash
ping telegram.org
# If fails → Network issue
```

---

### Problem: Database Corruption

**Symptoms**: Errors like "database disk image is malformed"

**CRITICAL**: Stop bot immediately

**Solution**:
```bash
# 1. Stop bot
pkill -f main.py

# 2. Check integrity
sqlite3 data/polymarket.db "PRAGMA integrity_check;"

# If output is NOT "ok":

# 3. Restore from backup
cp data/polymarket.db data/polymarket.db.corrupt
cp data/backups/polymarket_backup_LATEST.db data/polymarket.db

# 4. Verify restored DB
sqlite3 data/polymarket.db "PRAGMA integrity_check;"

# 5. Restart bot
nohup python main.py > /dev/null 2>&1 &
```

---

### Problem: High False Alert Rate

**Symptoms**: Getting alerts constantly, but no real issues

**Solution**:
```python
# Adjust alert thresholds in config.py

# Reduce price alert sensitivity
SUDDEN_DROP_THRESHOLD_PCT = 0.05  # Was 0.03 (now 5% instead of 3%)

# Reduce liquidity alert sensitivity
LIQUIDITY_DECAY_WARNING_PCT = 0.60  # Was 0.50

# Restart bot
```

---

## Failure Modes & Recovery

### Mode 1: Polymarket API Outage

**Detection**: HTTP 500/503 errors in logs

**Automatic Response**:
- Retry with exponential backoff (3 attempts)
- Log error and continue
- Alert if persistent (>5 failures)

**Human Action**:
- Check Polymarket status: https://status.polymarket.com
- If down >1 hour: Monitor positions manually
- If critical position: Exit manually on Polymarket website

---

### Mode 2: Claude API Outage

**Detection**: Anthropic API errors in logs

**Automatic Response**:
- Skip AI evaluation for this cycle
- Use fallback: Manual review only

**Human Action**:
- Check Anthropic status: https://status.anthropic.com
- Review opportunities manually until API recovers
- More conservative: Only approve obvious opportunities

---

### Mode 3: Telegram Delivery Failure

**Detection**: Message send timeout errors

**Automatic Response**:
- Queue messages, retry 3x
- Log to file if all retries fail

**Human Action**:
- Check logs manually: `tail -f logs/bot.log`
- Set up Discord webhook as backup (future enhancement)

---

### Mode 4: Database Locked

**Detection**: "Database is locked" errors

**Automatic Response**:
- Retry up to 5 times with 1-second delays
- If still locked, log error and skip operation

**Human Action**:
- Usually resolves itself
- If persistent: Restart bot
- Prevention: Ensure only one bot instance running

---

### Mode 5: Insufficient Funds

**Detection**: "Insufficient balance" on order placement

**Automatic Response**:
- Cancel order attempt
- Alert user

**Human Action**:
- Check wallet balance on Polymarket
- Add funds if needed: https://polymarket.com/wallet
- Or reduce position sizes: `MAX_POSITION_SIZE = 300`

---

## Emergency Procedures

### Emergency: Unexpected 20%+ Portfolio Loss

**Actions**:
1. **Immediately**: Exit all positions
   ```
   /emergency_exit_all
   ```

2. **Stop bot**:
   ```bash
   pkill -f main.py
   ```

3. **Investigate**:
   - Check all closed positions in last 24h
   - Identify common factor (category? timeframe? event type?)
   - Review logs for anomalies

4. **Mandatory 1-week pause**:
   - Do not resume trading
   - Analyze what went wrong
   - Revise strategy before restarting

---

### Emergency: Suspected Oracle Manipulation

**Symptoms**: Outcome settled incorrectly

**Actions**:
1. **Document evidence**:
   - Screenshot market resolution
   - Save proof of actual outcome (news articles, official data)

2. **File dispute** (if within dispute period):
   - Polymarket → Market → "Dispute outcome"
   - Provide evidence

3. **Review all positions**:
   - Exit any other positions with same oracle
   - Add oracle to blacklist

---

### Emergency: Exchange Appears Compromised

**Symptoms**: Unusual order behavior, unexpected liquidations

**Actions**:
1. **Immediately stop bot**:
   ```bash
   pkill -f main.py
   ```

2. **Exit all positions manually** on Polymarket website

3. **Secure wallet**:
   - Transfer funds to cold storage
   - Revoke approvals if needed

4. **Wait for official announcement** before resuming

---

## Monitoring Checklist

### Daily ✅
- [ ] Morning report received
- [ ] Reviewed and approved/skipped opportunities
- [ ] Responded to any alerts
- [ ] Evening positions check

### Weekly ✅
- [ ] Performance review (/weekly_report)
- [ ] Parameter adjustments (if needed)
- [ ] Log file check (errors/warnings)
- [ ] Backup verification

### Monthly ✅
- [ ] Financial analysis (metrics vs. targets)
- [ ] Category performance review
- [ ] API cost review
- [ ] Database cleanup
- [ ] Dependency updates check

### Quarterly ✅
- [ ] Full system audit
- [ ] Strategy effectiveness review
- [ ] Consider new features/improvements
- [ ] Security review (key rotation, permissions)

---

## Useful Commands Reference

### Bot Control
```bash
# Start bot
nohup python main.py > /dev/null 2>&1 &

# Stop bot
pkill -f main.py

# Restart bot
pkill -f main.py && sleep 2 && nohup python main.py > /dev/null 2>&1 &

# Check if running
ps aux | grep main.py
```

### Log Monitoring
```bash
# Tail logs (real-time)
tail -f logs/bot.log

# Search for errors
grep ERROR logs/bot.log | tail -20

# Search for specific market
grep "Warriors" logs/bot.log

# Count errors today
grep ERROR logs/bot.log | grep "$(date +%Y-%m-%d)" | wc -l
```

### Database Queries
```bash
# Open database
sqlite3 data/polymarket.db

# Active positions count
SELECT COUNT(*) FROM positions WHERE status='active';

# Today's P/L
SELECT SUM(pnl_usd) FROM positions WHERE DATE(exit_time) = DATE('now');

# Best trades
SELECT market_question, pnl_pct FROM positions ORDER BY pnl_pct DESC LIMIT 10;

# Worst trades
SELECT market_question, pnl_pct FROM positions ORDER BY pnl_pct ASC LIMIT 10;
```

### Telegram Commands
```
/approve_N $amount  - Execute trade N
/skip_N            - Reject opportunity N
/positions         - Show active positions
/exit_N            - Request exit for position N
/confirm_exit_N    - Confirm exit
/details_N         - Full details for opportunity/position N
/weekly_report     - Performance report
/help              - Command list
```

---

## Contact & Resources

### Polymarket
- Platform: https://polymarket.com
- Status: https://status.polymarket.com (if exists)
- Discord: https://discord.gg/polymarket
- Docs: https://docs.polymarket.com

### Anthropic (Claude)
- Console: https://console.anthropic.com
- Status: https://status.anthropic.com
- Docs: https://docs.anthropic.com

### Telegram
- Bot API: https://core.telegram.org/bots/api
- BotFather: @BotFather on Telegram

---

## Version History

**v1.0** - Initial runbook (Week 4)
- Basic operations documented
- Common troubleshooting scenarios
- Emergency procedures

**Future**:
- Add performance optimization guides
- Add advanced strategies
- Add multi-user procedures (if scaling)
