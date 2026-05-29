# Data Schema & Semantic Layer

**Last updated:** 2026-05-28

---

## The One Rule That Makes Everything Clear

**Every data store has exactly one writer and one job. If you need data, look it up in the table below — don't guess which file to touch.**

| Question you want to answer | Authoritative source | Written by | Updated |
|---|---|---|---|
| Did NVDA close up on May 15? | `scraped_observations` in Railway SQLite | `eod_update.py` EOD cron | Nightly 4:20pm ET (auto) |
| What is NVDA's current win rate? | `daily_wr` in Railway SQLite | `eod_update.py` EOD cron | Nightly 4:20pm ET (auto) |
| What price did YES trade at during the session? | `{ticker}_trades.parquet` (local Mac) | `eod_update.py` run locally | Run manually after 4pm ET |
| What was the bot's signal at 10:34am today? | `scan_log` in Railway SQLite + Supabase | Live bot (`engine/session.py`) | Every 2 min during session |
| What trades did the bot enter? | `decisions` in Railway SQLite + Supabase | Live bot on ENTER | Real-time |
| Did I make money today? | `outcomes` in Railway SQLite + Supabase | Live bot on EXIT | Real-time |
| What is the model's P(YES settles)? | `data/settlement_model.pkl` (local → deployed) | `tools/train_settlement_model.py` | Manually after retraining |
| 2-min VWAP + GFR for a historical session | `data/full_session_2min.csv` (local Mac) | `tools/extend_2min_data.py` | Run manually after 4pm ET |
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
│  Writer:  you, manually, after 4pm ET                           │
│  Never written to by the live bot                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2 — LIVE SESSION (Railway SQLite at /data/polymarket.db) │
│                                                                  │
│  scan_log     →  2-min bot evaluations (CLOB snapshots)         │
│  decisions    →  every trade entry                              │
│  outcomes     →  every exit + P&L                               │
│  daily_wr     →  win rate per ticker, recomputed nightly        │
│  live_quotes  →  latest order book per ticker (overwritten)     │
│                                                                  │
│  Purpose: run the live bot and record what it does              │
│  Writer:  engine/session.py (live) + eod_update.py (EOD cron)  │
│  Fast SQLite writes, never blocked by network                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3 — REMOTE MIRROR (Supabase via REST API)                │
│                                                                  │
│  scan_log, decisions, outcomes  →  mirrored from Layer 2        │
│                                                                  │
│  Purpose: survive Railway volume failure, query from anywhere   │
│  Writer:  dual-write in db.py (background thread, best-effort)  │
│           + EOD batch sync via eod_update.py                    │
│  Never used by the bot directly — mirror only                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## How Data Gets Into Each Layer

### Layer 1: Training data (local Mac)

```
Step 1 — Pull today's trades + gap:
  python tools/eod_update.py
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

Step 3 — Retrain models (when enough new data):
  python tools/train_settlement_model.py  → settlement_model.pkl
  python tools/calibrate_exit_model.py   → exit_model_calibration.csv

Or run all four steps at once:
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
    Polymarket Core API → appends trades to Railway SQLite (not parquets — those are local)
    yfinance → scraped_observations + daily_wr in Railway SQLite
    REST sync → batch-pushes today's rows to Supabase
```

### Layer 3: Supabase (auto via REST)

```
Real-time (during session):
  store_scan_log() → SQLite write → background thread → POST /rest/v1/scan_log
  store_decision() → SQLite write → background thread → POST /rest/v1/decisions
  store_outcome()  → SQLite write → background thread → POST /rest/v1/outcomes

EOD batch (4:20pm ET):
  _sync_sqlite_to_supabase() in eod_update.py → batch POST for the full day

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
| id | int | Auto PK |
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

---

### `outcomes`
Every exit — P&L record for each closed trade.

| Column | Type | Description |
|---|---|---|
| id | int | Auto PK |
| decision_id | int | FK → decisions.id |
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

---

### `daily_wr`
Current win rate per ticker per direction, recomputed nightly.

| Column | Type | Description |
|---|---|---|
| ticker | text | Ticker |
| direction | text | YES or NO |
| win_rate | real | Historical WR |
| observations | int | Sample size |
| updated_at | text | Last update |

**Written by:** `eod_update.py` nightly. **Read by:** `engine/state.py` at Railway startup.

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

**Rows:** ~66,500 (Oct 2025 → present) | **Built by:** `tools/extend_2min_data.py`

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
Logistic regression: input (tbf_min, yes_vwap, gfr) → P(YES settles). AUC 0.81.
**Built by:** `tools/train_settlement_model.py` | **Used by:** `engine/session.py` (deployed to Railway).

---

## What NOT to Do

| Don't | Because |
|---|---|
| Write scan_log from local tools | scan_log is live session data only — backfill via `/api/admin/sync-supabase` |
| Run eod_update.py on Railway manually | It runs automatically at 4:20pm ET via cron |
| Use full_session_analysis.py | Replaced by extend_2min_data.py |
| Use scrape_history.py or backfill_from_parquet.py | One-time historical scripts, already run |
| Modify full_session_2min.csv directly | Always go through extend_2min_data.py |

---

## Known Data Integrity Issues

| Issue | Impact | Status |
|---|---|---|
| Supabase psycopg2 / pooler broken | Resolved — REST API path implemented | Fixed |
| May 26 scan_log: 0 rows | Railway didn't start cleanly | Lost |
| May 28 scan_log: only 9:31–10:51 ET | Redeployed mid-session | Partially lost |
| May 27–28 scan_log not in Supabase | Pre-dates REST fix | Backfill via `/api/admin/sync-supabase` |
| full_session_2min.csv gap May 2–26 | Fixed 2026-05-28 via extend_2min_data.py | Fixed |
| wr_cache stale until Railway restart | adj_wr uses yesterday's WR priors intraday | Known, low priority |
