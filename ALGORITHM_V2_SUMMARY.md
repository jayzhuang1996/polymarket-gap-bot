# Algorithm v2 — Change Summary

**Date:** 2026-05-29  
**Session:** Complete algorithm redesign — model-driven direction, new features, simplified entry gate.

---

## What Changed

### 1. New primary model features

| Old | New | Why |
|-----|-----|-----|
| `gfr` (gap fill ratio) | `stock_pct_vs_prevclose` | Directly measures where the stock is vs the settlement threshold (prev_close). More predictive throughout the day, not just at open. |
| `gfr_velocity` | `momentum_30min` | 30-min change in stock position vs prev_close. Captures whether the thesis is still trending correctly. |
| `gap_abs` | *(removed)* | Subsumed by `stock_pct_vs_prevclose`. |

**Formula:**  
`stock_pct_vs_prevclose = gap_pct_fraction × 100 × (1 + gfr)`  
= where the stock is right now vs yesterday's close, in percentage points.

**Momentum:**  
`momentum_30min = stock_pct_vs_prevclose(now) − stock_pct_vs_prevclose(30 min ago)`  
Positive = stock trending away from prev_close (thesis strengthening).  
Negative = stock trending back toward prev_close (thesis weakening).

### 2. Model performance — old vs new on same holdout (2026-04-15 to 2026-05-28)

| Model | AUC (holdout) |
|-------|---------------|
| Old model (gfr + gap_abs features) | **0.47** — effectively random on recent data |
| New model (stock_pos + momentum) | **0.70** — meaningful predictive power |

The old model was overtrained on Oct 2025 – Apr 2026. The regime shift (bearish April–May 2026) broke it completely. The new features are more stable across regimes because they express the same underlying logic (where is the stock vs the settlement line) without depending on the gap being the primary driver.

Directional accuracy at 55% confidence threshold: **56.5%** on holdout.

### 3. Entry gate — SPRT and 3-of-4 removed

**Old gate:**  
- AMZN/TSLA: SPRT accumulated consecutive GO signals over 10-12 minutes before entry.  
- All others: 3-of-4 GO signals in last 4 ticks (8 minutes wait).  
- Effect: missed many entries because the stock moved past fair value before the gate passed.

**New gate:**  
1. Gap above per-ticker threshold (TICKER_GAP_THRESHOLD, previously hardcoded to 50 bps flat).  
2. Settlement model P(YES) ≥ 0.55 → enter YES. P(YES) ≤ 0.45 → enter NO.  
3. Live edge (model probability × 0.99 − ask price) ≥ time-based floor.  
4. Price in [0.40, 0.85] range.  
5. Spread ≤ spread_max for the hour.

No waiting. Entry happens the first tick the model has sufficient confidence and the edge clears the floor.

### 4. Direction is now model-driven

**Old:** `side = "YES" if gap_bps > 0 else "NO"` — hardcoded from overnight gap direction.  
**New:** Direction from `settlement_p_win`:
- `p_yes ≥ 0.55` → YES token is mispriced vs model estimate → BUY YES  
- `p_yes ≤ 0.45` → NO token is mispriced → BUY NO  
- `0.45 < p_yes < 0.55` → model uncertain → skip

This handles reversals automatically: a gap-UP day where the stock has already crossed prev_close will have `p_yes < 0.45` and the model will suggest NO rather than forcing a YES trade.

### 5. Per-ticker gap threshold wired

`TICKER_GAP_THRESHOLD` from config is now used in `_compute_signal` and `_check_entry`. Previously hardcoded to 50 bps for all tickers.

| Ticker | Old threshold | New threshold |
|--------|---------------|---------------|
| SPX    | 50 bps | 50 bps |
| NVDA   | 50 bps | **75 bps** |
| TSLA   | 50 bps | **100 bps** |
| AAPL   | 50 bps | **60 bps** |
| AMZN   | 50 bps | **65 bps** |
| NFLX   | 50 bps | **150 bps** |

### 6. Exit: NO trade settlement_urgent fixed

**Old:** `settlement_urgent` fired when `p_yes < 0.45` regardless of trade direction. For a NO trade, this is wrong — you want to exit NO when the thesis flips, i.e., when `p_yes > 0.55`.

**New:** Exit is per-side:
- YES trade: exit when `p_yes < 0.45` (model says we're now likely to lose)
- NO trade: exit when `p_yes > 0.55` (model says the YES thesis has recovered, NO losing)

### 7. Kelly sizing uses settlement_p directly

`compute_position_size(settlement_p_win, entry_price)` replaces `compute_position_size(adj_wr, entry_price)`. The settlement model's probability is the most current estimate of win rate — it's updated every 5 seconds rather than being a static daily lookup.

---

## Files Changed

| File | Change |
|------|--------|
| `data/full_session_2min.csv` | Added `stock_pct_vs_prevclose` and `momentum_30min` columns |
| `data/settlement_model.pkl` | Retrained with new features. AUC 0.70 (up from 0.47 on same holdout) |
| `engine/settlement_model.py` | New feature order, new predict() signature |
| `engine/state.py` | Added `_stock_pos_history` for 30-min momentum rolling window |
| `engine/data_feed.py` | Computes `stock_pct_vs_prevclose` and `momentum_30min` live, updated predict() call |
| `engine/strategy.py` | Model-driven direction, SPRT/3-of-4 removed, per-ticker gap threshold, NO exit fix |
| `engine/session.py` | Uses `settlement_p` for Kelly sizing and reprice signal_ok check; removed SPRT dashboard |
| `config.py` | Added `SETTLEMENT_YES_THRESHOLD = 0.55`; SPRT params retained as legacy symbols only |

---

## Risk Assessment

**Upside:** Eliminates the 10-12 minute SPRT wait that was causing missed entries. Handles reversals automatically rather than hardcoding direction. Model much more robust on recent data (0.47 → 0.70 AUC).

**Risk:** Faster entry = more trades per day. Without the 3-of-4 confirmation filter, some false positives may enter on the first confident model tick. The per-side exit logic for NO trades is new — monitor first week for unexpected behavior.

**Mitigations:**  
- Time-based edge floors remain (5%/8%/15%/20% by time of day).  
- GFR exit for YES trades still active (fires when GFR < -0.5, historically 18% WR).  
- Hard 3pm exit unchanged.  
- NO trail stop and profit lock unchanged.

---

## Next Steps

1. Monitor first live session — check that `MODEL` tags appear in entry logs (not `FALLBACK`).
2. After 20+ live trades, recompute directional accuracy vs model predictions.
3. Collect `stock_pct_vs_prevclose` at entry in DB — add column to `decisions` table.
4. Retrain model monthly with new live data as it accumulates.
