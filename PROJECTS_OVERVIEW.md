# Trading Projects Overview

Four projects, one shared skill set. Updated May 20, 2026.

---

## Project 1: Finance Daily Markets (PRIMARY)

**Concept:** Trade daily-settling binary markets on Polymarket — SPX, NVDA, TSLA, AAPL, AMZN, GOOGL, META, MSFT, NFLX. Exploit gap mispricing using empirical win rate analysis from historical trade data. Gap > 0.5% → buy YES. Gap < -0.5% → buy NO.

### MVP Scope: SPY + QQQ Only

**Why SPY and QQQ first:**
- SPY: 28 daily markets, $1.3M total volume, 27 resolved. Tracks S&P 500.
- QQQ: 23 daily markets, $233K total volume, 22 resolved. Tracks Nasdaq-100.
- Simple binary (YES/NO) — "SPY (SPY) Up or Down on DATE?"
- Both are well-known ETFs with high liquidity and predictable close mechanics
- Enough resolved markets for meaningful empirical analysis

**Expand later:** Individual stocks (NVDA, TSLA, AAPL, AMZN, META, MSFT, GOOGL, NFLX), commodities (WTI, Gold, Silver), international indices.

### Data Source

Public Hugging Face dataset: SII-WANGZJ/Polymarket_data
- `markets.parquet` (85MB, 1M markets) — downloaded, filtered to SPY + QQQ condition IDs
- `trades.parquet` (26GB, 418M trades) — need to download filtered extracts

### Analysis Approach

Simple statistics, not ML:
1. For each resolved SPY/QQQ market, reconstruct pricing trajectory across the trading day
2. Bucket by (time_before_close, price_range) → compute empirical win rate
3. Entry rule: if empirical_win_rate > breakeven_rate + safety_margin → ENTER

```python
# Breakeven by entry price:
# entry $0.10 → breakeven 10% win rate (need 11%+ to justify)
# entry $0.30 → breakeven 30%
# entry $0.50 → breakeven 50%
# entry $0.70 → breakeven 70%
# entry $0.90 → breakeven 90%
```

### Entry/Exit Mechanics

- Entry: At any point where empirical win rate exceeds breakeven + margin
- Exit: Hold to 4pm close (mechanical resolution)
- No early exit needed — binary markets resolve automatically at close

### Risk Parameters

| Parameter | Value |
|-----------|-------|
| Bankroll | $500 |
| Position size | $5-10 per trade |
| Max trades/day | 10-20 |
| Max loss/day | $50 |
| Win rate target | 60%+ |

### Current Status

- markets.parquet downloaded ✅
- SPY + QQQ condition IDs identified ✅
- Next: Download filtered trades data → pricing curve analysis → entry rules

---

## Project 3: Top Trader Pattern Analysis (OPTIMIZATION LAYER)

**Concept:** Monitor top 20 Polymarket traders (by profit) and reverse-engineer their strategies — what markets they trade, position sizing, timing, direction bias. Use insights to refine our own entry rules.

**What we can extract per trader:**
- Full fill history (Goldsky subgraph, proxy wallet, 205K fills for sharky6999)
- Current positions, win rate, P&L (from profile page React Query)
- Market preferences (sharky6999 trades crypto Up/Down markets — same format as our stocks)
- Limit vs market order ratio (~70/30 for sharky6999)

**Key infrastructure learned:** Polymarket uses proxy wallets — base address = identity, proxy wallet = actual on-chain trading. Must use proxy wallet for subgraph queries.

**Status:** Exploration done ✅. Data pipeline (leaderboard → proxy wallets → trade extraction) mapped. Engineering effort: ~1 day to build extraction, ~2 days for full pattern analysis. On hold until Project 1 reaches live paper trading.

**Cross-applicable to Project 1:**
- EV + Kelly sizing (from weather bot guide) — replaced flat sizing with quarter-Kelly on $5K bankroll, capped at $200/trade (4%)
- Self-calibration loop — track gap→win-rate empirically per ticker instead of static thresholds
- Multi-source data fusion — yfinance + Polymarket book + futures
- Stop management — canary stop + trailing stop

---

## Project 3b: Weather Temperature Market Trading

**Concept:** Exploit the gap between professional weather forecast models (NWS, GFS ensemble,
ECMWF) and Kalshi/Polymarket temperature market pricing. The edge is not prediction — it's
detecting where the market's implied probability diverges from model-calibrated probability,
particularly exploiting NWS systematic forecast biases.

**Volume:** ~$2M/day across 37 cities on Kalshi + Polymarket combined (as of March 2026).

### Where the Edge Actually Lives

**1. NWS Systematic Bias (Most Reliable Edge)**
The National Weather Service is the settlement authority for Kalshi weather markets.
NWS max temperature forecasts run a documented warm bias — they systematically overshoot
the actual high by 1–2°F, especially in winter. This bias varies by city and season and
is measurable from historical data. If NWS forecasts 85°F high but historically overshoots
by 1.5°F in this city/month → true high is probably 83.5°F → the market hasn't priced this.

**2. Multi-Model Divergence**
When GFS, ECMWF, and HRRR disagree significantly, the market is pricing uncertainty wrong.
GFS updates every 6h, ECMWF every 12h at higher resolution (14km vs 27km). When they diverge
and then converge toward one model, the market lags the convergence by 30–60 minutes.

**3. Same-Day Pace Misalignment**
For intraday markets: if temperature at 10am is tracking 3°F above the trajectory needed
to hit the daily high, the market still prices the old probability. Real-time ASOS station
data updates every 5 minutes; Kalshi market prices update slower.

### Settlement Mechanic (Critical)
Kalshi settles against the official NWS Daily Climate Report for a specific ASOS station
(usually the major airport). Not weather.com. Not your backyard. Not a city-wide average.
The edge requires knowing the specific station + its historical bias vs NWS forecast.

### Data Sources (All Free)
- **NWS API**: api.weather.gov — official forecasts and historical DCR records (settlement data)
- **Open-Meteo**: GFS 31-member ensemble, free API — same source as best open-source bots
- **NOAA ASOS**: 5-minute station observations, free — live temperature tracking
- **ECMWF Open Data**: free tier for GFS-comparable model output

### Honest Failure Modes
Documented from real traders who lost money:
1. **Gaussian assumption kills you**: Weather errors have fat tails. Events you price at 90%
   confidence are really ~75–80%. If your model doesn't correct for this, you systematically
   overbet.
2. **Fee death zone**: Markets priced at 5¢ with 1¢ fee = 20% immediate tax. Need to trade
   markets with sufficient liquidity (>20¢ prices on both sides).
3. **Stale signals**: GFS updates every 6h. If you poll at the same frequency, faster bots
   have already repriced. Need to react within minutes of model update.

### Open Source Starting Points
- `suislanchez/polymarket-kalshi-weather-bot` — Python/FastAPI, GFS ensemble, Kelly sizing,
  5 US cities, paper trading mode
- `Oalkhadra/prediction-market-trading` — boosted decision tree on 30 features, Kalshi temp markets
- WeatherEdgeFinder.com — commercial tool, surfaces NWS bias edges in real time

### Vs Sports Arbitrage

| | Sports (Strategy B+C) | Weather |
|---|---|---|
| Signal source | Pinnacle (external expert model) | NWS + GFS (external expert models) |
| Modeling required | None — delegate to Pinnacle | Yes — need bias correction + ensemble |
| Data cost | ~$50/mo (Odds API) | Free |
| Volume | 39% of Polymarket, $4.5B Kalshi/mo | $2M/day |
| Competition | High (many sports arb bots) | Medium (fewer weather quants) |
| Speed requirement | 30–90 seconds | Minutes (GFS update cadence) |

Weather is harder to model but less crowded. Sports is easier but more competitive.

**Status:** Research complete. Not started. Priority after Project 2 (Sports) is live.

---

## Project 2: Sports × Sportsbook Arbitrage (HIGH PRIORITY)

**Concept:** Use Pinnacle's sharp odds as the "true probability" benchmark. When Polymarket
or Kalshi misprices a sports event by >2–3% vs Pinnacle's no-vig probability, enter the
underpriced side. No sports knowledge required — you're not predicting outcomes, you're
detecting mispricing relative to an external pricing signal. Same structural logic as the
gap strategy: reliable external signal vs retail prediction market lag.

**Focus: Strategy B + Strategy C only.**

Strategy A (pure cross-platform arb) is deprioritized — Kalshi's 3–7% fee on winnings
eats the spread and makes true risk-free arb rare. Bots close those windows in seconds anyway.

### Strategy B: Value Betting vs Pinnacle ← PRIMARY
Strip Pinnacle's vig to get true implied probability. When Polymarket prices an event at
42¢ but Pinnacle says true probability is 50% → buy at 42¢, positive EV = +8¢.
- Typical edge: 5–15% when clear divergence
- Higher variance than pure arb but much larger edge per trade and far more opportunities
- Pinnacle's crowd is sharper than Polymarket's crowd — structurally valid signal
- No sports knowledge needed: you trust Pinnacle's model, not your own opinion
- Open source: Gambot pulls Pinnacle odds, removes vig, flags Polymarket divergences

### Strategy C: Timing Lag Arb (Sharp-to-Soft)
When Pinnacle reprices rapidly (injury news, lineup change, weather update), prediction
markets lag 30–90 seconds. Enter the new fair value on Polymarket/Kalshi before crowd catches up.
- Highest edge per trade (5–20%) but requires sub-second monitoring
- Needs WebSocket feeds from both Pinnacle and Polymarket simultaneously
- Most infrastructure-intensive

**Does this work without sports knowledge?**
Yes — completely. Strategy A is pure math (price discovery across fragmented markets).
Strategy B is delegating sports knowledge to Pinnacle's sharper crowd.
Strategy C is pure execution timing. None require you to have an opinion on who wins.
You're not betting on sports — you're arbitraging market inefficiency.

**Kalshi applicability:**
Kalshi is actually the primary venue for this strategy in the US:
- CFTC-regulated, US-legal, no account banning for sharp trading
- Sports = 90% of volume ($4.5B/month as of late 2025)
- Same events as Polymarket → enables cross-platform arb between both
- Clean REST + WebSocket API, RSA-authenticated
- Same event priced on Kalshi + Polymarket → gaps of 2–5% are common

**Data pipeline:**
- Pinnacle odds: The Odds API (~$50/month) or OddsPapi
- Kalshi prices: Kalshi REST API (free, public)
- Polymarket prices: Polymarket CLOB API (free, public)
- Unified feed: SportsGameOdds aggregator or Prediction Hunt unified API

**Open source references:**
- `ImMike/polymarket-arbitrage` — Python, watches 10,000+ markets across Polymarket + Kalshi
- `Drakkar-Softwares/polymarket-kalshi-arbitrage-bot` — TypeScript, 15-minute sports markets
- Gambot — pulls Pinnacle odds, devigged, flags Polymarket mispricings

**Status:** Research complete. Not started. Planned after Project 1 crypto expansion.

**Priority reasoning:** Sports is 39% of all Polymarket volume. $40M+ documented arb profits
in the 12 months Apr 2024–Apr 2025. Lower vig than sportsbooks means small-edge models that
barely break even at Betfair are profitable at Polymarket. Same infrastructure pattern as
Project 1: external reliable signal → prediction market lag → Kelly-sized entry.

---

## Project 4: BTC End-of-Window (LOWEST PRIORITY)

**Status:** Tested and invalidated for pure latency arb. BTC end-of-window panic sells only if clear opportunity arises.

---

## Data Collection for Live Markets

Once entry rules are derived from historical data, we need live data collection:
1. Scrape `polymarket.com/finance` → `__NEXT_DATA__` for current SPY/QQQ prices
2. Poll CLOB books every 60s during market hours (9:30am-4:00pm ET)
3. Record book snapshots + SPY/QQQ price from Yahoo Finance
4. Record outcomes after 4pm close

This live data will eventually become our own training data, replacing the HF dataset.
