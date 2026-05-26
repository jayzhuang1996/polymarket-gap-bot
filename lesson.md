# Lessons — Production Polymarket Bot Operations

Distilled operational learnings. Only what applies to this project.

---

## 1. Dry-run with a real wallet, zero balance

Paper trading simulates P&L but misses the actual execution layer:
- **NSF rejections** — $0 balance passes client-side validation; CLOB rejects it. Backtest assumes fills that never happen.
- **Signature errors** — EIP-712 signing on Polygon has edge cases. Invalid signature = missed entry.
- **USDC allowance** — before the first order, call `approve()` on-chain to allow the CLOB contract to spend USDC. One-time per wallet, but if skipped, every order is rejected at the smart contract level.
- **MATIC gas** — Polygon requires MATIC for gas, not USDC. A wallet with $500 USDC and zero MATIC places zero transactions. Monitor MATIC separately. Keep ≥ $2 equivalent at all times.

**What to do:** Run exact order-submission code with $0 balance for a full week. Log every rejection reason — each one is a trade the backtest pretends filled.

---

## 2. WebSocket data quality is the hidden tax

| Problem | What we see | Impact |
|---------|-------------|--------|
| Stale snapshot on connect | First tick is cached state, not current | Wrong entry price |
| After-hours garbage | Post-4pm: $0.001 / $0.999 prices | False signals if time gate fails |
| Silent stale feed | WS stays "connected" but stops sending | Bot holds losing position past exit |
| Top-of-book only | Depth check sees level 1 only | Depth looks fine; price moves on second fill |

**Already handled:** Hard time gate at 4pm, price sanity filter ($0.01–$0.99).

**Still needed before live:**
- Discard first tick on reconnect (stale snapshot)
- Track last-tick age — if > 5 seconds on an active position, treat feed as stale and widen exits
- Track per-ticker fill rate: "when ask=$0.55 and we place limit at $0.55, how often does it fill in 2 min?"

---

## 3. Entry price vs win rate — the math that kills bots

```
Breakeven WR = entry_price / 0.99 (Polymarket charges 1% at settlement)

At 57¢: breakeven = 57.6%  →  70% WR = +12.4pp edge
At 67¢: breakeven = 67.7%  →  70% WR = +2.3pp (one bad spread fill erases it)
At 77¢: breakeven = 77.8%  →  70% WR = negative edge, guaranteed loser
```

Our $0.40–$0.70 band is directionally correct. The correct upper bound is `base_WR × 0.99 − min_edge`, not a flat $0.70. SPX at 78¢ with 78% WR is +3.2% edge but gets blocked. Acceptable trade-off given current data volume.

---

## 4. Backtest must match paper within 3%

Run `tools/paper_trade_sim.py` against a past date with real CLOB data, then re-run with full entry logic (WebSocket pre-sign recheck, limit order timeout, spread adjustments). The difference is the "execution gap" — what the market takes between your decision and your fill.

If the gap is > 5%, strategy assumptions are wrong. Fix the execution model before sizing up. Our execution gap is unmeasured until dry-run begins.

---

## 5. Speed matters for exit, not entry

Gap mispricing persists for minutes to hours. Latency is irrelevant for entries. The ONE place where it matters: **GFR-triggered exits**.

When GFR crosses −0.5, the stock is moving against us right now. If the WebSocket is 3s stale and the order takes 2s to sign, actual GFR at fill is −0.7 and the token moved 5–10¢ against us.

**What to do:** On GFR exit and NO trailing stop: check WS tick age. If > 2s, use bid − 1 tick to prioritize fill speed over price. Cost of missing the fill > cost of the extra tick.

---

## 6. CLOB API rate limiting and nonce management

**Rate limiting:** Undocumented ~10 req/sec limit. When 4 tickers trigger simultaneously: cancel + resubmit × 3 each = up to 24 signed requests in a few seconds. Current code doesn't retry on 429 — it just misses the trade. Add exponential backoff.

**Nonce management:** Each Polygon transaction uses a sequential nonce per wallet. Two simultaneous orders can grab the same nonce → one is rejected. Reprice loop can legitimately emit 2 requests within 1 second. **Fix:** Serialize all order submissions through a single async queue.

---

## 7. Token precision and minimum order size

- Minimum CLOB order: $1 or $5 face value depending on market (verify per ticker)
- Kelly can produce 143.7 contracts → must round DOWN, not nearest
- On partial exits: after selling 50%, check if remaining position is above minimum tradeable size. If not, exit in full rather than leaving a dust position.

---

## 8. Market resolution edge cases

- **1¢ flip:** Stock closes $218.50 on Yahoo but Polymarket resolves at $218.49. One cent = entire $100 position. Rare but real. Cross-check resolutions against Yahoo Finance.
- **Delayed resolution:** Market sits unresolved for hours. Capital locked but P&L fine. Liquidity risk, not directional risk.
- **Friday close:** 4pm NYSE is the resolution price. Market-hours guard must use NYSE calendar, not generic weekday check.

---

## 9. The structural edge is narrow — discipline is the moat

Market makers on Polymarket earn 2–5% per round-trip with zero directional risk. Our edge requires being right about direction AND getting fills at the assumed prices. That means:

- Strict spread filter (no trades when bid-ask > 10% after 10:30am)
- Entry price band ($0.40–$0.70) enforced
- Exit at signal, not at "feels like it might come back"
- No overrides on the daily loss limit

The edge is structural (market doesn't reprice on gap data) but narrow. The only variable we can control is execution discipline.

---

## 10. NSF rejections are signals, not bugs

Every "insufficient funds" rejection in dry-run tells you what the strategy WOULD do with real capital. Collect them all. They reveal:
- How many simultaneous entries the strategy actually wants (vs the 6-position cap)
- Whether Kelly sizing produces sub-$20 positions
- Which tickers the strategy enters most aggressively

Log every attempted order in dry-run. Don't discard NSF rejections.

---

## 11. Credential hygiene — non-negotiable before live

- Private key (Polygon L1) in `.env` only. Never in code, never in logs.
- If key appears in a log file even once, rotate it immediately.
- Bot wallet must be a dedicated address — never same as personal wallet.
- CLOB API key (separate from private key): rotate every 90 days.

---

## Pre-Live Checklist Summary

| Category | Key items |
|----------|-----------|
| **Wallet** | MATIC ≥ $2, USDC loaded, `approve()` called, dedicated wallet |
| **Execution** | WS first-tick discard, 429 backoff, nonce queue, sub-minimum check |
| **Data** | Gaps loaded, WR store populated, settlement model loaded, WS delivering live ticks |
| **System** | No startup errors, DB writable, crash-recovery plist running, daily loss limit set |
| **Dry-run** | Full week at $0 balance, all NSF rejections logged, backtest gap < 5% |

---

## What's Fixed Since Initial Build

| Item | Status |
|------|--------|
| Crash recovery (launchd KeepAlive + reconcile on restart) | Done |
| Session state reconciled after restart (no double-entries) | Done |
| adj_wr / gfr_at_entry / spread_at_entry stored at entry | Done |
| daily_wr deduplication (DELETE+INSERT, MIN_OBS=30) | Done |
| scraped_observations backfilled (142 → 1,355 rows) | Done |
| EOD pipeline automated (4-step, launchd at 4:20pm ET) | Done |
| WS reconnect first-tick discard | Not done |
| 429 backoff | Not done |
| Nonce serialization queue | Not done |
| Sub-minimum partial exit check | Not done |
