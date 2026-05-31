# Data Schema & Semantic Layer

**Last updated:** 2026-05-29

---

## The One Rule That Makes Everything Clear

**Every data store has exactly one writer and one job. If you need data, look it up in the table below — don't guess which file to touch.**

| Question you want to answer | Authoritative source | Written by | Updated |
|---|---|---|---|
| Did NVDA close up on May 15? | `scraped_observations` in Railway SQLite + Supabase | `eod_update.py` EOD cron | Nightly 4:20pm ET (Railway auto) |
| What is NVDA's current win rate? | `daily_wr` in Railway SQLite + Supabase | `eod_update.py` EOD cron | Nightly 4:20pm ET (Railway auto) |
| What price did YES trade at during the session? | `{ticker}_trades.parquet` (local Mac) | `eod_pipeline.py` step 1 (Mac cron 1:20pm PT) | Nightly via Mac cron or manual |
| What was the bot's signal at 10:34am today? | `scan_log` in Railway SQLite + Supabase | Live bot (`engine/session.py`) | Every 2 min during session |
| What trades did the bot enter? | `decisions` in Railway SQLite + Supabase | Live bot on ENTER | Real-time |
| Did I make money today? | `outcomes` in Railway SQLite + Supabase | Live bot on EXIT | Real-time |
| What is the model's P(YES settles)? | `data/settlement_model.pkl` (local → deployed to Railway) | `tools/train_settlement_model.py` | Nightly via Mac cron, auto-pushed to Railway |
| 2-min VWAP + GFR for a historical session | `data/full_session_2min.csv` (local Mac) | `tools/extend_2min_data.py` | Nightly via Mac cron |
| Settlement probability lookup table | `data/settlement_probability.csv` (local Mac) | `tools/extend_2min_data.py` (side output) | Auto-regenerated when CSV updated |

---

## Three Layers — What Each Is For

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — TRAINING DATA (local Mac only)                       │
│                                                                  │
│  {ticker}_trades.parquet  →  raw trade executions               │
│  full_session_2min.csv    →  engineered 2-min intervals         │
│  settlement_model.pkl     →  trained model (deployed to Railway) │
│                                                                  │
│  Purpose: build and retrain the model                           │
│  Writer:  eod_pipeline.py (Mac cron 1:20pm PT, auto-backfills) │
│  Never written to by the live bot on Railway                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2 — LIVE SESSION (Railway SQLite at /data/polymarket.db) │
│                                                                  │
│  scan_log           →  2-min bot evaluations (CLOB snapshots)  │
│  decisions          →  every trade entry                        │
│  outcomes           →  every exit + P&L                         │
│  daily_wr           →  win rate per ticker, recomputed nightly  │
│  scraped_observations → one row per ticker/day (gap + outcome)  │
│  live_quotes        →  latest order book per ticker (overwritten)│
│                                                                  │
│  Purpose: run the live bot and record what it does              │
│  Writer:  engine/session.py (live) + eod_update.py (EOD cron)  │
│  Fast SQLite writes, never blocked by network                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3 — REMOTE MIRROR (Supabase via REST API)                │
│                                                                  │
│  scan_log           →  mirrored from Layer 2                    │
│  decisions          →  mirrored from Layer 2                    │
│  outcomes           →  mirrored from Layer 2                    │
│  daily_wr           →  upserted nightly (on ticker+direction+   │
│                          gap_bucket conflict)                    │
│  scraped_observations → upserted nightly (on date+ticker)       │
│                                                                  │
│  Purpose: survive Railway volume failure, query from anywhere   │
│  Writer:  dual-write in db.py (background thread, best-effort)  │
│           + EOD batch sync via eod_update.py                    │
│  Never used by the bot directly — mirror only                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## End-to-End Daily Workflow

This is the full data lifecycle from market open to the next morning's models.

### During Session (9:30am–4:30pm ET) — Railway

```
Every 5 seconds:
  data_feed.py → Yahoo Finance → stock price per ticker
               → GFR, adj_wr updated in memory

Every sub-second:
  clob_feed.py → Polymarket WebSocket → yes_bid, yes_ask updated in memory
  (REST fallback: poll every 25s if WebSocket stalls)

Every 2 minutes:
  session.py → evaluate all 9 tickers:
    → store_scan_log() → Railway SQLite + Supabase (background thread)
    → on ENTRY: store_decision() → Railway SQLite + Supabase (background thread)
    → on EXIT:  store_outcome()  → Railway SQLite + Supabase (background thread)
```

### After Market (4:20pm ET) — Railway auto-cron

```
POST /api/trigger/eod → tools/eod_update.py runs on Railway:
  1. Polymarket Core API → today's trade executions → scraped_observations + daily_wr
     (writes to Railway SQLite only — parquets are local Mac)
  2. Supabase batch sync:
     → decisions    (upsert on id)
     → outcomes     (upsert on id)
     → scan_log     (upsert on id)
     → daily_wr     (upsert on ticker+direction+gap_bucket)
     → scraped_observations (upsert on date+ticker)
```

### After Market (1:20pm PT = 4:20pm ET) — Mac cron

```
python tools/eod_pipeline.py  (launchd: com.polymarket.eod_update.plist)
  Auto-detects missed days (up to 5 back) via scraped_observations gaps + NYSE calendar

  Step 1 — eod_update.py --date YYYY-MM-DD:
    Polymarket Core API → appends to {ticker}_trades.parquet (local only)
    yfinance OHLC → scraped_observations + daily_wr in local SQLite
    Supabase batch sync (same as Railway step 2)

  Step 2 — extend_2min_data.py:
    Reads {ticker}_trades.parquet → computes 2-min VWAP intervals
    Appends to full_session_2min.csv (deduped by ticker+date)
    Regenerates settlement_probability.csv

  Step 3 — calibrate_exit_model.py:
    Reads full_session_2min.csv → rebuilds exit_model_calibration.csv

  Step 4 — train_settlement_model.py:
    Reads full_session_2min.csv → retrains settlement_model.pkl

  Step 5 — git deploy:
    git add data/settlement_model.pkl data/exit_model_calibration.csv
    git commit + git push origin main
    → Railway auto-deploys fresh models on next startup
```

### What Lives Where Permanently

| Data | Local Mac | Railway SQLite | Supabase |
|------|-----------|----------------|---------|
| `{ticker}_trades.parquet` | Yes (primary) | No | No |
| `full_session_2min.csv` | Yes (primary) | No | No |
| `settlement_model.pkl` | Yes (primary + git) | No (loaded at startup) | No |
| `exit_model_calibration.csv` | Yes (primary + git) | No (loaded at startup) | No |
| `scan_log` | No | Yes (primary) | Yes (mirror) |
| `decisions` | No | Yes (primary) | Yes (mirror) |
| `outcomes` | No | Yes (primary) | Yes (mirror) |
| `daily_wr` | Yes (local copy) | Yes (primary) | Yes (mirror+upsert) |
| `scraped_observations` | Yes (local copy) | Yes (primary) | Yes (mirror+upsert) |

---

## How Data Gets Into Each Layer

### Layer 1: Training data (local Mac)

```
Step 1 — Pull today's trades + gap:
  python tools/eod_update.py --date YYYY-MM-DD
  Sources: Polymarket Core API → appends to {ticker}_trades.parquet
           yfinance daily OHLC → scraped_observations + daily_wr in local SQLite

Step 2 — Engineer 2-min intervals:
  python tools/extend_2min_data.py
  Sources: {ticker}_trades.parquet (local)
           markets.parquet for dates ≤ May 1 2026 (condition_id lookup, no API call)
           Gamma API for dates > May 1 2026 (condition_id + outcome lookup)
           yfinance 5-min intraday (GFR calculation)
  Output: full_session_2min.csv (appends, deduped by ticker+date)
          settlement_probability.csv (regenerated from full CSV)

Step 3 — Retrain models:
  python tools/calibrate_exit_model.py  → exit_model_calibration.csv
  python tools/train_settlement_model.py → settlement_model.pkl

Step 4 — Deploy to Railway:
  git add data/settlement_model.pkl data/exit_model_calibration.csv
  git push origin main  → Railway auto-deploys

Or run all five steps at once (with auto-backfill + auto-deploy):
  python tools/eod_pipeline.py
```

### Layer 2: Live session (Railway auto)

```
During session (9:30–4:30pm ET):
  engine/session.py → CLOB WebSocket/REST → scan_log every 2 min
                    → decisions on ENTER
                    → outcomes on EXIT

EOD cron (4:20pm ET, Railway auto):
  POST /api/trigger/eod → eod_update.py
    Polymarket Core API → scraped_observations + daily_wr in Railway SQLite
    REST sync → batch-pushes today's rows to Supabase
```

### Layer 3: Supabase (auto via REST)

```
Real-time (during session):
  store_scan_log() → SQLite write → background thread → POST /rest/v1/scan_log
  store_decision() → SQLite write → background thread → POST /rest/v1/decisions
  store_outcome()  → SQLite write → background thread → POST /rest/v1/outcomes

EOD batch (4:20pm ET, Railway + Mac cron):
  _sync_sqlite_to_supabase() in eod_update.py → upsert for full day:
    decisions, outcomes, scan_log (upsert on id)
    daily_wr (upsert on ticker+direction+gap_bucket)
    scraped_observations (upsert on date+ticker)

On-demand backfill (for any gap):
  POST /api/admin/sync-supabase?date=YYYY-MM-DD
```

---

## Table Schemas

### `scan_log`
Every 2-min bot evaluation tick. The live equivalent of `full_session_2min.csv`.

| Column | Type | Description |
|---|---|---|
| id | int | Auto PK |
| date | text | Trading date (YYYY-MM-DD) |
| scanned_at | text | Exact timestamp of this tick |
| ticker | text | SPX, NVDA, TSLA, etc. |
| et_time | text | Eastern time (HH:MM) |
| gap_bps | real | Overnight gap in basis points |
| yes_ask | real | Current CLOB ask price |
| yes_bid | real | Current CLOB bid price |
| adj_wr | real | Bayesian-adjusted win rate |
| edge | real | adj_wr × (1−fee) − yes_ask |
| gfr | real | Gap Fill Ratio at this tick |
| gfr_velocity | real | Rate of GFR change |
| settlement_p_win | real | Model P(win) |
| signal | text | FLAT / GO / FADE / WATCH / SKIP |
| vix_change | real | VIX % change since open |

**Written by:** `engine/session.py` every 2 min. Mirrored to Supabase.

---

### `decisions`
Every trade entry.

| Column | Type | Description |
|---|---|---|
| id | int | Auto PK (included in REST payload to keep Railway + Supabase sequences aligned) |
| date | text | Trading date |
| ticker | text | Ticker |
| entry_side | text | YES or NO |
| entry_price | real | Price paid |
| position_size | real | USD invested |
| expected_edge | real | Edge at entry |
| adj_wr | real | WR at entry |
| gfr_at_entry | real | GFR when entered |
| gap_bps | real | Gap at entry |
| yes_bid / yes_ask | real | Order book at entry |
| spread_bps | real | Spread in bps at entry |
| created_at | text | Entry timestamp |

**Written by:** `engine/session.py` on ENTER. Mirrored to Supabase.
**Note:** `position_size` is computed as quarter-Kelly on `(1 − settlement_p)` for NO trades, `settlement_p` for YES trades. Pre-2026-05-29 NO trades were sized at $0 due to a bug (now fixed).

---

### `outcomes`
Every exit — P&L record for each closed trade.

| Column | Type | Description |
|---|---|---|
| id | int | Auto PK (included in REST payload) |
| decision_id | int | FK → decisions.id (same id across Railway + Supabase) |
| date | text | Trading date |
| ticker | text | Ticker |
| resolved_yes | int | 1 = YES settled, 0 = NO settled |
| pnl_usd | real | Realized P&L |
| exit_price | real | Price at exit |
| exit_type | text | settlement / time_exit / stop_loss |
| closed_at | text | Exit timestamp |

**Written by:** `engine/session.py` exit handlers. Mirrored to Supabase.

---

### `scraped_observations`
One row per ticker per day — ground truth for WR model.

| Column | Type | Description |
|---|---|---|
| id | int | Auto PK |
| date | text | Trading date |
| ticker | text | Ticker |
| gap_pct | real | Overnight gap as decimal (0.012 = 1.2%) |
| close_up | int | 1 = closed above prev_close |
| created_at | text | Scraped timestamp |

**Written by:** `eod_update.py` nightly. `UNIQUE(date, ticker)` — safe to re-run.
**Mirror:** Supabase upsert on `(date, ticker)` — sent WITHOUT id to avoid PK sequence conflicts.

---

### `daily_wr`
Current win rate per ticker per direction and gap bucket, recomputed nightly.

| Column | Type | Description |
|---|---|---|
| id | int | Auto PK |
| ticker | text | Ticker |
| direction | text | YES or NO |
| win_rate | real | Historical WR |
| observations | int | Sample size |
| source | text | 'live' or 'prior' |
| updated_at | text | Last update |
| gap_bucket | text | 'all', 'small', 'large' (default: 'all') |

**Written by:** `eod_update.py` nightly. **Read by:** `engine/state.py` at Railway startup.
**Mirror:** Supabase `UNIQUE(ticker, direction, gap_bucket)` — upserted with id for PK alignment.

---

## File-Based Data (Local Mac)

### `data/full_session_2min.csv`
2-minute interval VWAP for every resolved session. The training dataset.

| Column | Description |
|---|---|
| ticker | SPX, NVDA, etc. |
| date | Trading date |
| dow | Mon/Tue/Wed/Thu/Fri |
| tbf_min | Minutes before 4pm close (390=9:30am) |
| yes_vwap | Volume-weighted avg YES token price in this 2-min window |
| gfr | Gap Fill Ratio at this time |
| gap_pct | Overnight gap % (0.214 = 0.214%, not 21.4%) |
| outcome_yes | 1 = YES settled at $1 |
| n_trades | Number of trades in this window |
| stock_pct_vs_prevclose | Where stock is vs prev_close now (%) — model feature |
| momentum_30min | 30-min change in stock_pct_vs_prevclose — model feature |

**Rows:** ~66,998 (Oct 2025 → present) | **Built by:** `tools/extend_2min_data.py`

---

### `data/{ticker}_trades.parquet` (9 files)
Raw Polymarket trade executions. Source of truth for VWAP.

| Column | Description |
|---|---|
| condition_id | Links trade to a specific date's market |
| timestamp | Unix timestamp (seconds) |
| price | YES token execution price (0.0–1.0) |
| usd_amount | Dollar value |
| maker_direction | Buy or Sell |

**Built by:** `eod_update.py` via Polymarket Core API | **Appends only, deduped.**

---

### `data/markets.parquet`
Static HuggingFace dump of Polymarket market metadata.
**Coverage:** Oct 2025 → May 1, 2026 | **Used by:** `extend_2min_data.py` for pre-cutoff condition_id lookups. For dates after May 1 2026, Gamma API is used instead.

---

### `data/settlement_model.pkl`
Logistic regression: input (stock_pct_vs_prevclose, momentum_30min, log_tbf, yes_vwap, dow_thu) → P(YES settles).
**AUC:** 0.7928 (OOS, retrained 2026-05-29) | **Built by:** `tools/train_settlement_model.py`
**Deployment:** committed to git → auto-pushed nightly by Mac cron → Railway loads at startup.

---

## What NOT to Do

| Don't | Because |
|---|---|
| Write scan_log from local tools | scan_log is live session data only — backfill via `/api/admin/sync-supabase` |
| Run eod_update.py on Railway manually | It runs automatically at 4:20pm ET via cron |
| Use full_session_analysis.py | Replaced by extend_2min_data.py |
| Use scrape_history.py or backfill_from_parquet.py | One-time historical scripts, already run |
| Modify full_session_2min.csv directly | Always go through extend_2min_data.py |
| Send scraped_observations to Supabase with `id` field | PK sequences diverged — send WITHOUT id, conflict on (date,ticker) |
| Run eod_pipeline.py steps manually in separate commands | Run `python tools/eod_pipeline.py` — it handles backfill + deploy automatically |

---

## Known Data Integrity Issues

| Issue | Impact | Status |
|---|---|---|
| Supabase psycopg2 / pooler broken | Resolved — REST API path implemented | Fixed |
| May 26 scan_log: 0 rows | Railway didn't start cleanly | Lost |
| May 28 scan_log: only 9:31–10:51 ET | Redeployed mid-session | Partially lost |
| May 27–28 scan_log not in Supabase | Pre-dates REST fix | Backfill via `/api/admin/sync-supabase` |
| full_session_2min.csv gap May 2–26 | Fixed 2026-05-28 via extend_2min_data.py | Fixed |
| Pre-2026-05-29 NO trades: position_size = $0 | quarter-Kelly received raw settlement_p (≤0.50 for NO) → sizer returned 0 | Fixed going forward; historical records corrupted |
| Pre-2026-05-29 Supabase duplicates | Real-time + EOD sync both omitted id → Supabase generated new PK each time | Fixed (id now included in REST payload) |
| AMZN 2026-05-29 YES exit outcome | decision_id mismatch from pre-fix era | Corrupted; cannot fix retroactively |
| `stock_daily_obs` stale (last entry 2026-05-22) | Different from scraped_observations — populated by a separate pipeline not yet running | Low priority; does not affect live trading |
| wr_cache stale until Railway restart | adj_wr uses yesterday's WR priors intraday | Known, low priority — fix: reload at session start |
| DST hardcode (ET_OFFSET_H = -4) | Breaks in November: entries miss 9:30–10:30, exits 1hr late | Fix before November — use pytz/zoneinfo |
