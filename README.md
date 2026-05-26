# Polymarket Gap Mispricing Bot

Live 9-ticker paper trading bot that exploits a structural mispricing in Polymarket's daily stock binary markets. The market prices YES tokens at ~50-57¢ regardless of gap size; actual close win rates range from 17% (gap-down >2%) to 76% (gap-up >2%). Edge: +5-19% per trade before fees.

**Status:** Paper trading (local, Mac must be on). Railway + Supabase migration in progress to remove that constraint.

---

## Architecture

```
server.py                      ← FastAPI entrypoint + startup wiring (run this)
│
├── engine/
│   ├── strategy.py            ← Entry gates (8 gates) + exit ladder (7 levels)
│   ├── session.py             ← 2-min trading loop, reconcile on restart
│   ├── clob_feed.py           ← Polymarket WebSocket + REST fallback
│   ├── data_feed.py           ← Market discovery, gap calculation, stock price loop
│   ├── state.py               ← Shared in-memory state (quotes, positions, WR cache)
│   ├── exit_model.py          ← Calibration table: GFR × time × gap_size → token price
│   ├── settlement_model.py    ← Logistic regression: P(win) at any intraday moment
│   └── order_manager.py       ← CLOB order placement + fill tracking
│
├── database/
│   ├── db.py                  ← SQLite schema + CRUD (decisions, outcomes, live_quotes)
│   └── wr_store.py            ← Bayesian WR: 5-year OHLC priors + live Polymarket obs
│
├── api/
│   ├── routes.py              ← HTTP endpoints (/api/live-quotes, /api/outcomes, etc.)
│   └── ws.py                  ← WebSocket broadcast to dashboard
│
├── tools/
│   ├── eod_pipeline.py        ← 4-step EOD pipeline (runs nightly at 4:20pm ET via launchd)
│   ├── eod_update.py          ← Step 1: scrape Polymarket outcomes, update WR store
│   ├── full_session_analysis.py   ← Rebuild full_session_2min.csv (57,470 rows)
│   ├── calibrate_exit_model.py    ← Rebuild exit model calibration table
│   ├── train_settlement_model.py  ← Retrain logistic regression
│   ├── scrape_history.py      ← Backfill Polymarket trade history via Gamma API
│   └── oos_validation.py      ← Out-of-sample edge validation (run monthly)
│
├── config.py                  ← All constants (thresholds, sizing, VIX, SPRT, Kelly)
├── index.html                 ← Browser dashboard (9-card live signal view)
└── data/
    ├── polymarket.db          ← SQLite (decisions, outcomes, win rates, live quotes)
    ├── settlement_model.pkl   ← Trained model bundle
    └── full_session_2min.csv  ← 57,470 rows of historical 2-min Polymarket sessions
```

---

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Start server (run each market day before 9:35am ET)
python server.py   # Dashboard → http://localhost:8000

# EOD pipeline runs automatically at 4:20pm ET via launchd
# Manual run: python tools/eod_pipeline.py

# Retrain settlement model (periodically as data accumulates)
python tools/train_settlement_model.py

# Out-of-sample validation (monthly)
python tools/oos_validation.py
```

**Install launchd agents (one-time):**
```bash
cp deploy/com.polymarket.eod_update.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.polymarket.eod_update.plist
cp deploy/com.polymarket.server.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.polymarket.server.plist
```

---

## Data Flow

```
9:30am ET open
│
├── yfinance OHLC → gap_bps per ticker (startup, once)
├── Polymarket Gamma API → discover YES/NO token IDs (startup, once)
├── Bayesian WR blend → adj_wr per ticker (startup, once)
└── Crash recovery → reconcile open DB positions into memory (startup, once)
                           ↓
         Polymarket CLOB WebSocket (sub-second)
         REST fallback every 25 seconds
                           ↓ yes_bid, yes_ask, depth
         yfinance stock price every 5 seconds → GFR
                           ↓
         ┌─── 2-minute trading loop ────────────────────────────────┐
         │                                                           │
         │  For each ticker:                                         │
         │    Entry check (8 gates): gap threshold → GFR signal →   │
         │      SPRT/3-of-4 conviction → price band → edge → spread │
         │      → VIX regime → Kelly sizing → LOG to DB             │
         │                                                           │
         │    Exit check (7 levels): time exits (2pm/2:30pm/3pm) →  │
         │      GFR reversal (YES only) → NO profit lock + trail →  │
         │      settlement model P(win) → LOG to DB                 │
         └───────────────────────────────────────────────────────────┘
                           ↓ 4:20pm ET
         EOD pipeline: scrape outcomes → update WR → rebuild models
```

---

## Key Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Tickers | 9 (SPX, NVDA, TSLA, AAPL, AMZN, GOOGL, META, MSFT, NFLX) | |
| Gap threshold | Beta-scaled: 0.50% (SPX) → 1.50% (NFLX) | `TICKER_GAP_THRESHOLD` |
| Entry window | 9:35am – 12:00pm ET | Hard freeze at noon |
| Min edge | 3% standard / 8% after 10:30am / 10% Thursday | Dynamic per regime |
| Position sizing | Quarter-Kelly on 90% CI lower bound | Max $100, 6 positions max |
| Daily loss limit | $500 | Stops all trading for the day |
| GFR exit (YES) | −0.5 → sell 100% | Disabled for NO trades (43% WR at GFR < −0.5, not actionable) |
| Time exits | 2:00pm / 2:30pm / 3:00pm ET | Tiered; 3pm is hard |
| PRIOR_WEIGHT | 50 virtual obs | Bayesian weight on 5-year OHLC-derived priors |
| SPRT | AMZN + TSLA YES only | LR ≥ 5.0 enter, ≤ 0.2 abort |

---

## Win Rate System

Bayesian blend in `database/wr_store.py`:
- **Prior:** 5-year daily OHLC → empirical gap-direction close WR per ticker. Worth 50 virtual observations.
- **Live:** Each resolved Polymarket market appended nightly by `eod_pipeline.py`.
- **Blend:** `adj_wr = (prior_wr × 50 + live_wr × N) / (50 + N)`. With N < 30, prior dominates entirely.

Real-time intraday adjustment: `adj_wr += 0.15 × gfr × direction_sign`

---

## Settlement Model

Logistic regression predicting P(trade wins) at any intraday moment. Used for mid-session exits.

- **Features:** `gfr`, `gfr_velocity`, `log(time_before_close)`, `abs(gap_pct)`, `market_p_win`, `dow_thu`, `vix_high`
- **Exit triggers:** P(win) < 45% → sell 100%; live_edge < 0 → sell 80%
- **AUC:** 0.8095 | **Brier:** 0.1654 | **Trained on:** 57,313 rows from `data/full_session_2min.csv` (GFR backfilled Oct 2025–Feb 2026 via Twelve Data)

---

## Component Status

| Component | Status |
|-----------|--------|
| Data pipeline (1,355 Polymarket observations, Oct 2025–present) | Done |
| 3-gate scanner + SPRT (AMZN/TSLA) | Done |
| VIX regime filter | Done |
| GFR-based exit ladder (direction-asymmetric) | Done |
| NO trade protection (profit lock + trailing stop) | Done |
| Settlement model (AUC 0.8095, Brier 0.1654) | Done |
| Session crash recovery (reconcile on restart) | Done |
| EOD pipeline (4-step, launchd automated) | Done |
| Live WebSocket dashboard | Done |
| Railway deploy (24/7 uptime, no Mac required) | In progress |
| Supabase migration (SQLite → PostgreSQL) | In progress |
| Live order execution | Not started |
