# Polymarket Gap Mispricing Bot — Active TODO

**Strategy:** Exploit Polymarket's daily stock binary markets. Market prices YES at ~50-57¢ regardless of gap size. Actual close win rates range 17–76% depending on gap direction and size. Edge: +5-19% per trade.

**Status:** Paper trading ready. Data pipeline complete. Server with crash recovery live.

---

## Paper Trading — Active (May 2026)

### Pre-session setup
- [x] Run `python -c "from database.wr_store import daily_update; daily_update()"` — win rates refreshed (120–137 obs per ticker, adj_wr 0.67–0.73)
- [x] Install launchd plists — both `com.polymarket.server` and `com.polymarket.eod_update` registered and running
- [x] `data/settlement_model.pkl` exists — AUC 0.8095, Brier 0.1654 (retrained on 57,313 rows, full clean dataset)
- [x] Smoke test passed — server starts clean, 9 markets discovered, 9/9 gaps computed

### During paper trading (accumulating data)
- [ ] Monitor each session: check `localhost:8001` for live signals and open positions
- [ ] After 4:20pm each weekday: EOD pipeline runs automatically via launchd (logs to `logs/eod_update.log`)
- [ ] Run `tools/oos_validation.py` monthly once 30+ new sessions have accumulated

---

## Railway + Supabase Migration (required — Mac can't stay on during market hours)

**Why this is blocking:** launchd crash recovery only works if the Mac is on. Railway hosts `server.py` 24/7 on a remote VM. Supabase replaces the local SQLite files that Railway's ephemeral filesystem would wipe on every redeploy.

### Phase 1 — Supabase (DB migration)
- [x] Create Supabase project (id: dftkwvdhwkbtjxutgqzy, us-west-1, free tier)
- [x] Apply schema via MCP (8 tables, PostgreSQL DDL)
- [x] Migrate all historical data: isolated_priors (18), daily_wr (18), scraped_observations (1355), stock_daily_obs (11295), live_quotes (9) — row counts verified
- [x] Rewrite `database/db.py`: `DATABASE_URL` env var selects psycopg2 (PG) or sqlite3 (local). `_PgConn` wrapper translates `?`→`%s`, handles RETURNING id, ON CONFLICT upserts.
- [x] Fix `database/wr_store.py`: `INSERT OR IGNORE` → ON CONFLICT DO NOTHING, PRAGMA → information_schema for PG
- [x] Add `psycopg2-binary` to requirements.txt; update .env.example with DATABASE_URL
- [ ] **YOU:** Get Supabase DB password from dashboard (Settings → Database → Connection string) → add to local `.env` as `DATABASE_URL=postgresql://postgres:[password]@db.dftkwvdhwkbtjxutgqzy.supabase.co:5432/postgres`
- [ ] **YOU:** Test locally: `DATABASE_URL=postgresql://...` python -c "from database.db import init_db, total_stats; init_db(); print(total_stats())"

### Phase 2 — Railway (server deploy)
- [ ] Commit model artifacts to git: `data/settlement_model.pkl`, `data/exit_model_calibration.csv` (currently gitignored but needed at startup)
- [x] Change `server.py` port → `int(os.environ.get("PORT", 8001))` (avoids local conflict with Hermes port 8000)
- [ ] Add `railway.toml` with start command: `python server.py`
- [ ] Set Railway env vars: `DATABASE_URL`, `TWELVEDATA_API_KEY`, `CLOB_API_KEY`, `GAMMA_API` (and all others from `.env`)
- [ ] Deploy and confirm startup log shows "Server ready" with 9 markets discovered
- [ ] Remove `deploy/com.polymarket.server.plist` from active launchd (Railway takes over crash recovery)

### Phase 3 — EOD cron on Railway
- [ ] Add second Railway service (cron) running `python tools/eod_pipeline.py`
- [ ] Schedule: `0 21 * * 1-5` (4:20pm ET = 21:20 UTC, Mon–Fri)
- [ ] Verify cron has access to same `DATABASE_URL` and writes back to Supabase correctly
- [ ] Keep `com.polymarket.eod_update.plist` as local fallback until Railway cron confirmed working

---

## Near-Term Improvements (next 2 weeks)

- [x] **Extract `compute_position_size()` from `config.py`** — moved to `engine/sizer.py`. All three import sites updated.

- [ ] **Sector correlation cap** — max 1 position per sector group prevents 4 simultaneous tech-long positions. Tech group: NVDA/TSLA/AAPL/META/MSFT/GOOGL/NFLX. Pure risk management, no edge assumption needed.

- [ ] **Better NO entry signal** — current 3-of-4 heuristic for NO trades uses GFR as GO signal but data shows p1 ≈ p0 (not informative). Candidates: pre-market volume, sector breadth, VIX spike direction. Do NOT implement until LR > 1.3 confirmed in data.

---

## Medium-Term (next month, data-dependent)

- [ ] **Ticker-specific calibration sub-tables** — SPX token dynamics differ from TSLA. Check if per-ticker cell density ≥ 30 after splitting. Fall back to pooled for sparse cells.

- [ ] **CLOB exit discount calibration** — hardcoded `CLOB_EXIT_DISCOUNT = 0.05` is a guess. Track estimated vs actual exit price from paper trades. Derive empirical discount per ticker/time/spread bucket.

- [ ] **90¢ reverse NO bet module** — after 1pm, if YES token ≥ 90¢ AND GFR flat/fading AND settlement_prob < 0.88 → enter NO. Only after fully exiting YES. Needs separate entry/exit tracking.

- [ ] **Gap size segmentation in calibration table** — add gap bucket dimension (small: 0.5–2%, large: ≥2%). A 0.7% gap with GFR=0 at 11:30am is very different from a 3.0% gap with GFR=0.

- [ ] **Intraday flat-open entry signal** — test: if gap < 0.3% at open but stock moves >0.8% from open by 10:30am, is Polymarket still anchored near 50¢? Only add if confirmed in `full_session_2min.csv`.

---

## Data Gaps (non-blocking)

| Gap | Impact | Fix |
|-----|--------|-----|
| ~~GFR missing Oct 2025 → Feb 2026~~ | ~~Exit model less accurate~~ | Solved — Twelve Data backfill, AUC 0.683 → 0.8095 |
| OOS validation only 22 days | Can't confirm edge persistence | Re-run monthly as paper trades accumulate |
| Backtest tools use flat 0.5% threshold | Overstated edge on high-beta tickers | Update `tools/backtest_may20.py` to use `TICKER_GAP_THRESHOLD` |

---

## Live Trading Checklist (before going live — not yet)

All must be true before spending real capital:

**Wallet / On-chain:**
- [ ] MATIC balance ≥ $2 equivalent (Polygon gas)
- [ ] USDC balance matches intended max exposure
- [ ] CLOB contract `approve()` called (USDC allowance set)
- [ ] Bot wallet is dedicated address (not personal funds)
- [ ] Private key only in `.env`, not in any log

**Execution:**
- [ ] WebSocket reconnect: first tick discarded (stale snapshot)
- [ ] 429 retry with exponential backoff
- [ ] Nonce serialization — single async queue for order submission
- [ ] Sub-minimum check before partial exits
- [ ] GFR/trail-stop exits: widen limit when last WS tick > 2s old
- [ ] MATIC balance monitoring with alert

**Dry-run validation:**
- [ ] Run full week with $0 wallet balance
- [ ] All NSF rejection reasons logged (each is a signal the backtest ignores)
- [ ] Backtest vs paper trade gap < 5% before sizing up

---

## Deferred (after 1+ months of paper trading)

- Supabase migration (replace SQLite → PostgreSQL for remote access)
- Polygon.io historical intraday data (fill GFR gap for Oct 2025–Feb 2026)
- Correlation hedge (reduce position when multiple tickers signal same direction)
- Per-ticker CLOB execution analysis (fill rate, slippage, repricing frequency)
