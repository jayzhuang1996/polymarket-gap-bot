# Polymarket Gap Mispricing Bot — Active TODO

**Strategy:** Exploit Polymarket's daily stock binary markets. Market prices YES at ~50-57¢ regardless of gap size. Actual close win rates range 17–76% depending on gap direction and size. Edge: +5-19% per trade.

**Status:** Paper trading live on Railway + Supabase as of May 26 2026. Mac not required during market hours.

---

## Known Risks — Address Before Live Trading

### P0 — Fixed
- [x] `scipy` missing from requirements.txt → Kelly used point estimates instead of 90% CI lower bound. **Fixed May 26.**
- [x] Algorithm v2 deployed 2026-05-29: model-driven direction, new features (stock_pct_vs_prevclose + momentum_30min), SPRT/3-of-4 removed, per-side settlement exit, per-ticker gap threshold wired.
- [x] Settlement model v3 retrained 2026-05-31: 8 features (gfr, gfr_velocity, log_tbf, gap_abs, market_p_win, dow_thu, vix_high, stock_pct_vs_prevclose), C=0.1 regularization, AUC 0.764 IS / 0.591 OOS. Feature mismatch bug fixed — old model was silently disabled in production (dimension error on every 5s tick). sklearn version pinned via .venv/bin/python for all training.
- [x] AMZN exit silent failure fixed 2026-05-31: hard_3pm exit now fires even when current_bid is None/0, falling back to entry_price so position closes at breakeven rather than staying open indefinitely.

### P1 — Fix Before November
- [x] **DST hardcode** — Fixed 2026-05-29. `engine/strategy.py` and `tools/eod_update.py` now use `zoneinfo.ZoneInfo("America/New_York")` with `timedelta(hours=-4)` as fallback (Python < 3.9). `ET_OFFSET_H = -4` kept as fallback constant only.

### P2 — Operational (non-blocking)
- [x] **No daily server restart** — Fixed 2026-05-31. `trading_session_loop()` daily reset block now calls `load_base_wr()` for every ticker and updates `state.wr_cache` immediately after VIX reload. No Railway restart needed.
- [x] **Synthetic bid in REST fallback** — Fixed 2026-05-29. `initial_rest_fallback()` and `periodic_rest_poll()` now call `GET /price?side=BUY` for real bid alongside the existing SELL call. Falls back to `p * 0.95` only if the BUY call fails.
- [x] **`_ensure_obs_table()` DDL** — Fixed 2026-05-31. Removed `AUTOINCREMENT` from `tools/eod_update.py` and `tools/scrape_history.py`. Both now use `INTEGER PRIMARY KEY` which is portable across SQLite and PostgreSQL.

---

## Paper Trading — Active (May 2026)

### Pre-session setup
- [x] Run `python -c "from database.wr_store import daily_update; daily_update()"` — win rates refreshed (120–137 obs per ticker, adj_wr 0.67–0.73)
- [x] `data/settlement_model.pkl` exists — **v3 model retrained 2026-05-31**: AUC 0.764 IS / 0.591 OOS, 8 features. Feature mismatch bug fixed; model now active in production.
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
- [x] Verified Railway cron fires at 4:20 PM ET — confirmed 2026-05-29
- [x] `scraped_observations` and `daily_wr` now mirrored to Supabase nightly
- [x] Mac launchd crons loaded: eod_update (1:20pm PT), scan, resolve — confirmed 2026-05-29

### Phase 4 — Mac EOD automation ✓
- [x] `eod_pipeline.py` rewritten: 5-step pipeline (scrape → extend → calibrate → retrain → git deploy)
- [x] Auto-backfill: detects up to 5 missed trading days via `scraped_observations` gaps + NYSE calendar
- [x] Auto-deploy: `git push origin main` in step 5 — Railway picks up updated pkl automatically
- [x] `daily_wr` added to Supabase mirror (upsert on `ticker+direction+gap_bucket`)
- [x] `scraped_observations` added to Supabase mirror (upsert on `date+ticker`)
- [x] Supabase schema: `daily_wr` unique constraint updated to `(ticker, direction, gap_bucket)`
- [x] NO trade position_size bug fixed: sizer now receives `1 − settlement_p` for NO side
- [x] Duplicate Supabase row bug fixed: `id` now included in REST payload for decisions + outcomes

**Note:** Model retraining is now daily (not monthly). Railway filesystem is ephemeral — parquet files stay local. Mac cron handles everything; no manual steps needed unless Mac was asleep (run `eod_pipeline.py` once to backfill).

---

## Near-Term Improvements (next 2 weeks)

- [x] **Extract `compute_position_size()` from `config.py`** — moved to `engine/sizer.py`.
- [x] **Fast-entry path (FAST tag)** — 2 consecutive GO signals + live_edge ≥ 20% bypasses 3-of-4 wait. Tagged "FAST" in DB.
- [x] **Tiered entry edge floors** — 5% (9:35–10:30) / 8% (10:30–12:00) / 15% (12:00–13:30) / 20% (13:30–14:00) / freeze at 14:00. Replaces flat 12:00pm freeze and flat 8% floor.
- [x] **VIX 30-min refresh** — re-fetched every 15 × 2-min ticks during market hours. Catches mid-morning VIX spikes.
- [x] **Intraday reversal NO trades** — gap-UP day + GFR < −1.0 triggers `_check_reversal_entry()`. Bypasses signal history; GFR crossing is own trigger. Historical: 338 events, 67.2% NO WR, +14.8% edge. Calibrated REVERSAL_NO_WR per ticker in `config.py`.
- [x] **Better NO entry signal** — addressed by reversal path above. GFR < −1.0 is the data-driven trigger for NO entries on gap-UP days (historical NO WR 59–85% by ticker).
- [ ] **Model-vs-gap direction agreement analysis** — v2 model can flip YES/NO relative to overnight gap. Edge estimates in STRATEGY_EXPLANATION.md Section 2 are from gap-direction base rates. We have never measured: (a) edge when model AGREES with gap direction, (b) edge when model DISAGREES. Run `tools/oos_validation.py`-style split on `full_session_2min.csv`: for sessions in the holdout period, tag each 2-min row by model_direction == gap_direction or not, compute WR per group. If model-disagrees edge is negative, the v2 entry path is losing money on a subset of trades with no current detection mechanism.
- [ ] **Sector correlation cap** — max 1 position per sector group prevents 4 simultaneous tech-long positions. Tech group: NVDA/TSLA/AAPL/META/MSFT/GOOGL/NFLX.

---

## Medium-Term (data-dependent)

- [x] **Daily model retraining workflow** — `eod_pipeline.py` runs nightly via Mac cron (1:20pm PT). Auto-backfills missed days, retrains models, git-pushes to Railway. No manual steps needed.
- [ ] **Ticker-specific calibration sub-tables** — check per-ticker cell density ≥ 30 after splitting.
- [ ] **CLOB exit discount calibration** — hardcoded `CLOB_EXIT_DISCOUNT = 0.05` is a guess. Track estimated vs actual exit price from paper trades.
- [ ] **REVERSAL_NO_WR recalibration** — current values from 338 historical events (Oct 2025–May 2026). Recalibrate after 50+ live reversal trades accumulate per ticker from paper/live runs.
- [ ] **90¢ reverse NO bet module** — distinct from REVERSAL path. Targets gap-DOWN days where YES ran to 90¢+ (settlement near-certain) then fades. After 1pm, if YES ≥ 90¢ AND GFR flat/fading AND settlement_prob < 0.88 → enter NO at ~10¢.
- [ ] **Gap size segmentation in calibration table** — add gap bucket dimension (small: 0.5–2%, large: ≥2%).
- [x] **Daily WR cache refresh** — Fixed 2026-05-31. See P2 fix above.

---

## Data Gaps

| Gap | Impact | Fix |
|-----|--------|-----|
| ~~GFR missing Oct 2025 → Feb 2026~~ | ~~Exit model less accurate~~ | Solved — Twelve Data backfill |
| OOS validation only 22 days | Can't confirm edge persistence | Re-run monthly as paper trades accumulate |
| Backtest tools use flat 0.5% threshold | Overstated edge on high-beta tickers | Update `tools/backtest_may20.py` to use `TICKER_GAP_THRESHOLD` |
| `stock_daily_obs` stale (last entry 2026-05-22) | Different table from `scraped_observations`; populated by a separate pipeline step not running | Low priority — does not affect live trading or model training |

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
