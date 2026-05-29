# Polymarket Gap Mispricing Bot — Active TODO

**Strategy:** Exploit Polymarket's daily stock binary markets. Market prices YES at ~50-57¢ regardless of gap size. Actual close win rates range 17–76% depending on gap direction and size. Edge: +5-19% per trade.

**Status:** Paper trading live on Railway + Supabase as of May 26 2026. Mac not required during market hours.

---

## Known Risks — Address Before Live Trading

### P0 — Fixed
- [x] `scipy` missing from requirements.txt → Kelly used point estimates instead of 90% CI lower bound. **Fixed May 26.**
- [x] Algorithm v2 deployed 2026-05-29: model-driven direction, new features (stock_pct_vs_prevclose + momentum_30min), SPRT/3-of-4 removed, per-side settlement exit, per-ticker gap threshold wired.

### P1 — Fix Before November
- [ ] **DST hardcode** — `ET_OFFSET_H = -4` in `engine/strategy.py` and `timedelta(hours=-4)` in `tools/eod_update.py`. Works for EDT (Mar–Nov). In EST (Nov–Mar), strategy clock runs 1 hour ahead: misses 9:30–10:30 AM entries, exits 1 hour late. Fix: use `pytz` or `zoneinfo` to derive offset dynamically.

### P2 — Operational (non-blocking)
- [ ] **No daily server restart** — `state.wr_cache` is loaded once at Railway startup and never refreshed. After EOD cron updates `daily_wr` in Supabase, the running server won't see it until next restart. Fix: add a Railway scheduled restart at 9:20 AM ET daily, or reload WR cache at start of each trading day inside `trading_session_loop`.
- [ ] **Synthetic bid in REST fallback** — `periodic_rest_poll()` uses `p * 0.95` as a synthetic bid when WS hasn't provided real depth. Hardcodes a 5% spread. Real spread can be 10–20% in thin markets. Fix: use `(bid + ask) / 2` from the REST `/book` endpoint instead.
- [ ] **`_ensure_obs_table()` DDL** — `INTEGER PRIMARY KEY AUTOINCREMENT` is SQLite-only syntax. Harmless since the table already exists in Supabase (`IF NOT EXISTS` skips it), but would fail if the PG schema were ever recreated. Fix: add PG branch same as `rebuild_priors()`.

---

## Paper Trading — Active (May 2026)

### Pre-session setup
- [x] Run `python -c "from database.wr_store import daily_update; daily_update()"` — win rates refreshed (120–137 obs per ticker, adj_wr 0.67–0.73)
- [x] `data/settlement_model.pkl` exists — **v2 model retrained 2026-05-29**: AUC 0.70 OOS (vs old 0.47 on same holdout), features: stock_pos + momentum + log_tbf + yes_vwap + dow_thu
- [x] Server running on Railway — `polymarket-gap-bot-production.up.railway.app`
- [x] EOD cron running on Railway — fires at 4:20 PM ET weekdays

### During paper trading (accumulating data)
- [ ] Monitor each session: check dashboard at `polymarket-gap-bot-production.up.railway.app`
- [ ] After 4:20pm each weekday: EOD cron runs automatically on Railway (logs to Railway deploy logs)
- [ ] Run `tools/oos_validation.py` monthly once 30+ new sessions have accumulated

---

## Railway + Supabase Migration — Complete

### Phase 1 — Supabase (DB migration) ✓
- [x] Create Supabase project (id: dftkwvdhwkbtjxutgqzy, us-west-1, free tier)
- [x] Apply schema via MCP (8 tables, PostgreSQL DDL)
- [x] Migrate all historical data: isolated_priors (18), daily_wr (18), scraped_observations (1355), stock_daily_obs (11295), live_quotes (9)
- [x] Rewrite `database/db.py`: dual SQLite/PostgreSQL backend with `_PgConn` wrapper
- [x] Fix `database/wr_store.py`: PG-compatible SQL throughout
- [x] Add `psycopg2-binary` to requirements.txt; update .env.example

### Phase 2 — Railway server ✓
- [x] `railway.toml` with `python server.py` start command, `on_failure` restart policy
- [x] `data/settlement_model.pkl` + `data/exit_model_calibration.csv` committed to git
- [x] GitHub repo: `https://github.com/jayzhuang1996/polymarket-gap-bot`
- [x] Railway service deployed and Active — 9 markets discovered, all 9 gaps computed
- [x] Dashboard exposed at `polymarket-gap-bot-production.up.railway.app`

### Phase 3 — EOD cron on Railway ✓
- [x] Railway cron service: `python tools/eod_update.py` at `20 21 * * 1-5` (UTC)
- [x] Fix `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING` in `eod_update.py` for PG
- [x] Add `holidays` + `pyarrow` to requirements.txt
- [ ] Verify first cron run fires tonight (May 26) — check Railway cron deploy logs after 4:20 PM ET
- [ ] Confirm `scraped_observations` row count +9 in Supabase after first run
- [ ] Unload `com.polymarket.eod_update.plist` from local launchd once Railway cron confirmed working

**Note:** Steps 2–4 of `eod_pipeline.py` (model retraining) stay local. Railway filesystem is ephemeral — parquet trade history files don't persist across deploys. Run monthly from Mac after 30+ new sessions.

---

## Near-Term Improvements (next 2 weeks)

- [x] **Extract `compute_position_size()` from `config.py`** — moved to `engine/sizer.py`.
- [x] **Fast-entry path (FAST tag)** — 2 consecutive GO signals + live_edge ≥ 20% bypasses 3-of-4 wait. Tagged "FAST" in DB.
- [x] **Tiered entry edge floors** — 5% (9:35–10:30) / 8% (10:30–12:00) / 15% (12:00–13:30) / 20% (13:30–14:00) / freeze at 14:00. Replaces flat 12:00pm freeze and flat 8% floor.
- [x] **VIX 30-min refresh** — re-fetched every 15 × 2-min ticks during market hours. Catches mid-morning VIX spikes.
- [x] **Intraday reversal NO trades** — gap-UP day + GFR < −1.0 triggers `_check_reversal_entry()`. Bypasses signal history; GFR crossing is own trigger. Historical: 338 events, 67.2% NO WR, +14.8% edge. Calibrated REVERSAL_NO_WR per ticker in `config.py`.
- [x] **Better NO entry signal** — addressed by reversal path above. GFR < −1.0 is the data-driven trigger for NO entries on gap-UP days (historical NO WR 59–85% by ticker).
- [ ] **Sector correlation cap** — max 1 position per sector group prevents 4 simultaneous tech-long positions. Tech group: NVDA/TSLA/AAPL/META/MSFT/GOOGL/NFLX.

---

## Medium-Term (data-dependent)

- [ ] **Monthly model retraining workflow** — after 30+ sessions: run `eod_pipeline.py` locally (steps 2-4), commit updated `settlement_model.pkl` + `exit_model_calibration.csv`, push → Railway auto-deploys with fresh models.
- [ ] **Ticker-specific calibration sub-tables** — check per-ticker cell density ≥ 30 after splitting.
- [ ] **CLOB exit discount calibration** — hardcoded `CLOB_EXIT_DISCOUNT = 0.05` is a guess. Track estimated vs actual exit price from paper trades.
- [ ] **REVERSAL_NO_WR recalibration** — current values from 338 historical events (Oct 2025–May 2026). Recalibrate after 50+ live reversal trades accumulate per ticker from paper/live runs.
- [ ] **90¢ reverse NO bet module** — distinct from REVERSAL path. Targets gap-DOWN days where YES ran to 90¢+ (settlement near-certain) then fades. After 1pm, if YES ≥ 90¢ AND GFR flat/fading AND settlement_prob < 0.88 → enter NO at ~10¢.
- [ ] **Gap size segmentation in calibration table** — add gap bucket dimension (small: 0.5–2%, large: ≥2%).
- [ ] **Daily WR cache refresh** — reload `wr_cache` at start of each trading day in `trading_session_loop` so updated Supabase values are used without a server restart.

---

## Data Gaps

| Gap | Impact | Fix |
|-----|--------|-----|
| ~~GFR missing Oct 2025 → Feb 2026~~ | ~~Exit model less accurate~~ | Solved — Twelve Data backfill |
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
- [ ] Private key only in `.env` and Railway env vars, not in any log

**Execution:**
- [ ] WebSocket reconnect: first tick discarded (stale snapshot)
- [ ] 429 retry with exponential backoff
- [ ] Nonce serialization — single async queue for order submission
- [ ] Sub-minimum check before partial exits
- [ ] GFR/trail-stop exits: widen limit when last WS tick > 2s old
- [ ] MATIC balance monitoring with alert

**Dry-run validation:**
- [ ] Run full week with $0 wallet balance
- [ ] All NSF rejection reasons logged
- [ ] Backtest vs paper trade gap < 5% before sizing up
- [ ] DST fix deployed (see P1 above)

---

## Deferred

- Per-ticker CLOB execution analysis (fill rate, slippage, repricing frequency)
- Polygon.io historical intraday data (for future GFR backfills)
- Correlation hedge (reduce position when multiple tickers signal same direction)
