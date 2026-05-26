# Database Architecture
**File:** `data/polymarket.db` (SQLite)  
**Last updated:** May 2026

---

## What Is This Database?

Think of this database as the bot's memory and trading journal combined. It stores:
- Historical win/loss records so the bot knows whether to bet
- Every opportunity the bot evaluated (entered or passed on)
- The result of every trade
- Live market prices during the session

Everything the bot decides is informed by, and recorded in, these tables.

---

## The 9 Tables At a Glance

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  HISTORICAL DATA (built once, refreshed periodically)                               │
│                                                                                     │
│  stock_daily_obs          scraped_observations                                      │
│  (11,295 rows)            (1,355 rows)                                              │
│  5 years of daily         7 months of actual Polymarket                             │
│  stock prices             binary market resolutions                                 │
│  from yfinance            from Gamma API                                            │
│  ─────────────────         ────────────────────────                                 │
│  ticker ◄──shared──────────► ticker                                                 │
│  date                        date                                                   │
│  gap_pct                     gap_pct                                                │
│  close_up                    close_up                                               │
│           │                           │                                             │
│           └──────────┬────────────────┘                                             │
│                      │ feeds into (computed monthly/nightly)                        │
│                      ▼                                                              │
│  ┌───────────────────────────────────────────────────────┐                          │
│  │  isolated_priors (18 rows)   daily_wr (18 rows)       │                          │
│  │  Long-run win rate           Recent Polymarket WR     │                          │
│  │  (pre-Feb 2026 only)         (all observations)       │                          │
│  │                                                        │                          │
│  │  ticker ◄───────────────────► ticker                  │                          │
│  │  direction ◄───────────────► direction                │                          │
│  │  win_rate                    win_rate                  │                          │
│  │  observations                observations              │                          │
│  └──────────────────────┬────────────────────────────────┘                          │
│                         │                                                           │
│              blended in memory via load_base_wr()                                   │
│              → adj_wr (the number the bot actually uses to decide)                  │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LIVE SESSION DATA (written during 9:30am–4pm)                                      │
│                                                                                     │
│  live_quotes (9 rows)                                                               │
│  One row per ticker, overwritten every few seconds                                  │
│  ticker ─────────────── shared key connecting everything                            │
│  yes_bid / yes_ask      what the YES token costs right now                          │
│  no_bid / no_ask        what the NO token costs right now                           │
│  gap_bps                overnight gap size (set at startup, doesn't change)         │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  TRADING JOURNAL (written throughout session and EOD)                               │
│                                                                                     │
│  decisions (63 rows)               outcomes (12 rows)                               │
│  Every market the bot looked at     Result of every actual trade                    │
│                                                                                     │
│  id ◄──────────────────────────────► decision_id  ← THE ONLY EXPLICIT LINK          │
│  date ◄──────────────────────────────► date        ← same trading day               │
│  ticker ◄────────────────────────────► ticker      ← same stock                     │
│  decision  ("BUY YES" or "SKIP")       resolved_yes (1=won, 0=lost)                 │
│  entry_price                           pnl_usd                                      │
│  expected_edge                         exit_type ("resolve" or "time_exit")         │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  NOTIFICATIONS (0 rows — will populate during live trading)                         │
│  Trading alerts: entry signals fired, exits triggered, errors                       │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## The Shared Key That Connects Everything: `ticker`

Every single table has a `ticker` column (SPX, NVDA, TSLA, etc.). That's the spine. When the bot makes a decision about NVDA, it:
1. Looks up `live_quotes` WHERE ticker = 'NVDA' → gets current price
2. Looks up `daily_wr` + `isolated_priors` WHERE ticker = 'NVDA' → gets win rate
3. Writes to `decisions` WHERE ticker = 'NVDA' → logs what it decided
4. Later, writes to `outcomes` via decision_id → records what happened

The second shared key is **`(ticker, direction)`** — used specifically in `daily_wr` and `isolated_priors`. Direction is computed from gap size: gap > 0 = 'gap_up', gap < 0 = 'gap_down'. These two tables must always agree on this key format or the Bayesian blend breaks.

The third shared key is **`(ticker, date)`** — links `decisions` to `scraped_observations` for the same trading day. No foreign key enforces this; it's a logical link you use in analysis.

---

## How a Single Trading Decision Works (Step by Step)

This is what happens every 2 minutes during the session:

```
1. The bot checks the clock.
   Is it a trading day? Is it between 9:30am and 3pm?
   If yes → continue. If no → sleep.

2. For each ticker (NVDA, SPX, TSLA, etc.):

   a. READ live_quotes WHERE ticker = 'NVDA'
      → gets yes_ask = 0.52 (buying YES costs 52 cents)
      → gets gap_bps = +89 (NVDA opened 89 basis points above yesterday's close)
      → gets gfr = 0.4 (40% of that gap has reversed so far today)

   b. COMPUTE adj_wr using load_base_wr('NVDA', gap_up=True):
      → reads isolated_priors WHERE ticker='NVDA' AND direction='gap_up'
         win_rate = 0.785 (from 5-year history)
      → reads daily_wr WHERE ticker='NVDA' AND direction='gap_up'
         win_rate = 0.632 (from 87 real Polymarket observations)
      → blends: adj_wr = (0.785 × 50 + 0.632 × 87) / (50 + 87) = 0.697

   c. COMPUTE edge:
      → edge = adj_wr × $1.00 payout - entry_price
      → edge = 0.697 × 1.00 - 0.52 = +17.7¢ per dollar

   d. DECIDE:
      If edge > threshold AND spread is tight enough → BUY YES
      Otherwise → SKIP

   e. WRITE to decisions:
      → ticker='NVDA', entry_price=0.52, expected_edge=0.177,
        decision='BUY YES (gap +89 bps, ~$0.52, depth 50260)'

3. After 4pm (EOD pipeline runs):
   a. Polymarket resolves: did NVDA close higher than yesterday? → YES
   b. WRITE to outcomes:
      → decision_id = [id from step 2e], resolved_yes=1,
        pnl_usd = contracts × ($1.00 - $0.52) = +$48 on $52 spent
```

---

## Table-by-Table Reference

### `stock_daily_obs` — The Long Memory
**What it is:** 5 years of daily stock data. Every row = one stock, one day.  
**Why it matters:** Tells us how often NVDA historically closed up after a gap-up day. Built from yfinance once per month.  
**Key columns:** `ticker`, `date`, `gap_pct` (how big the overnight gap was), `close_up` (1 = stock went up that day)  
**Shared key:** `(ticker, date)`  
**Written by:** `update_stock_priors()` — runs first trading day of each month  
**Read by:** `_recompute_priors_from_obs()` → produces `isolated_priors`

---

### `scraped_observations` — Polymarket-Specific History
**What it is:** Same concept as `stock_daily_obs` but sourced directly from Polymarket market resolutions. Oct 2025 → today.  
**Why it matters:** More relevant than 5-year history because it reflects the current market regime and Polymarket-specific dynamics.  
**Key columns:** `ticker`, `date`, `gap_pct`, `close_up`  
**Shared key:** `(ticker, date)` — unique constraint, no duplicates  
**Written by:** `eod_update.py` — runs nightly at 4:20pm via cron  
**Read by:** `daily_update()` → produces `daily_wr`

---

### `isolated_priors` — The Long-Run Baseline Win Rate
**What it is:** One row per (ticker, direction). The "what percentage of the time does this situation win?" number derived from 5-year stock history.  
**Why it matters:** Acts as the anchor in the Bayesian blend. Even if recent Polymarket data is thin, the prior keeps the estimate sane.  
**Key columns:** `ticker`, `direction` (gap_up / gap_down), `win_rate`, `observations`  
**Shared key:** `(ticker, direction)` — primary key, exactly 18 rows  
**Written by:** `update_stock_priors()` monthly OR `rebuild_priors()` on demand  
**Read by:** `load_base_wr()` — called at every trading decision

---

### `daily_wr` — The Recent Polymarket Win Rate
**What it is:** Same structure as `isolated_priors` but computed from recent `scraped_observations`. Updates every night.  
**Why it matters:** Captures regime shifts. If the market is behaving differently from its 5-year history, this table picks it up.  
**Key columns:** `ticker`, `direction`, `win_rate`, `observations`, `updated_at`  
**Shared key:** `(ticker, direction)` — one row per pair (de-duplicated as of May 2026 fix)  
**Written by:** `daily_update()` — called by `eod_update.py`  
**Read by:** `load_base_wr()` — blended with `isolated_priors`

---

### `live_quotes` — The Pulse During Session
**What it is:** One row per ticker. Overwritten every few seconds during market hours.  
**Why it matters:** The bot reads this to know what it would actually pay right now. Also feeds the real-time dashboard.  
**Key columns:** `ticker`, `yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `gap_bps`, `updated_at`  
**Shared key:** `ticker` (primary key)  
**Written by:** `update_live_quote()` — called from `clob_feed.py` on every CLOB price update  
**Read by:** Dashboard (`/api/live-quotes`), trading session loop indirectly via `state.current_quotes`

---

### `decisions` — The Trading Journal
**What it is:** Every market the bot evaluated, regardless of outcome. The full log.  
**Why it matters:** Post-session analysis. You can see every opportunity: which ones were entered, which were skipped and why, and what the expected edge was at the time.  
**Key columns:** `id` (links to outcomes), `date`, `ticker`, `decision` (the full reason string), `entry_price`, `expected_edge`, `gap_bps`  
**Shared key:** `id` → `outcomes.decision_id`; `(ticker, date)` → `scraped_observations`  
**Written by:** `store_decision()` — called in `trading_session_loop` every 2 minutes  
**Read by:** Dashboard, Hermes agent (future), analytics scripts

---

### `outcomes` — The Scoreboard
**What it is:** For every trade entered, the final result. P&L, how it was resolved, exit price.  
**Why it matters:** The only source of truth for "did this system make money?" Also used to evaluate whether the edge estimates are accurate over time.  
**Key columns:** `decision_id` → `decisions.id`, `resolved_yes`, `pnl_usd`, `exit_type` (resolve / time_exit)  
**Shared key:** `decision_id` is the only hard FK in the entire database  
**Written by:** `store_outcome()` — called in `trading_session_loop` on exit or by `eod_update.py` on resolution  
**Read by:** Dashboard (`/api/outcomes`, `/api/pnl-history`), performance analytics

---

### `notifications` — Alerts (Currently Empty)
**What it is:** Trading alerts: entry signals fired, exits triggered, errors during session.  
**Why it matters:** Will give you a real-time log of what the bot did and why, separate from the full `decisions` journal.  
**Written by:** Not yet implemented in session loop (wired in but nothing calls it yet)  
**Read by:** Dashboard (`/api/notifications`)

---

## Bayesian Blend — How adj_wr Is Computed

This is the most important formula in the system. It combines two win-rate estimates:

```
adj_wr = (isolated_prior × 50 + daily_wr × N) / (50 + N)

Where:
  isolated_prior  = win rate from 5-year stock history (e.g., 0.785)
  daily_wr        = win rate from recent Polymarket observations (e.g., 0.632)
  50              = "trust weight" — treat the prior as if it's backed by 50 fresh observations
  N               = actual number of Polymarket observations we have (e.g., 87)

Example: NVDA gap_up
  adj_wr = (0.785 × 50 + 0.632 × 87) / (50 + 87)
         = (39.25 + 55.0) / 137
         = 0.688

Intuition: When N is small (e.g., 10), the 5-year prior dominates (82% weight).
           When N is large (e.g., 200), Polymarket data dominates (80% weight).
           MIN_OBS_FOR_DB_WR = 30 means daily_wr is ignored entirely if N < 30.
```

---

## Data Flow Map: What Runs When

```
Every weekday at 4:20pm PT (automated via launchd plist):
  tools/eod_pipeline.py
    ├── Step 1: eod_update.py
    │     ├── Scrapes today's Polymarket resolution via Gamma API
    │     ├── Appends today's CLOB trades to *_trades.parquet
    │     ├── Writes new row to scraped_observations
    │     └── Calls daily_update() → refreshes daily_wr
    │
    ├── Step 2: full_session_analysis.py
    │     ├── Reads *_trades.parquet (all history)
    │     ├── Fetches intraday stock prices from yfinance (last 60 days only)
    │     └── Rebuilds data/full_session_2min.csv (57,470 rows)
    │
    ├── Step 3: calibrate_exit_model.py
    │     └── Rebuilds data/exit_model_calibration.csv (when to exit)
    │
    └── Step 4: train_settlement_model.py
          └── Retrains data/settlement_model.pkl (P(win) live inference)

First trading day of each month:
  update_stock_priors()
    ├── Fetches incremental yfinance daily OHLCV
    ├── Appends to stock_daily_obs
    └── Recomputes isolated_priors

At server startup (python server.py):
  ├── Loads daily_wr + isolated_priors → computes adj_wr per ticker (in memory)
  ├── Discovers live Polymarket markets via Gamma API
  └── Starts 6 background loops:
       ├── stock_price_loop    (GFR every 5 seconds via yfinance)
       ├── polymarket_loop     (CLOB prices via WebSocket)
       ├── periodic_rest_poll  (REST fallback every 25 seconds)
       ├── trading_session_loop (entry/exit decisions every 2 minutes)
       ├── broadcast_worker    (sends live updates to dashboard)
       └── stock_price_loop    (GFR computation)
```

---

## Known Data Gaps and Limitations

| Gap | Impact | Fix |
|-----|--------|-----|
| ~~GFR missing Oct 2025 → Feb 2026~~ | ~~Exit model on 44 days only~~ | Fixed — Twelve Data 5-min backfill, AUC 0.683 → 0.8095 |
| SQLite files on local disk | Bot requires Mac to be on during market hours | Supabase migration (Railway + Supabase plan, in progress) |
| decisions table missing adj_wr at entry | Can't audit whether edge estimate was accurate | Add adj_wr, gfr_at_entry, spread_at_entry columns (pending) |
| notifications table empty | No alert log | Wire store_notification() into session loop (pending) |
| outcomes only 12 rows | Can't evaluate strategy performance | Normal — accumulates as paper trades run |
