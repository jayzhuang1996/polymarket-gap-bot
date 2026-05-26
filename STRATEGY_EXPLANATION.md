# Strategy: Polymarket Gap Mispricing — Full Algorithm Reference

---

## 0. What This Strategy Actually Does (Plain English)

Every morning, stocks open at a different price than where they closed the day before. This overnight jump is called the **gap**. A stock that closed at $100 and opens at $102 has "gapped up" by 2%.

On Polymarket, there are daily binary markets that ask: "Will this stock close *above* yesterday's close today?" The answer pays $1 if YES, $0 if NO. You can buy either side.

**The mispricing:** Retail Polymarket traders price these tokens at roughly 50–57¢ regardless of gap size. But the actual historical close rate for a stock that gapped up 2%+ is about 76%. At a 57¢ buy price, you're getting a 76% chance at $1 for 57¢ in — that's a 19¢ structural edge per trade.

**Why it persists:** Polymarket's order book has no automated market maker that reprices based on outside data. Prices only move when someone manually trades. Retail flow is directionally biased and not statistically calibrated to gap size.

**The strategy in one sentence:** Every trading day, find overnight gaps above our threshold, confirm the gap is holding intraday, buy the token for the direction the gap predicts, and exit before 3pm before late-session randomness erodes the edge.

---

## 1. Full Algorithm Flowchart

Read this top to bottom. Each level of indentation is a decision or action. `→` means "proceed." `STOP` means the ticker is skipped for that day or that cycle.

```
╔══════════════════════════════════════════════════════════════════╗
║  SERVER STARTUP (runs once before 9:30am ET)                     ║
╚══════════════════════════════════════════════════════════════════╝

1. Initialize DB (create tables if new, run column migrations if upgrading)
2. Discover Polymarket markets for all 9 tickers via Gamma API
3. Calculate overnight gaps from yfinance OHLC
4. Load Bayesian win rates (isolated_priors + daily_wr blend) into memory
5. Reconcile session state from DB
   → If server crashed mid-session (e.g., 11am), this restores open positions
   → Reads today's unresolved decisions, re-fills _session_entered / _decision_ids
   → Prevents double-entry after a restart


╔══════════════════════════════════════════════════════════════════╗
║  PRE-SESSION SETUP (before 9:35am ET, at startup)               ║
╚══════════════════════════════════════════════════════════════════╝

For every ticker (SPX, NVDA, TSLA, AAPL, AMZN, GOOGL, META, MSFT, NFLX):
│
├─ STEP 1: CALCULATE THE OVERNIGHT GAP
│     gap_pct = (today's open − yesterday's close) / yesterday's close
│     Example: closed at $100, opened at $102 → gap_pct = +2.0%
│     [gap_bps = gap in basis points; 200 bps = 2%]
│
├─ STEP 2: FIND THE POLYMARKET MARKET
│     Query Gamma API for "Will SPX close up or down on May 24 2025?"
│     Retrieve YES token ID and NO token ID.
│     No market found → STOP this ticker today.
│
├─ STEP 3: FETCH VIX CHANGE (once per day)
│     VIX = market fear index. vix_change = VIX open − yesterday's VIX close
│     Declining VIX → bullish conditions (lower edge threshold for YES)
│     Rising VIX → fear regime (higher edge threshold for YES)
│
└─ STEP 4: LOAD WIN RATES
      adj_wr = Bayesian blend: (isolated_prior × 50 + daily_wr × N) / (50 + N)
      With N < 30 live observations, the 5-year prior dominates entirely.
      With N = 80, live Polymarket data carries 62% of the weight.


╔══════════════════════════════════════════════════════════════════╗
║  ENTRY DECISION (every 2 minutes, 9:35am → 12:00pm ET)          ║
╚══════════════════════════════════════════════════════════════════╝

Every 2 minutes, for each ticker:
│
├─ UPDATE GFR (Gap Fill Ratio)
│     GFR = (current_price − open_price) / (open_price − yesterday's close)
│
│     GFR = +1.0 → stock moved further in gap direction (gap accelerating)
│     GFR =  0.0 → stock sitting at open (gap unchanged)
│     GFR = -0.5 → stock moved 50% back toward yesterday's close
│     GFR = -1.0 → gap fully erased
│     GFR = -1.5 → stock is past yesterday's close (gap fully reversed)
│
│     Example: Opened at $102 (gap up from $100). Now at $101.
│       GFR = (101 − 102) / (102 − 100) = −0.5
│       → Gap 50% filled. Not great for a YES bet.
│
├─ GATE 1: GAP ABOVE BETA-SCALED THRESHOLD?
│     SPX (β=1.0) → needs >0.50%   TSLA (β=2.0) → needs >1.00%
│     NFLX override → 1.50% (data quality too thin below this)
│     Gap too small? → STOP.
│
├─ GATE 2: BEFORE ENTRY FREEZE?
│     No new entries after 12:00pm ET.
│     After noon → STOP checking entries.
│
├─ GATE 3: INTRADAY SIGNAL?
│     GO   → live edge ≥3% AND GFR not reversed
│     WATCH → edge positive but < 3%
│     FADE  → GFR < −0.3 (gap reversed 30%+)
│     SKIP  → edge negative
│     FADE or SKIP → STOP this cycle, retry in 2 minutes.
│
├─ GATE 4: CONVICTION CHECK
│     AMZN/TSLA YES trades → SPRT (Sequential Probability Ratio Test)
│       Each GO signal multiplies LR by (p1/p0). Each non-GO by (1-p1)/(1-p0).
│       LR ≥ 5.0 → evidence strong, ENTER. LR ≤ 0.2 → gap fading, ABORT for day.
│       SPRT abort is permanent for the day — no retry.
│     All other trades → 3-of-4: need 3+ GO signals in last 4 two-minute checks.
│
├─ GATE 5: GFR ENTRY GATE FOR NO TRADES
│     NO trades bet the gap reverses. Enter while gap is still intact.
│     GFR < −0.3 at entry → STOP. Stock already bounced 30%+ back.
│     Historical data: filtered WR = 83.6% (n=128) vs 60.9% when GFR already < −0.3.
│
├─ GATE 6: EDGE AND VIX REGIME
│     adj_wr = base_wr + 0.15 × GFR × direction_sign  [real-time GFR adjustment]
│     edge = adj_wr × 0.99 − current_ask_price
│     [0.99 accounts for Polymarket's 1% settlement fee]
│
│     Minimum edge required:
│       Thursday or Friday              → ≥10% (historically weaker for gap bets)
│       After 10:30am                   → ≥8%  (less ladder time)
│       VIX in bullish zone [−2, −0.5] → subtract 2% from threshold
│       VIX rising (>+0.5), YES trade  → add 3% to threshold
│       Standard (before 10:30am)      → ≥3%
│
├─ GATE 7: PRICE AND SPREAD
│     Token price: $0.40–$0.70.
│       Below $0.40 → market says you're probably wrong.
│       Above $0.70 → not enough profit potential.
│     Spread: ≤15% standard, ≤10% after 10:30am.
│
├─ GATE 8: PORTFOLIO LIMITS
│     Already 6 open positions? → STOP.
│     Daily loss already hit $500? → STOP ALL TRADING today.
│
└─ POSITION SIZING (Quarter-Kelly with CI safety)
      Kelly sizes on the 90% confidence interval LOWER BOUND of win_rate.
      With n=20 observations at 70% WR, lower bound ≈ 54% → size as if WR=54%.
      As data accumulates and CI tightens, Kelly scales up naturally.
      Cap: $100 per position. Minimum: $20 (skip below this).

      Entry logged to DB: ticker, entry_price, entry_side, position_size,
      expected_edge, adj_wr, gfr_at_entry, spread_at_entry.
      [gfr_at_entry and adj_wr stored at time of entry so we can audit later
       whether the edge estimate was accurate — Risk 2 fix from May 2026.]


╔══════════════════════════════════════════════════════════════════╗
║  LIMIT ORDER LIFECYCLE                                           ║
╚══════════════════════════════════════════════════════════════════╝

After placing the buy order:
│
├─ FILLED → open position, switch to exit monitoring
└─ NOT FILLED (order expired after 2 minutes):
    All four must be true to reprice:
    - Entry window still open (before noon)
    - Signal still GO
    - New price still $0.40–$0.70
    - Reprice count < 3
    → CANCEL old order, place new order at updated price.
    → Any condition fails: ABANDON, allow fresh entry next cycle.


╔══════════════════════════════════════════════════════════════════╗
║  EXIT DECISION (every 2 minutes while holding a position)       ║
╚══════════════════════════════════════════════════════════════════╝

Check in priority order. First matching condition fires. Each trigger fires once per session.

├─ LEVEL 1 — HARD TIME EXIT (3:00pm ET)
│     SELL 100%, no exceptions.
│     After 3pm, MOC orders can swing markets unrelated to the gap thesis.
│
├─ LEVEL 2 — GFR REVERSAL EXIT (YES trades only)
│     Condition: GFR drops below −0.5
│     Action: SELL 100%
│     Historical WR for YES at GFR < −0.5: 18%. The bet is losing. Get out.
│     ⚠ NO trades: DISABLED. NO WR at GFR < −0.5 is still 43% — this is noise,
│     not a reversal. Exiting NO trades on GFR early costs more edge than it saves.
│
├─ LEVEL 3 — NO PROFIT LOCK (NO trades only)
│     Condition: NO token ≥ entry price + 12¢
│     Action: SELL 50%
│     Why: Choppy sessions oscillate. If the NO token runs up 12¢, capture half
│     immediately before the next bounce erases it. Keep the other half running.
│
├─ LEVEL 4 — NO TRAILING STOP (NO trades only)
│     Arms when: Session peak price ≥ entry + 10¢
│     Triggers when: Current price falls ≥ 8¢ from session peak
│     Action: SELL remaining 100%. After trail stop fires, ticker blocked from re-entry.
│     Example: Entered at 40¢. Token ran to 55¢. Falls to 46¢. 46¢ < 55¢ − 8¢ → EXIT.
│
├─ LEVEL 5 — SETTLEMENT MODEL EXIT
│     Logistic regression trained on 57,313 historical Polymarket sessions.
│     Inputs: GFR, GFR velocity (change over last 2 min), time to close, gap size,
│             Polymarket's own implied probability, day of week, VIX high flag.
│     Output: P(this trade wins at 4pm)
│
│     Exit when:
│       P(win) < 45% → SELL 100% (gap reversing hard, model says losing)
│       live_edge < 0 → SELL 80% (token now priced past model's fair value — edge extracted)
│
├─ LEVEL 6 — EDGE EXHAUSTION FALLBACK (when settlement_model.pkl missing)
│     Condition: position up ≥15% AND adj_wr × 0.99 ≤ current_token_price AND GFR < 0
│     Action: SELL 85%
│
└─ LEVEL 7 — TIERED TIME REVIEWS
      2:00pm → SELL unless token ≥85¢ AND GFR ≥+0.5
      2:30pm → SELL unless token ≥85¢ AND GFR ≥+0.2
      3:00pm → HARD EXIT ALL
      Why: 82–86% of gap fills that will happen have happened by 10:30am. Holding
      past 2pm only makes sense when the gap is clearly going to hold all day.


╔══════════════════════════════════════════════════════════════════╗
║  END OF SESSION (4:20pm ET, automated via launchd)              ║
╚══════════════════════════════════════════════════════════════════╝

eod_pipeline.py chains 4 steps:
  Step 1: eod_update.py — scrapes Polymarket resolutions, appends scraped_observations,
          calls daily_update() to rebuild daily_wr from all observations to date
  Step 2: full_session_analysis.py — rebuilds full_session_2min.csv (57,470 rows)
  Step 3: calibrate_exit_model.py — rebuilds exit model calibration table
  Step 4: train_settlement_model.py — retrains logistic regression

Pipeline aborts on Step 1 or 2 failure. Continues past Step 3/4 failure (model rebuilds
are non-critical; previous day's models remain active).
```

---

## 2. The Edge — What Makes This Work

Every trading day, stocks open above or below the prior close. Win rates by gap size:

| Gap Bucket | YES Win Rate | Avg YES Price | Edge (buy YES) |
|-----------|-------------|---------------|----------------|
| Gap-up >2% | 76% | ~57¢ | +19¢ |
| Gap-up 1–2% | 65% | ~56¢ | +9¢ |
| Gap-up 0.5–1% | 57% | ~55¢ | +2¢ (weak) |
| Near flat | 48–52% | ~54¢ | skip |
| Gap-down 0.5–1% | 41% YES WR | ~53¢ | buy NO (+6¢) |
| Gap-down 1–2% | 32% YES WR | ~52¢ | buy NO (+20¢) |
| Gap-down >2% | 17% YES WR | ~52¢ | buy NO (+35¢) |

Why it persists: Polymarket's CLOB has no algorithmic market maker that reprices on external data. Prices only move when someone trades. Retail flow is directionally biased, not statistically calibrated to gap size.

---

## 3. Entry Gates — Detailed Reference

### Gap threshold (Gate 1)

| Ticker | Beta | Threshold |
|--------|------|-----------|
| SPX | 1.0 | 0.50% |
| NVDA | 1.5 | 0.75% |
| TSLA | 2.0 | 1.00% |
| AAPL | 1.2 | 0.60% |
| AMZN | 1.3 | 0.65% |
| GOOGL | 1.1 | 0.55% |
| META | 1.4 | 0.70% |
| MSFT | 1.1 | 0.55% |
| NFLX | — | 1.50% (data-driven override) |

### Conviction system

**3-of-4 (all NO trades, most YES trades):** 3+ of last 4 two-minute checks must show GO.

**SPRT (AMZN/TSLA YES only):**

| Ticker | p1 (GO in winning trades) | p0 (GO in losing trades) | Enter at LR | Abort at LR |
|--------|--------------------------|--------------------------|-------------|-------------|
| AMZN | 0.43 | 0.28 | ≥5.0 | ≤0.2 |
| TSLA | 0.26 | 0.19 | ≥5.0 | ≤0.2 |

### VIX regime adjustment

`vix_change = today's VIX open − yesterday's VIX close` (fetched once at startup)

- `vix_change ∈ [−2.0, −0.5]` → subtract 2% from required edge for YES (88.4% historical WR zone, n=95)
- `vix_change > +0.5` → add 3% to required edge for YES entries
- `VIX close > 20` → `vix_high=1` feature injected into settlement model

---

## 4. Exit System — Detailed Reference

### GFR exits — direction-asymmetric

| GFR Level | YES Win Rate | YES Action | NO Action |
|-----------|-------------|------------|-----------|
| < −0.5 | 18% | SELL 100% | No exit — 43% WR, this is noise |

### NO trade intraday protection

| Mechanism | Trigger | Action | Arms when |
|-----------|---------|--------|-----------|
| Profit lock | Token ≥ entry + 12¢ | SELL 50% | Always |
| Trailing stop | Token ≤ peak − 8¢ | SELL remaining | Peak ≥ entry + 10¢ |

After trail stop fires: ticker added to session abort list. No re-entry that day.

### Exit model — gap size segmentation

```
Tier 1: (time, gfr, ALL, gap_bucket)    — gap-segmented, pooled [primary]
Tier 2: (time, gfr, day-of-week, ALL)   — day-specific, no gap dimension
Tier 3: (time, gfr, ALL, ALL)           — fully pooled
Tier 4: linear formula                   — final fallback

gap_bucket: "small" = 0.5–2%, "large" = ≥2%
```

GFR=0 at 10:30am means fundamentally different things at different gap sizes:
- Small gap (0.7%): GFR=0 → stock at open, halfway to close. Token ≈ 60¢.
- Large gap (3.0%): GFR=0 → entire 3-point gap erased. Token ≈ 36¢.

Without gap segmentation, the model gives both the same estimate — a 20¢+ error.

### Tiered time exits

```
2:00pm  → SELL unless token ≥85¢ AND GFR ≥+0.5
2:30pm  → SELL unless token ≥85¢ AND GFR ≥+0.2
3:00pm  → HARD EXIT ALL (no conditions)
```

---

## 5. Win Rate System

Win rates are Bayesian blends in `database/wr_store.py`:

- **isolated_priors:** Built from 5-year daily OHLC (pre-Feb 2026 data only — kept isolated from live observations to preserve independence). Worth PRIOR_WEIGHT=50 virtual observations.
- **daily_wr:** Computed from `scraped_observations` (1,355 resolved Polymarket markets, Oct 2025–present). Rebuilt nightly by `daily_update()`.
- **Blend:** `adj_wr = (isolated_prior × 50 + daily_wr × N) / (50 + N)`
  - MIN_OBS_FOR_DB_WR = 30: daily_wr ignored entirely if fewer than 30 observations exist for that (ticker, direction) pair.
- **Real-time adjustment:** `adj_wr += 0.15 × gfr × direction_sign`

Three model inputs stored at every entry (Risk 2 fix, May 2026): `adj_wr`, `gfr_at_entry`, `spread_at_entry`. This lets us audit post-session whether the edge estimate was accurate.

---

## 6. Out-of-Sample Validation

Run `tools/oos_validation.py` monthly. Method: compare in-sample WR (Oct 2025–Mar 2026) vs out-of-sample WR (Apr 2026 onward) across 36 cells (9 tickers × 4 gap buckets) with Wilson 95% CIs and Bonferroni correction (α = 0.00139 per cell).

As of May 2026: 27/36 cells have insufficient OOS data (<5 obs). The 4 cells with negative OOS edge all have ≤6 observations — consistent with noise. Re-run after 50+ new sessions.

---

## 8. Appendix — Jargon and Key Functions

### Terms

| Term | What it means | Scenario |
|------|---------------|----------|
| **Gap / gap_pct** | Overnight price jump as a percentage. Positive = opened above prior close, negative = gap down. | NVDA closed Friday at $100, opened Monday at $103 → gap_pct = +3%. Bot targets YES. |
| **gap_bps** | Same gap in basis points (1% = 100 bps). Used internally as an integer. | That +3% gap = +300 bps. NVDA entry threshold is 75 bps → passes Gate 1. |
| **GFR (Gap Fill Ratio)** | How much of the overnight gap has reversed intraday. 0=at open, -1=gap erased, +1=gap extended. Formula: `(current - open) / (open - prev_close)`. | NVDA opened $103 (gap +$3). By 11am it's $101.50 → GFR=(101.50-103)/(103-100)=-0.5. Half the gap filled. |
| **adj_wr** | The win rate the bot actually bets on — Bayesian blend of 5-year history and live Polymarket data, nudged by real-time GFR. | 5-year prior=72%, 137 real trades show 68.8% → blend lands at 68.8% adj_wr. |
| **isolated_priors** | Win rate from 5 years of daily OHLC stock data only. Kept separate from live Polymarket data to preserve independence. | "NVDA gapped up >1% on 200 days; closed up 144 times → prior WR = 72%." |
| **daily_wr** | Win rate from actual resolved Polymarket markets (Oct 2025-present). Only trusted once >=30 observations exist. | 87 NVDA gap-up trades, 60 won → daily_wr = 68.9%. Below 30 obs this number is ignored entirely. |
| **Bayesian blend** | Weighting prior and live WR by observations behind each. Prior treated as 50 virtual observations. | NVDA: (72%×50 + 68.8%×137)/(50+137) = 69.7%. With only 10 real trades, prior carries 83% weight. |
| **SPRT** | Evidence test that accumulates multiplicatively across 2-min checks. Score >=5.0 → enter; <=0.2 → abort ticker for the day. AMZN and TSLA YES only. | TSLA checks: GO, GO, no-GO, GO → score = 1.37×1.37×0.93×1.37 = 2.39. Still below 5.0 — keep watching. |
| **LR (Likelihood Ratio)** | The running SPRT score. Starts at 1.0, multiplies up on GO signals, down on non-GO. | AMZN p1=0.43, p0=0.28. Each GO multiplies by 1.54. Four consecutive GOs: 1.54^4 = 5.6 → enter. |
| **Quarter-Kelly** | 25% of the theoretically optimal bet size. Full Kelly is optimal long-run but causes brutal drawdowns. | Full Kelly says bet $400. Quarter-Kelly → $100 max. |
| **CI lower bound** | 90% confidence interval lower bound of win rate, used for sizing. Thin data means smaller bets automatically. | 20 obs at 70% WR → lower bound ~54% → $22 position. After 200 obs the bound tightens to 64% → $68. |
| **AUC-ROC** | How often the model ranks a winning trade above a losing one. 0.5=coin flip, 1.0=perfect. Current: 0.8095. | Given NVDA (will win) and AAPL (will lose) both in-flight, model assigns NVDA higher P(win) 81% of the time. |
| **Brier Score** | Mean squared error of probability estimates. 0.25=random, 0=perfect. Current: 0.1654. | Model says 70% P(win). Trade wins → Brier contribution = (0.70-1)^2 = 0.09. Averaged across all trades. |
| **CLOB** | Polymarket's order book. You place limit orders; they fill when a counterparty takes the other side. Thin book, retail-driven. | You submit "BUY 50 YES @ 0.52". Sits in book until someone sells at <=0.52. May not fill for minutes. |
| **VIX** | The S&P 500 fear index. Rising VIX = fear. Bot tightens entry thresholds on rising-VIX mornings. | VIX jumped +3 overnight. Required edge increases 5% → 8%. NVDA's 6.2% edge now fails the gate. |
| **tbf_min** | Minutes before 4pm ET close. 390=9:30am open, 120=2pm, 0=close. Feature in settlement model and exit ladder. | Trade entered at 10am: tbf_min=360. By 2pm: tbf_min=120. Model penalises low-tbf — little time to recover. |
| **live_edge** | Expected profit per dollar risked = `adj_wr × 0.99 - ask_price`. The 0.99 accounts for the 1% Polymarket fee. | adj_wr=0.69, ask=0.52 → live_edge = 0.69×0.99 - 0.52 = +0.163. You expect 16.3c profit per 52c risked. |
| **3-of-4 conviction** | Entry requires GO signal in >=3 of last 4 two-minute checks. Filters single noisy ticks. | Checks: GO, no-GO, GO, GO → 3/4 = enter. Checks: GO, no-GO, no-GO, GO → 2/4 = wait. |

---

### Key Functions

| Function | File | What it does |
|----------|------|--------------|
| `load_base_wr(ticker, gap_up)` | `database/wr_store.py` | Returns `(adj_wr, prior_wr, n_obs)`. Bayesian blend of 5-year prior + live Polymarket WR. Called at every trading decision. |
| `compute_position_size(win_rate, entry_price, n_obs)` | `engine/sizer.py` | Quarter-Kelly with 90% CI lower bound. Returns dollar size to buy, or 0.0 to skip. |
| `predict(gfr, gfr_velocity, tbf_min, ...)` | `engine/settlement_model.py` | Logistic regression returning `(p_win, live_edge)`. Used to trigger mid-session exits. AUC 0.8095. |
| `reconcile_session_state()` | `engine/session.py` | On server restart, reads today's unresolved DB decisions and rehydrates in-memory position state. Prevents double-entry after a crash. |
| `daily_update()` | `database/wr_store.py` | Recomputes `daily_wr` from all scraped_observations to date. Runs nightly via EOD pipeline. |
| `_compute_signal(...)` | `engine/strategy.py` | Runs all 8 entry gates and returns GO / WATCH / FADE / SKIP. The brain of the entry decision. |
| `calc_gaps()` | `engine/data_feed.py` | Fetches yfinance OHLC, computes `(gap_bps, today_open, prev_close)` per ticker. Called once at startup. |
| `discover_markets()` | `engine/data_feed.py` | Queries Polymarket Gamma API to find today's YES/NO token IDs for all 9 tickers. |
| `backfill_gfr(df, ticker, td_df, daily)` | `tools/backfill_gfr_twelvedata.py` | Fills null GFR values in `full_session_2min.csv` using Twelve Data 5-min bars. Run once to patch historical dark period (Oct 2025–Feb 2026). |

---

## 7. What We Explicitly Do Not Do

| | Reason |
|---|---|
| Hold to 4pm binary settlement | Late-day token decay kills edge even on winning positions |
| Market orders | Paying the spread on entry destroys thin edges |
| Trailing stops for YES trades | YES protection handled by GFR exit ladder — no overlap needed |
| Intraday ML direction prediction | Gap is a 64% directional predictor; no evidence ML improves on it at current data volumes |
| Trade markets with < 3 months history | Insufficient data for reliable edge estimation |
| Trade NFLX below 1.5% gap | Data quality too thin on Polymarket for NFLX at small gaps |
| Per-ticker GFR thresholds | Attempted May 2026 but reverted — first-trigger dedup gave n≈10/ticker. Revisit when ≥50 trigger events per ticker accumulate from live trading |
