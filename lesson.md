# Lessons Learned: Polymarket Data Architecture

This file documents wrong assumptions, mistakes, and confusions encountered while building the Polymarket trading bot. Read this before starting any new research or implementation.

---

## 1. All Crypto Markets Are Pure CLOB — No AMM

**The mistake:** I repeatedly assumed markets had an AMM (automated market maker) that reprices based on oracle updates. Every architecture diagram and strategy description was built on this assumption.

**The reality:** Every single crypto market on Polymarket has `enableOrderBook: True` and `marketMakerAddress: ''` (empty string = no AMM). Verified across all 66+ active crypto events. The platform migrated to a CLOB-first architecture.

**How to avoid:** Before making ANY claim about market mechanism, check the raw API response:
```python
is_amm = market.get("marketMakerAddress") not in (None, "", "0x0...0")
```

---

## 2. Two Prices: Reference Price vs Order Book Price — They Are NOT the Same

**The mistake:** I used `token.price` from the `GET /markets/{condition_id}` response as if it were a live, tradeable price.

**The reality:** There are TWO separate prices on every Polymarket token:
- **Reference price** (`token.price`): A static/stale field. Origin unclear — possibly a mark price or last-traded. Hours/days out of date. NOT tradeable.
- **Order book price** (best bid/ask from `GET /book?token_id={id}`): The actual live price where you can buy/sell. Use for all decisions.

**Evidence:**
| Market | Reference Price | Book Mid | Diff |
|--------|---------------|----------|------|
| 5-min BTC | $0.505 | $0.585 | -13.7% |
| Gold Daily | $0.080 | $0.050 | +60% |
| BTC→$150k Jun | $0.013 | $0.007 | +80% |

**How to avoid:** Never use `token.price` for trading decisions. Only use order book bid/ask. Always ask: "Is this the reference price or the order book price?"

---

## 3. Order Book API: Correct Endpoint is `GET /book`, NOT `POST /orderbook`

**The mistake:** `fetch_order_book()` called `POST /orderbook` which always returned 404.

**The reality:**
- Correct: `GET https://clob.polymarket.com/book?token_id={token_id}`
- Wrong: `POST https://clob.polymarket.com/orderbook`

**How to avoid:** Test every API endpoint with a raw curl call before writing any code that depends on it.

---

## 4. Gamma API Returns JSON Strings, Not Native Objects

**The mistake:** Code like `float(prices[0])` crashed because `prices` was a JSON string `'["0.58", "0.42"]'`, not a list.

**The reality:** Gamma API wraps nested JSON as strings:
- `outcomePrices` → string. Fix: `json.loads(outcomePrices)`
- `clobTokenIds` → string. Fix: `json.loads(clobTokenIds)`

**How to avoid:** Check `type()` on every Gamma field you use before assuming it's parsed.

---

## 5. Building Theories on Unverified Assumptions

**The cost of not verifying:** I spent multiple sessions building strategies based on market structure assumptions never verified with raw API data:
- Assumed AMM existed → built strategy around AMM entry/exit
- Assumed reference price was live → ran tests measuring wrong metric
- Assumed `/orderbook` was correct endpoint → code silently failed
- Assumed `outcomePrices` was a list → type errors

Days of wasted work, invalidated test data, confusing analysis.

**How to avoid:** Before forming ANY theory about how Polymarket works:
1. Make a raw API call (curl or Python requests)
2. Print the FULL response
3. Verify data types with `type()`
4. Check the field you're building on exists and contains what you expect
5. Only then form a hypothesis

---

## 6. Gamma `outcomePrices` Is Indexer Data, Not a Live Price Feed

Gamma `outcomePrices` updates via Polymarket's on-chain indexing pipeline, NOT from the CLOB order book. For CLOB-only markets (all crypto), on-chain settlement happens AFTER the window closes, so Gamma's outcomePrices freezes during the trading window.

**Observed:**
- 15-min BTC: Gamma was 244% off from CLOB book, 324s stale
- 5-min BTC: Gamma never updated during the 5-min trading window — book went 0.50→0.99, Gamma stayed frozen at 0.515

**Architecture:**
```
Off-chain CLOB (real-time) ──→ GET /book, /price, /midpoint
     ↓ (settlement after window)
On-chain Polygon (CTF contracts) ──→ indexed by Gamma API
     ↓
Gamma outcomePrices updates (stale during trading)
```

**The fix:** Never use Gamma outcomePrices or CLOB token.price for trading. Use only:
- `GET /book?token_id={id}` — live order book
- `GET /midpoint?token_id={id}` — live midpoint (~100ms)
- `GET /price?token_id={id}&side=BUY/SELL` — live best ask/bid (~100ms)
- WebSocket `wss://ws-subscriptions-clob.polymarket.com/ws/market` — real-time stream

This is NOT a bug in our code or Polymarket's API. It's a correct understanding of a two-layer architecture where discovery (Gamma) and trading (CLOB) use different data pipelines.

---

## 7. How to Find Polymarket Markets

Three approaches, in order of reliability:

### A) Gamma Events API with slug search (BEST for daily stock markets)
```
GET https://gamma-api.polymarket.com/events?slug={ticker}-up-or-down-on-{month}-{day}-{year}
```
Slug format: `nvda-up-or-down-on-may-20-2026`. Works for all 9 tickers, SPX Opens, SPY, WTI.

### B) Frontend `__NEXT_DATA__` scraping (BEST for category browsing)
Navigate to `polymarket.com/finance` → extract `__NEXT_DATA__` → parse `dehydratedState` → find `finance-markets` query. This gives ALL events in a category with live prices, volumes, depth.

### C) Gamma `/markets` endpoint (WORST — incomplete)
Returns ~100 markets with opaque ordering. Tag parameter doesn't filter properly. Avoid for discovery.

---

## 8. The Book Changes Faster Than We Can Poll

**Observed in 20-second rapid poll test:**
- UP price moved 0.860→0.890
- Ask depth fluctuated: 408→15→231→2561→5 contracts
- "Can fill $50" changed from YES→NO→YES multiple times within seconds

In another 30-second poll: CLOB book mid moved 0.095→0.145 (53%) then flipped to 0.475→0.705 within minutes.

**Implication:** A "confirmed" entry signal can vanish before our order is signed. Re-check conditions right before signing.

---

## 9. Polymarket Docs Structure

- Base: `https://docs.polymarket.com/`
- Full index: `https://docs.polymarket.com/llms.txt`
- Concepts: `https://docs.polymarket.com/concepts/prices-orderbook.md`
- Market data: `https://docs.polymarket.com/market-data/overview.md`
- API reference: `https://docs.polymarket.com/api-reference/introduction.md`
- Gamma OpenAPI: `https://docs.polymarket.com/api-spec/gamma-openapi.yaml`
- CLOB OpenAPI: `https://docs.polymarket.com/api-spec/clob-openapi.yaml`

Check `llms.txt` first for the full doc tree index.

---

## 10. Historical Trade Data: Hugging Face Dataset

**Source:** [SII-WANGZJ/Polymarket_data on Hugging Face](https://huggingface.co/datasets/SII-WANGZJ/Polymarket_data)

**What it contains:**
- `markets.parquet` (85MB, 1,019,069 markets) — slugs, questions, condition IDs, token IDs, volumes, outcomes
- `trades.parquet` (26.1GB, 418M trades) — individual trade records (`condition_id`, `timestamp`, `price`, `usd_amount`, `maker_direction`)

**How it's useful:**
- Filter by `question` to find daily close markets: `df[df['question'].str.contains(r'\(\w+\)\s+Up\s+or\s+Down\s+on', na=False)]`
- Get condition IDs → match with trades data
- Get market metadata: volume, outcome, token IDs

**Stability tiers (from HF dataset, Oct 2025 - May 2026):**
| Tier | Tickers | History |
|------|---------|---------|
| Long-standing | SPX, NVDA, AMZN, NFLX | 8 months, ~135 markets |
| Newer | SPY, WTI | 3 months, ~27 markets |
| Short-lived | QQQ | 2 months, 23 markets |

**Lesson:** Don't build around a market with <3 months of data. SPX is gold standard.

**Current limitation:** Dataset snapshots from Oct 2025 to early May 2026. Need our own collection going forward.

---

## 11. WebSocket API: Live Order Book Streaming
ok 
**Endpoint:** `wss://ws-subscriptions-clob.polymarket.com/ws/market`
**Auth:** None required (public channel).

**Subscription:**
```python
{
    "type": "market",
    "assets_ids": ["<token_id>"],
    "initial_dump": True,
    "custom_feature_enabled": True  # enables best_bid_ask events
}
```
**Heartbeat:** Send `PING` every 10s; server replies with `PONG`.

**Event types:**
| event_type | Description |
|---|---|
| Initial snapshot (list) | Full order book — price levels with side, price, size |
| `price_change` | Delta update — price, size, side, best_bid, best_ask |
| `last_trade_price` | Trade execution |
| `best_bid_ask` | Only with `custom_feature_enabled: true` |

**Verified working.** Updates every ~1s even during quiet pre-market. Both YES and NO tokens arrive simultaneously.

**Market hours note:** SPY has book activity pre-market. Individual stocks (NVDA, TSLA) have 0 bids/asks before 9:30am ET. Connection still works — you get empty books until liquidity arrives.

---

## 12. CLOB Price Endpoints: `/price` vs `/book`

| Endpoint | What it returns | Use for |
|----------|----------------|---------|
| `GET /price?token_id={id}&side=BUY` | Competitive best bid | Live trading prices |
| `GET /price?token_id={id}&side=SELL` | Competitive best ask | Live trading prices |
| `GET /midpoint?token_id={id}` | Midpoint of best bid/ask | Quick price check |
| `GET /book?token_id={id}` | ALL order book levels (including extremes) | Depth analysis |

The `/book` endpoint includes mechanical arbitrage orders at 0.01 and 0.99. The `/price` endpoint returns only the competitive best bid/ask.

**Gamma API `bestBid`/`bestAsk` ARE live and correct** — they match CLOB `/price` values (sourced from same pipeline). Verified via cross-reference with `/book`.

**To get NO price:** NO has its OWN token_id — query it directly, NOT as `1 - YES_price`:
```python
requests.get("https://clob.polymarket.com/price",
    params={"token_id": "NO_TOKEN_ID", "side": "BUY"})
```

---

## 13. HF Dataset Trades: YES and NO Tokens Are Mixed Under One `condition_id`

**The mistake:** I used `trades.parquet` VWAP as YES token price and computed edge = win rate - VWAP, claiming "+57% NO edge on gap-down days."

**The reality:** `trades.parquet` has NO `token_id` — only `condition_id`. Each condition has two tokens (YES and NO), so trades for BOTH are mixed. A VWAP across all trades is a meaningless blend.

**Evidence (resolved SPX market where YES won):**
| Trade Type | Count | VWAP |
|-----------|-------|------|
| Trades above $0.50 (likely YES) | 8 | $0.900 |
| Trades below $0.50 (likely NO) | 42 | $0.351 |
| ALL trades mixed | 50 | $0.645 ← meaningless |

**What's still valid from HF dataset:**
- Win rates from `outcome_prices` (settlement data, not trades) ✅
- Gap calculations from yfinance (stock data) ✅
- Current live prices from CLOB `/price` endpoint ✅
- Token ID mapping from Gamma events API ✅

**What's invalid:**
- Historical YES/NO prices derived from trade VWAPs
- "Edge" numbers computed from those prices
- Any conclusion about intraday price trajectories based on trade data

---

## 14. Corrected Gap Analysis — Separating YES from NO Trades

**Methodology:** For each resolved market, split trades at $0.50 threshold. Trades above $0.50 = winning side, below = losing side. Works because YES + NO ≈ $1.00 at all times (verified: sum clusters at 99-101¢).

**Sample sizes:** Small (3-14 observations per bucket). Directional signals, not precise measurements. Paper trading needed to validate.

### Gap-Up > 0.5% — Buy YES
| Ticker | Best Window | YES WR | YES Price | YES Edge |
|--------|------------|--------|-----------|----------|
| SPX | 9:30am | 78% | 71¢ | +6% |
| NVDA | 9:30am | 70% | 62¢ | +8% |
| TSLA | 10:00am | 75% | 68¢ | +7% |
| AMZN | 11:00am | 67% | 59¢ | +7% |

### Gap-Down < -0.5% — Buy NO
| Ticker | Best Window | NO WR | NO Price | NO Edge |
|--------|------------|--------|----------|---------|
| SPX | 9:30am | 80% | 68¢ | +12% |
| AMZN | 9:30am | 83% | 70¢ | +14% |
| TSLA | 9:30am | 83% | 76¢ | +8% |
| NVDA | 12:00pm | 100% | 79¢ | +21%* |

*NVDA 12pm: only 3 observations — low confidence.

### Key findings:
1. **Real edge is 5-15%, not 50-60%.** Earlier +57% NO edge was a data artifact from mixed YES/NO trades.
2. **SPX and AMZN gap-down are strongest** — NO edge +12-14% at 9:30am, 80-83% WR, 10-12 observations each.
3. **SPX gap-down edge decays by 11am** (9:30am: +12%, 10am: +7%, 11am: +0.5%).
4. **AMZN gap-down edge persists all day** — +13-14% even at 1pm.
5. **NVDA gap-up (+8%) is cleanest YES signal** — strongest and most consistent.
6. **The market is systematically wrong about gaps,** but modestly so. Execution quality (spread, timing) matters.
7. **Broad NO bias in individual stocks** — YES overpriced by 2-5¢ at 9:30am across all days (retail optimism bias).

### Strategy implications
- Target 5-15% edge per trade
- Capital recycling (2-3x/day at 10% edge) compounds faster than single holds
- Spread cost consumes significant fraction of edge — limit orders essential
- Paper trade 2-4 weeks to validate before live

---

## 15. Top Trader Monitoring (Side Project)

**What we learned from sharky6999 (30K predictions, $35.5K portfolio):**
- Trades **crypto price markets** (XRP, SOL, ETH, BNB Up/Down) — same format as our stock strategy
- Proxy wallet at `0x751a2b86cab503496efd325c8344e10159349ea1` has 205K fills on Goldsky subgraph
- Mix of limit (~70%) and market (~30%) orders
- Polymarket uses proxy wallet system: base address = identity, proxy wallet = actual trading

**Accessible data per trader:**
- Leaderboard (top by profit/volume) via `polymarket.com/leaderboard` → `__NEXT_DATA__`
- User stats: trade count, biggest win, P&L history (from profile page React Query)
- Current positions with full market context
- Full fill history via Goldsky subgraph (using proxy wallet address)
- Goldsky endpoint: `https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/0.0.1/gn`

**Limitations:** Gamma API requires auth. Can only get CLOB fills from subgraph (not AMM swaps). P&L reconstruction requires joining fills to market outcomes.

---

## Checklist Before Building Any New Feature

Before writing code that depends on Polymarket data:

- [ ] Made a raw API call and verified the response structure?
- [ ] Checked data types of ALL fields used (`type()` on each)?
- [ ] Verified the endpoint returns 200, not 404?
- [ ] Distinguished reference price from order book price?
- [ ] Confirmed the field is from CLOB (live) not Gamma (stale)?
- [ ] Checked `marketMakerAddress` to confirm AMM vs CLOB?
- [ ] Not assumed any field is a native type without verifying?
- [ ] Measured the actual latency of the data source?
- [ ] Tested how fast the data changes (poll multiple times)?
- [ ] Asked: "Is this data fresh enough for the decision I'm making?"
- [ ] Confirmed the correct endpoint to FIND the market? (slug search vs frontend vs Gamma)

---

## Pre-Live Execution Risks — Four Items Still Open

These are not done. Each one is a class of trade that paper trading silently misses.

### 1. WebSocket stale snapshot on reconnect
First message after a WS connect is cached state from Polymarket's server — not the current live book. If a reconnect happens mid-session (Railway restart, network blip), the first tick can be 60+ seconds stale. An entry decision made on that tick uses the wrong price and wrong spread.

**Fix needed:** Discard the first event on every new WS connection. Tag reconnects so the session loop knows to skip one cycle.

### 2. 429 rate limiting — no retry logic
Polymarket CLOB has an undocumented ~10 req/sec limit. When 4+ tickers trigger simultaneously (entry + position check + book refresh), the burst easily hits the limit. Current code doesn't retry on 429 — it logs and moves on. That trade is silently missed.

**Fix needed:** Exponential backoff with jitter on all CLOB REST calls. In paper trading, missed fills look like "no opportunity" — in live trading, they're lost P&L with no alert.

### 3. Nonce serialization — no queue
Each Polygon transaction uses a sequential nonce per wallet. Two simultaneous orders (e.g., NVDA + TSLA both trigger at 9:37am) can grab the same nonce from the RPC node → one is rejected with a nonce collision error. The reprice loop can also emit two requests within the same second.

**Fix needed:** Single async queue for all order submissions. Orders dequeue one at a time. This serializes signing and prevents nonce collisions.

### 4. Sub-minimum partial exit
After selling 50% of a NO position (profit lock), the remaining half may fall below Polymarket's minimum order size ($1–5 face value, varies by market). Attempting to exit a dust position causes a CLOB rejection. The position stays open indefinitely.

**Fix needed:** After any partial exit, check if the remaining position is above minimum size. If not, exit in full rather than leaving a dust position.

---

## 16. Settlement Model Feature Mismatch Silently Disables the Model

**What happened:** `engine/settlement_model.py` had `_FEATURE_ORDER` with 5 entries; the saved pkl contained a scaler fit on 7 features. `scaler.transform(row)` raised a dimension error every 5-second price tick. The `except Exception: pass` block caught and suppressed it. `settlement_p_win` was `None` for the entire paper-trading run — model completely disabled with no alert.

**How it hid:** The dashboard still showed `settlement_edge: null` instead of a number, which was visually indistinguishable from "model unavailable because market is closed."

**Fix:** On load, compare `len(_FEATURE_ORDER)` against `bundle["scaler"].n_features_in_`. If mismatched, log a clear WARNING and set `_bundle = None` immediately — do not let wrong-dimension inference silently proceed.

**Rule going forward:** After any model retrain, verify the production inference module's `_FEATURE_ORDER` matches the new pkl's feature count before committing. Add a startup assertion.

---

## 17. sklearn Version Mismatch Between Training and Inference

**What happened:** Training was done via the system `python` (Anaconda, sklearn 1.6.1). Railway runs the project's `.venv` (sklearn 1.8.0). Every model load emitted `InconsistentVersionWarning` — harmless for now but will break on a major version boundary.

**Fix:** Always use `.venv/bin/python` for model training. `eod_pipeline.py` now auto-detects `ROOT/.venv/bin/python` and falls back to `sys.executable` only if the venv doesn't exist.

**Rule going forward:** The pkl must be trained by the same sklearn major version that runs in production. Lock this in `requirements.txt` with an exact version pin once we go live.

---

## 18. Hard Exit Must Fire Even When Bid Is Stale

**What happened (AMZN pattern):** `_check_exit()` read `current_bid` at the top of the function. If the WebSocket was stale or the market thin, `current_bid` was `None` or `0`. The function returned `None` — including at 3pm hard exit time. AMZN position stayed open past close with no record of exit.

**Fix:** Hard time exits (3pm `hard_3pm`, 4pm `hard_4pm`) must fire unconditionally. If `current_bid` is unavailable at exit time, fall back to `entry_price` so the position records at breakeven rather than staying orphaned.

**Pattern:** Any time-triggered exit is more critical than a price-triggered one — never gate a hard deadline on data availability.
