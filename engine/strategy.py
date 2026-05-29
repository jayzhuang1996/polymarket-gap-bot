"""Trading strategy — time helpers, signal computation, entry/exit decisions.

Pure-ish functions: they read session state from engine.state but contain
no I/O (no network calls, no DB writes) other than the VIX yfinance fetch.

Algorithm v2 changes:
  - Entry direction driven by settlement model P(YES), not hardcoded from gap direction.
  - Entry gate: model confidence ≥ SETTLEMENT_YES_THRESHOLD + live edge ≥ floor.
    SPRT and 3-of-4 signal accumulation removed.
  - Gap threshold per ticker via TICKER_GAP_THRESHOLD (replaces hardcoded 50 bps).
  - Exit: settlement_urgent now fires per-side (YES exits when p_yes < 0.45;
    NO exits when p_yes > 0.55).
"""

import datetime as _dt

import yfinance as yf

import engine.state as state
from config import (
    TRADING_FEE_PCT, BAYES_LAMBDA, BAYES_STEEP_LAMBDA,
    SETTLEMENT_YES_THRESHOLD,
    TICKER_GAP_THRESHOLD,
    VIX_HIGH_THRESHOLD,
    VIX_CHANGE_BULLISH_LO, VIX_CHANGE_BULLISH_HI,
    VIX_CHANGE_BEARISH_MIN, VIX_BULLISH_EDGE_DISCOUNT, VIX_BEARISH_EDGE_PENALTY,
    NO_PROFIT_LOCK_GAIN, NO_PROFIT_LOCK_FRAC,
    NO_TRAIL_STOP_DROP, NO_TRAIL_STOP_FRAC, NO_TRAIL_MIN_PEAK,
    GFR_NO_ENTRY_MIN,
    REVERSAL_NO_WR, REVERSAL_NO_WR_DEFAULT, REVERSAL_EDGE_MIN,
)

# ── Session constants ──────────────────────────────────────────────────────────
LATE_ENTRY_HOUR_CUTOFF     = (10, 30)
TIER1_ENTRY_HOUR_CUTOFF    = (12, 0)    # 12:00–13:30 → edge floor 15%
TIER2_ENTRY_HOUR_CUTOFF    = (13, 30)   # 13:30–14:00 → edge floor 20%
ENTRY_FREEZE_HOUR          = (14, 0)    # 14:00 → hard freeze
HARD_EXIT_ET               = (15, 0)
ET_OFFSET_H                = -4         # EDT (Mar–Nov)
GFR_COOLDOWN_MINUTES       = 30
FULLY_EXITED_THRESHOLD     = 0.05
ENTRY_CONFIRMATIONS_NEEDED = 3          # kept for session.py reprice signal_ok check


# ── Time helpers ───────────────────────────────────────────────────────────────

def _et_now_hm() -> tuple[int, int]:
    utc = _dt.datetime.now(_dt.timezone.utc)
    et  = utc.replace(tzinfo=None) + _dt.timedelta(hours=ET_OFFSET_H)
    return et.hour, et.minute


def _in_market_hours() -> bool:
    h, m = _et_now_hm()
    return (9, 30) <= (h, m) <= HARD_EXIT_ET


def _entry_frozen(h: int, m: int) -> bool:
    return (h, m) >= ENTRY_FREEZE_HOUR


def _is_late_entry(h: int, m: int) -> bool:
    return (h, m) >= LATE_ENTRY_HOUR_CUTOFF


def _is_thursday() -> bool:
    return _dt.datetime.now().weekday() == 3


def _entry_edge_min(h: int, m: int) -> float:
    if _is_thursday():
        return 0.10
    if (h, m) >= TIER2_ENTRY_HOUR_CUTOFF:  # 13:30–14:00
        return 0.20
    if (h, m) >= TIER1_ENTRY_HOUR_CUTOFF:  # 12:00–13:30
        return 0.15
    if _is_late_entry(h, m):               # 10:30–12:00
        return 0.08
    return 0.05


def _entry_spread_max(h: int, m: int) -> float:
    return 10.0 if _is_late_entry(h, m) else 15.0


# ── VIX helpers ────────────────────────────────────────────────────────────────

def _fetch_vix_change() -> tuple[float | None, bool]:
    """Fetch VIX change (current vs prev close). Returns (vix_change, vix_high).

    Uses fast_info.last_price for the current VIX level — daily Open bars return 0
    early in the session before the VIX market opens, which caused 0.0 all day.
    Falls back to bars["Close"].iloc[-1] if fast_info is unavailable.
    """
    try:
        ticker = yf.Ticker("^VIX")
        bars = ticker.history(period="5d", interval="1d")
        if len(bars) < 2:
            return None, False
        vix_prev_close = float(bars["Close"].iloc[-2])
        if vix_prev_close <= 0:
            return None, False
        cur = getattr(ticker.fast_info, "last_price", None)
        if not cur or cur <= 0:
            cur = float(bars["Close"].iloc[-1])
        if not cur or cur <= 0:
            return None, False
        change = round(cur - vix_prev_close, 2)
        high   = cur > VIX_HIGH_THRESHOLD
        return change, high
    except Exception:
        return None, False


def _vix_zone() -> str:
    vc = state._vix_change
    if vc is None:
        return "UNKNOWN"
    if VIX_CHANGE_BULLISH_LO <= vc <= VIX_CHANGE_BULLISH_HI:
        return "BULLISH"
    if vc > VIX_CHANGE_BEARISH_MIN:
        return "BEARISH"
    return "NEUTRAL"


# ── Signal helpers ─────────────────────────────────────────────────────────────

def _spread_pct(bid: float, ask: float) -> float | None:
    if bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return round((ask - bid) / mid * 100.0, 1)


def _est_edge(
    ticker: str,
    gap_bps: int | None,
    yes_ask: float | None,
    no_ask: float | None,
) -> float | None:
    if gap_bps is None or gap_bps == 0:
        return None
    wr = state.wr_cache.get(ticker)
    if not wr:
        return None
    yes_wr, no_wr = wr
    payout = 1.0 - TRADING_FEE_PCT
    if gap_bps > 0:
        if yes_ask is None or yes_ask <= 0:
            return None
        return round(yes_wr * payout - yes_ask, 4)
    else:
        if no_ask is None or no_ask <= 0:
            return None
        return round(no_wr * payout - no_ask, 4)


def _compute_signal(
    ticker: str,
    gap_bps: int | None,
    gfr: float | None,
    live_edge: float | None,
) -> str:
    """Compute the per-tick signal. Uses per-ticker gap threshold from config."""
    threshold_bps = round(TICKER_GAP_THRESHOLD.get(ticker, 0.005) * 10_000)
    if not gap_bps or abs(gap_bps) <= threshold_bps:
        return "FLAT"
    if gfr is not None and gfr < -0.3:
        return "FADE"
    if live_edge is None:
        return "WAIT"
    if live_edge < 0:
        return "SKIP"
    if live_edge >= 0.03:
        return "GO"
    return "WATCH"


# ── Reversal entry ─────────────────────────────────────────────────────────────

def _check_reversal_entry(ticker: str, q: dict, h: int, m: int) -> dict | None:
    """NO entry when a gap-UP day fully reverses (GFR < -1.0).

    Called from _check_entry when gap_bps > threshold and gfr < -1.0.
    Uses per-ticker reversal win rates rather than the cached no_wr.
    """
    if _entry_frozen(h, m):
        return None
    if ticker in state._session_aborted:
        return None

    no_ask = q.get("no_ask")
    if not no_ask or no_ask < 0.40 or no_ask > 0.70:
        return None

    spread = q.get("no_spread")
    if spread is None or spread > _entry_spread_max(h, m):
        return None

    rev_wr    = REVERSAL_NO_WR.get(ticker, REVERSAL_NO_WR_DEFAULT)
    payout    = 1.0 - TRADING_FEE_PCT
    live_edge = round(rev_wr * payout - no_ask, 4)
    edge_min  = max(REVERSAL_EDGE_MIN, _entry_edge_min(h, m))
    if live_edge < edge_min:
        return None

    return {
        "ticker":      ticker,
        "side":        "NO",
        "entry_price": round(no_ask, 4),
        "live_edge":   live_edge,
        "adj_wr":      round(rev_wr, 4),
        "settlement_p": None,
        "gap_bps":     q.get("gap_bps"),
        "tag":         "REVERSAL",
        "late":        _is_late_entry(h, m),
        "thursday":    _is_thursday(),
        "vix_change":  state._vix_change,
        "vix_high":    state._vix_high,
    }


# ── Entry decision ─────────────────────────────────────────────────────────────

def _check_entry(
    ticker: str, q: dict, h: int, m: int, reentry: bool = False
) -> dict | None:
    """Return an entry signal dict if all conditions are met, else None.

    Direction is determined by the settlement model's P(YES):
      - P(YES) ≥ SETTLEMENT_YES_THRESHOLD  → trade YES
      - P(YES) ≤ 1 - SETTLEMENT_YES_THRESHOLD → trade NO
      - Dead-zone in between → skip
    No SPRT or 3-of-4 signal accumulation required.
    """
    if not reentry and ticker in state._session_entered:
        return None
    if ticker in state._session_aborted:
        return None

    gap_bps = q.get("gap_bps") or 0
    threshold_bps = round(TICKER_GAP_THRESHOLD.get(ticker, 0.005) * 10_000)
    if abs(gap_bps) <= threshold_bps:
        return None

    gap_up = gap_bps > 0
    gfr    = q.get("gfr")

    # Reversal path: gap-UP day, stock crossed prev_close.
    if gap_up and gfr is not None and gfr < -1.0:
        return _check_reversal_entry(ticker, q, h, m)

    # ── Model-driven direction ─────────────────────────────────────────────
    settlement_p = q.get("settlement_p_win")
    if settlement_p is None:
        # Model hasn't fired yet (first few ticks); fall back to gap direction
        # with the Bayesian adj_wr as the win-rate estimate.
        settlement_p = None

    payout   = 1.0 - TRADING_FEE_PCT
    edge_min = max(_entry_edge_min(h, m), 0.08 if reentry else 0.0)

    # Determine side and compute live edge from model probability
    if settlement_p is not None:
        if settlement_p >= SETTLEMENT_YES_THRESHOLD:
            side        = "YES"
            entry_price = q.get("yes_ask")
            if not entry_price:
                return None
            live_edge = round(settlement_p * payout - entry_price, 4)
        elif settlement_p <= (1.0 - SETTLEMENT_YES_THRESHOLD):
            side        = "NO"
            entry_price = q.get("no_ask")
            if not entry_price:
                return None
            live_edge = round((1.0 - settlement_p) * payout - entry_price, 4)
        else:
            return None  # model uncertain — skip
    else:
        # Fallback: use gap direction + adj_wr (model not yet available)
        adj_wr = q.get("adj_wr")
        if adj_wr is None:
            return None
        side        = "YES" if gap_up else "NO"
        entry_price = q.get("yes_ask") if side == "YES" else q.get("no_ask")
        if not entry_price:
            return None
        live_edge = q.get("live_edge") or q.get("est_edge")
        if live_edge is None:
            return None

    # NO entry GFR gate: skip NO entry if stock bounced hard above prev_close
    if side == "NO" and gfr is not None and gfr < GFR_NO_ENTRY_MIN:
        return None

    if live_edge < edge_min:
        return None

    # Price sanity: token must be in tradeable range
    if not entry_price or entry_price > 0.90 or entry_price < 0.40:
        return None

    spread     = q.get("yes_spread") if side == "YES" else q.get("no_spread")
    spread_max = min(_entry_spread_max(h, m), 10.0 if reentry else 999.0)
    if spread is None or spread > spread_max:
        return None

    # VIX adjustment (YES trades only)
    if side == "YES" and state._vix_change is not None:
        if VIX_CHANGE_BULLISH_LO <= state._vix_change <= VIX_CHANGE_BULLISH_HI:
            edge_min = max(0.01, edge_min - VIX_BULLISH_EDGE_DISCOUNT)
        elif state._vix_change > VIX_CHANGE_BEARISH_MIN:
            edge_min += VIX_BEARISH_EDGE_PENALTY
        if live_edge < edge_min:
            return None

    adj_wr_for_db = (
        round(settlement_p, 4) if settlement_p is not None
        else (q.get("adj_wr") or 0.60)
    )

    return {
        "ticker":      ticker,
        "side":        side,
        "entry_price": round(entry_price, 4),
        "live_edge":   round(live_edge, 4),
        "adj_wr":      adj_wr_for_db,
        "settlement_p": settlement_p,
        "gap_bps":     gap_bps,
        "tag":         "MODEL" if settlement_p is not None else "FALLBACK",
        "late":        _is_late_entry(h, m),
        "thursday":    _is_thursday(),
        "vix_change":  state._vix_change,
        "vix_high":    state._vix_high,
    }


# ── Exit decision ──────────────────────────────────────────────────────────────

def _check_exit(
    ticker: str, q: dict, position: dict, h: int, m: int, no_peak: float = 0.0
) -> dict | None:
    """Return an exit signal dict if any threshold is triggered, else None."""
    fired       = state._exit_triggers_fired.get(ticker, set())
    entry_price = position.get("entry_price") or 0
    if not entry_price:
        return None

    side        = position.get("entry_side", "YES")
    current_bid = q.get("yes_bid") if side == "YES" else q.get("no_bid")
    if not current_bid:
        return None

    gfr        = q.get("gfr")
    adj_wr     = q.get("adj_wr")
    payout     = 1.0 - TRADING_FEE_PCT
    profit_pct = (current_bid - entry_price) / entry_price

    # 1. Hard 3pm exit
    if (h, m) >= HARD_EXIT_ET and "hard_3pm" not in fired:
        return {"reason": "hard_3pm", "fraction": 1.0,
                "price": current_bid, "profit_pct": profit_pct}

    # 2. NO trade intraday protection
    if side == "NO":
        if current_bid >= entry_price + NO_PROFIT_LOCK_GAIN and "no_profit_lock" not in fired:
            return {"reason": "no_profit_lock", "fraction": NO_PROFIT_LOCK_FRAC,
                    "price": current_bid, "profit_pct": profit_pct}
        if (no_peak >= entry_price + NO_TRAIL_MIN_PEAK
                and current_bid <= no_peak - NO_TRAIL_STOP_DROP
                and "no_trail_stop" not in fired):
            return {"reason": "no_trail_stop", "fraction": NO_TRAIL_STOP_FRAC,
                    "price": current_bid, "profit_pct": profit_pct}

    # 3. Settlement model exits — per-side
    s_p_win = q.get("settlement_p_win")
    if s_p_win is not None:
        if side == "YES":
            s_edge = s_p_win * payout - current_bid
            if s_p_win < 0.45 and "settlement_urgent" not in fired:
                return {"reason": "settlement_urgent", "fraction": 1.0,
                        "price": current_bid, "profit_pct": profit_pct}
        else:  # side == "NO"
            p_no   = 1.0 - s_p_win
            s_edge = p_no * payout - current_bid
            if s_p_win > 0.55 and "settlement_urgent" not in fired:
                return {"reason": "settlement_urgent", "fraction": 1.0,
                        "price": current_bid, "profit_pct": profit_pct}

        if s_edge <= 0 and "settlement_edge_gone" not in fired:
            return {"reason": "settlement_edge_gone", "fraction": 0.80,
                    "price": current_bid, "profit_pct": profit_pct}

    # 4. Edge-exhaustion profit lock (adj_wr fallback, no settlement model)
    if (s_p_win is None and adj_wr is not None and profit_pct >= 0.15
            and gfr is not None and gfr < 0 and "edge_exhausted" not in fired):
        if adj_wr * payout - current_bid <= 0:
            return {"reason": "edge_exhausted_profit_lock", "fraction": 0.85,
                    "price": current_bid, "profit_pct": profit_pct}

    # 5. Tiered time exits
    if (h, m) >= (15, 0) and "time_exit_3pm" not in fired:
        return {"reason": "time_exit_3pm", "fraction": 1.0,
                "price": current_bid, "profit_pct": profit_pct}
    if (h, m) >= (14, 30) and "time_exit_230" not in fired:
        # Hold through 2:30 only if bid is near-certain win AND model highly confident
        if not (current_bid >= 0.85 and s_p_win is not None and s_p_win >= 0.80):
            return {"reason": "time_exit_230", "fraction": 1.0,
                    "price": current_bid, "profit_pct": profit_pct}
    if (h, m) >= (14, 0) and "time_exit_2pm" not in fired:
        if not (current_bid >= 0.85 and s_p_win is not None and s_p_win >= 0.85):
            return {"reason": "time_exit_2pm", "fraction": 1.0,
                    "price": current_bid, "profit_pct": profit_pct}

    return None
