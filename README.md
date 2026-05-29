# Polymarket Gap Mispricing Bot

Live 9-ticker paper trading bot that exploits a structural mispricing in Polymarket's daily stock binary markets. The market prices YES tokens at ~50-57¢ regardless of gap size; actual close win rates range from 17% (gap-down >2%) to 76% (gap-up >2%). Edge: +5-19% per trade before fees.

**Status:** Paper trading live on Railway + Supabase. Mac not required during market hours.

---

## Infrastructure

| Layer | What runs there |
|-------|----------------|
| **Railway** (server service) | `server.py` — 24/7, auto-restarts on crash |
| **Railway** (cron service) | `tools/eod_update.py` — 4:20 PM ET weekdays |
| **Supabase** (PostgreSQL) | All persistent state: decisions, outcomes, WR, live_quotes |
| **Local Mac** | Monthly model retraining only (`tools/eod_pipeline.py --steps 2-4`) |

Dashboard: `https://polymarket-gap-bot-production.up.railway.app`
GitHub: `https://github.com/jayzhuang1996/polymarket-gap-bot`

---

## Architecture

```
server.py                      ← FastAPI entrypoint + startup wiring
│
├── engine/
│   ├── strategy.py            ← Entry gates (8 gates) + exit ladder (7 levels)
│   ├── session.py             ← 2-min trading loop, reconcile on restart
│   ├── clob_feed.py           ← Polymarket WebSocket + REST fallback (25s)
│   ├── data_feed.py           ← Market discovery, gap calculation, stock price loop (5s)
│   ├── state.py               ← Shared in-memory state (quotes, positions, WR cache)
│   ├── exit_model.py          ← Calibration table: GFR × time × gap_size → token price
│   ├── settlement_model.py    ← Logistic regression: P(win) at any intraday moment
│   ├── sizer.py               ← Quarter-Kelly with 90% CI lower bound (scipy)
│   └── order_manager.py       ← CLOB order placement + fill tracking (dry-run default)
│
├── database/
│   ├── db.py                  ← Dual backend: SQLite (local) / PostgreSQL (Railway)
│   └── wr_store.py            ← Bayesian WR: 5-year OHLC priors + live Polymarket obs
│
├── api/
│   ├── routes.py              ← HTTP endpoints (/api/live-quotes, /api/outcomes, etc.)
│   └── ws.py                  ← WebSocket broadcast to dashboard
│
├── tools/
│   ├── eod_pipeline.py        ← 4-step EOD pipeline (local use only — models need parquet)
│   ├── eod_update.py          ← Step 1: scrape outcomes, update WR (runs on Railway cron)
│   ├── full_session_analysis.py   ← Rebuild full_session_2min.csv
│   ├── calibrate_exit_model.py    ← Rebuild exit model calibration table
│   ├── train_settlement_model.py  ← Retrain logistic regression
│   ├── scrape_history.py      ← Backfill Polymarket trade history
│   ├── oos_validation.py      ← Out-of-sample edge validation (run monthly)
│   └── reversal_analysis.py   ← GFR < −1.0 reversal edge analysis (research, one-time)
│
├── config.py                  ← All constants (thresholds, sizing, VIX, SPRT, Kelly)
├── railway.toml               ← Railway deploy config (start command + restart policy)
├── index.html                 ← Browser dashboard (9-card live signal view)
└── data/
    ├── settlement_model.pkl   ← Trained model bundle (committed to git, loaded at startup)
    ├── exit_model_calibration.csv ← Exit price lookup table (committed, retrained monthly)
    └── ticker_cids.json       ← Polymarket condition IDs per ticker
```

---

## Data Flow

```
9:30am ET open
│
├── yfinance OHLC → gap_bps per ticker (startup, once)
├── Polymarket Gamma API → discover YES/NO token IDs (startup, once)
├── Supabase daily_wr → Bayesian WR blend → wr_cache (startup, once)
└── Supabase decisions → reconcile open positions into memory (startup, once)
                           ↓
         Polymarket CLOB WebSocket (sub-second ticks)
         REST fallback poll every 25 seconds
                           ↓ yes_bid, yes_ask
         Yahoo Finance stock price every 5 seconds → GFR, adj_wr
                           ↓
         ┌─── 2-minute trading loop ──────────────────────────────────┐
         │                                                             │
         │  Entry (v2): gap threshold (per-ticker) →                  │
         │    settlement model P(YES) ≥ 0.55 → YES                   │
         │    settlement model P(YES) ≤ 0.45 → NO                    │
         │    dead-zone 0.45–0.55 → skip                             │
         │    → live edge ≥ time-based floor → price/spread → Kelly  │
         │  Reversal path: gap-UP AND GFR < −1.0 → BUY NO            │
         │    (bypasses model; GFR crossing is its own trigger)       │
         │                                                             │
         │  Exit (7 levels): time exits (2pm/2:30pm/3pm) →           │
         │    GFR reversal (YES only, gfr < −0.5) →                  │
         │    NO profit lock + trail stop →                           │
         │    settlement P(win) per-side →                            │
         │    write to Supabase outcomes                              │
         └─────────────────────────────────────────────────────────────┘
                           ↓ 4:20pm ET (Railway cron)
         eod_update.py: scrape outcomes → scraped_observations → daily_wr
                           ↓ monthly (local Mac)
         eod_pipeline.py: rebuild full_session_2min.csv → retrain models
         → commit updated pkl + csv → Railway auto-deploys
```

---

## Key Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Tickers | 9 (SPX, NVDA, TSLA, AAPL, AMZN, GOOGL, META, MSFT, NFLX) | |
| Gap threshold | Beta-scaled: 0.50% (SPX) → 1.50% (NFLX) | `TICKER_GAP_THRESHOLD` |
| Entry window | 9:35am – 14:00 ET | Tiered floors; hard freeze at 2pm |
| Min edge | **Thu/Fri: 10% flat** · Mon–Wed tiered: 5% (9:35–10:30) / 8% (10:30–12:00) / 15% (12:00–13:30) / 20% (13:30–14:00) | Hard freeze at 14:00 |
| Position sizing | Quarter-Kelly using settlement_p_win | Max $100, 6 positions max |
| Entry direction | Settlement model: P(YES) ≥ 0.55 → YES; ≤ 0.45 → NO | Model-driven, not hardcoded |
| GFR exit (YES) | −0.5 → sell 100% | Disabled for NO trades |
| Time exits | 2:00pm / 2:30pm / 3:00pm ET | Tiered; 3pm is hard |
| PRIOR_WEIGHT | 50 virtual obs | Bayesian weight on 5-year OHLC-derived priors |

---

## Win Rate System

Bayesian blend in `database/wr_store.py`:
- **Prior:** 5-year daily OHLC → empirical gap-direction close WR per ticker. Worth 50 virtual observations.
- **Live:** Each resolved Polymarket market appended nightly by `eod_update.py` (Railway cron).
- **Blend:** `adj_wr = (prior_wr × 50 + live_wr × N) / (50 + N)`. With N < 30, prior dominates.
- **Intraday:** Two-slope GFR adjustment — `+0.15/unit` while GFR×direction > −1.0 (shallow); `+0.35/unit` once GFR×direction < −1.0 (steep). Prevents adj_wr from being inflated when the stock has already crossed prev_close.

---

## Settlement Model (v2 — retrained 2026-05-29)

Logistic regression predicting P(YES settles) at any intraday moment.

- **Features:** `stock_pct_vs_prevclose`, `momentum_30min`, `log(time_before_close)`, `yes_vwap`, `dow_thu`
- **`stock_pct_vs_prevclose`** = gap_pct_fraction × 100 × (1 + gfr) — where stock is vs prev_close right now (%)
- **`momentum_30min`** = change in stock_pct_vs_prevclose over last 30 min — trending toward or away from prev_close
- **Direction:** P(YES) ≥ 0.55 → BUY YES; P(YES) ≤ 0.45 → BUY NO
- **Exit:** YES exits when P(YES) < 0.45; NO exits when P(YES) > 0.55
- **AUC:** 0.70 out-of-sample (vs old model: 0.47 on same holdout) | **Trained on:** 66,533 rows

---

## Component Status

| Component | Status |
|-----------|--------|
| Data pipeline (1,355 Polymarket obs, Oct 2025–present) | Done |
| 8-gate entry + SPRT (AMZN/TSLA) + fast-entry path | Done |
| Intraday reversal NO trades (GFR < −1.0 trigger, +14.8% historical edge) | Done |
| VIX regime filter (30-min refresh during market hours) | Done |
| GFR-based exit ladder (direction-asymmetric) | Done |
| NO trade protection (profit lock + trailing stop) | Done |
| Settlement model (AUC 0.8095, Brier 0.1654) | Done |
| Session crash recovery (reconcile on restart) | Done |
| Supabase migration (PostgreSQL, 8 tables, 12K+ rows) | Done |
| Railway server deploy (24/7, auto-restart) | Done |
| Railway EOD cron (4:20 PM ET weekdays) | Done |
| Live order execution | Not started |

---

## Monthly Maintenance (local Mac)

```bash
# After 30+ new sessions have accumulated:

# 1. Retrain models with new data
python tools/eod_pipeline.py   # steps 2-4: rebuild session csv + retrain pkl + csv

# 2. Run OOS validation
python tools/oos_validation.py

# 3. Commit updated artifacts and push → Railway auto-deploys
git add data/settlement_model.pkl data/exit_model_calibration.csv
git commit -m "chore: retrain models — [date]"
git push
```

---

## Environment Variables

Set in Railway service Variables tab (not committed to git):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Supabase PostgreSQL pooler URL |
| `POLYMARKET_PRIVATE_KEY` | Wallet key (dry-run safe; only used when `LIVE_TRADING=true`) |
| `LIVE_TRADING` | `false` for paper trading, `true` for real orders |
| `BANKROLL_USD` | Total capital for Kelly sizing |
| `PORT` | Auto-injected by Railway — do not set |
