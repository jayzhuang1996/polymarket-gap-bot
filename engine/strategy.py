"""Trading strategy — time helpers, signal computation, entry/exit decisions.

Pure-ish functions: they read session state from engine.state but contain
no I/O (no network calls, no DB writes) other than the VIX yfinance fetch.
"""

import datetime as _dt

import yfinance as yf

import engine.state as state
from config import (
    TRADING_FEE_PCT, BAYES_LAMBDA,
    SPRT_YES_PARAMS, SPRT_ENTER_LR, SPRT_ABORT_LR,
    VIX_HIGH_THRESHOLD,
    VIX_CHANGE_BULLISH_LO, VIX_CHANGE_BULLISH_HI,
    VIX_CHANGE_BEARISH_MIN, VIX_BULLISH_EDGE_DISCOUNT, VIX_BEARISH_EDGE_PENALTY,
    NO_PROFIT_LOCK_GAIN, NO_PROFIT_LOCK_FRAC,
    NO_TRAIL_STOP_DROP, NO_TRAIL_STOP_FRAC, NO_TRAIL_MIN_PEAK,
    TICKER_GFR_EXIT_SHALLOW, TICKER_GFR_EXIT_DEEP,
    GFR_EXIT_FRAC_YES_SHALLOW, GFR_EXIT_FRAC_YES_DEEP,
    GFR_EXIT_FRAC_NO_SHALLOW, GFR_EXIT_FRAC_NO_DEEP,
    GFR_NO_ENTRY_MIN,
)

# ── Session constants ──────────────────────────────────────────────────────────
ENTRY_CONFIRMATIONS_NEEDED = 3
LATE_ENTRY_HOUR_CUTOFF     = (10, 30)
HARD_EXIT_ET               = (15, 0)
ET_OFFSET_H                = -4        # EDT (Mar–Nov)
GFR_COOLDOWN_MINUTES       = 30
FULLY_EXITED_THRESHOLD     = 0.05


# ── Time helpers ───────────────────────────────────────────────────────────────

def _et_now_hm() -> tuple[int, int]:
    utc = _dt.datetime.now(_dt.timezone.utc)
    et  = utc.replace(tzinfo=None) + _dt.timedelta(hours=ET_OFFSET_H)
    return et.hour, et.minute


def _in_market_hours() -> bool:
    h, m = _et_now_hm()
    return (9, 30) <= (h, m) <= HARD_EXIT_ET


def _entry_frozen(h: int, m: int) -> bool:
    return (h, m) >= (12, 0)


def _is_late_entry(h: int, m: int) -> bool:
    return (h, m) >= LATE_ENTRY_HOUR_CUTOFF


def _is_thursday() -> bool:
    return _dt.datetime.now().weekday() == 3


def _entry_edge_min(h: int, m: int) -> float:
    if _is_thursday():
        return 0.10
    if _is_late_entry(h, m):
        return 0.08
    return 0.05


def _entry_spread_max(h: int, m: int) -> float:
    return 10.0 if _is_late_entry(h, m) else 15.0


# ── VIX helpers ────────────────────────────────────────────────────────────────

def _fetch_vix_change() -> tuple[float | None, bool]:
    """Fetch VIX at session start. Returns (vix_change, vix_high)."""
    try:
        bars = yf.Ticker("^VIX").history(period="5d", interval="1d")
        if len(bars) < 2:
            return None, False
        vix_prev_close  = float(bars["Close"].iloc[-2])
        vix_open_today  = float(bars["Open"].iloc[-1])
        vix_close_today = float(bars["Close"].iloc[-1])
        change = round(vix_open_today - vix_prev_close, 2)
        high   = vix_close_today > VIX_HIGH_THRESHOLD
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
    gap_bps: int | None,
    gfr: float | None,
    live_edge: float | None,
) -> str:
    if not gap_bps or abs(gap_bps) <= 50:
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


# ── Entry decision ─────────────────────────────────────────────────────────────

def _check_entry(
    ticker: str, q: dict, h: int, m: int, reentry: bool = False
) -> dict | None:
    """Return an entry signal dict if all conditions are met, else None."""
    if not reentry and ticker in state._session_entered:
        return None
    if ticker in state._session_aborted:
        return None
    gap_bps = q.get("gap_bps") or 0
    if abs(gap_bps) <= 50:
        return None

    gap_up  = gap_bps > 0
    history = state._signal_history.get(ticker, [])

    sprt_params = SPRT_YES_PARAMS.get(ticker) if gap_up else None
    if sprt_params:
        p1, p0 = sprt_params
        lr = 1.0
        for sig in history:
            lr *= p1 / p0 if sig == "GO" else (1 - p1) / (1 - p0)
        if lr <= SPRT_ABORT_LR:
            state._session_aborted.add(ticker)
            return None
        if lr < SPRT_ENTER_LR:
            return None
    else:
        go_count = sum(1 for s in history[-4:] if s == "GO")
        if go_count < ENTRY_CONFIRMATIONS_NEEDED:
            return None

    if not gap_up:
        gfr = q.get("gfr")
        if gfr is not None and gfr < GFR_NO_ENTRY_MIN:
            return None

    edge_min   = max(_entry_edge_min(h, m),   0.08 if reentry else 0.0)
    spread_max = min(_entry_spread_max(h, m), 10.0 if reentry else 999.0)

    if gap_up and state._vix_change is not None:
        if VIX_CHANGE_BULLISH_LO <= state._vix_change <= VIX_CHANGE_BULLISH_HI:
            edge_min = max(0.01, edge_min - VIX_BULLISH_EDGE_DISCOUNT)
        elif state._vix_change > VIX_CHANGE_BEARISH_MIN:
            edge_min += VIX_BEARISH_EDGE_PENALTY

    live_edge = q.get("live_edge") or q.get("est_edge")
    if live_edge is None or live_edge < edge_min:
        return None

    side   = "YES" if gap_up else "NO"
    spread = q.get("yes_spread") if side == "YES" else q.get("no_spread")
    if spread is None or spread > spread_max:
        return None

    entry_price = q.get("yes_ask") if side == "YES" else q.get("no_ask")
    if not entry_price or entry_price > 0.70 or entry_price < 0.40:
        return None

    adj_wr   = q.get("adj_wr")
    go_count = sum(1 for s in history[-4:] if s == "GO")
    tag = "SPRT" if sprt_params else ("EARLY" if go_count == 4 else "CONFIRMED")
    return {
        "ticker":      ticker,
        "side":        side,
        "entry_price": round(entry_price, 4),
        "live_edge":   round(live_edge, 4),
        "adj_wr":      round(adj_wr, 4) if adj_wr else None,
        "gap_bps":     gap_bps,
        "go_signals":  go_count,
        "tag":         tag,
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

    # 2. GFR-based exits
    if gfr is not None:
        gfr_shallow = TICKER_GFR_EXIT_SHALLOW.get(ticker, -0.5)
        gfr_deep    = TICKER_GFR_EXIT_DEEP.get(ticker, -0.8)
        f_shallow   = GFR_EXIT_FRAC_YES_SHALLOW if side == "YES" else GFR_EXIT_FRAC_NO_SHALLOW
        f_deep      = GFR_EXIT_FRAC_YES_DEEP    if side == "YES" else GFR_EXIT_FRAC_NO_DEEP
        if f_deep > 0 and gfr < gfr_deep and "gfr_08" not in fired:
            return {"reason": "gfr<-0.8_reversed", "fraction": f_deep,
                    "price": current_bid, "profit_pct": profit_pct}
        if f_shallow > 0 and gfr < gfr_shallow and "gfr_05" not in fired:
            return {"reason": "gfr<-0.5_fading", "fraction": f_shallow,
                    "price": current_bid, "profit_pct": profit_pct}

    # 3. NO trade intraday protection
    if side == "NO":
        if current_bid >= entry_price + NO_PROFIT_LOCK_GAIN and "no_profit_lock" not in fired:
            return {"reason": "no_profit_lock", "fraction": NO_PROFIT_LOCK_FRAC,
                    "price": current_bid, "profit_pct": profit_pct}
        if (no_peak >= entry_price + NO_TRAIL_MIN_PEAK
                and current_bid <= no_peak - NO_TRAIL_STOP_DROP
                and "no_trail_stop" not in fired):
            return {"reason": "no_trail_stop", "fraction": NO_TRAIL_STOP_FRAC,
                    "price": current_bid, "profit_pct": profit_pct}

    # 4. Settlement model exits
    s_p_win = q.get("settlement_p_win")
    s_edge  = q.get("settlement_edge")
    if s_p_win is not None:
        if s_p_win < 0.45 and "settlement_urgent" not in fired:
            return {"reason": "settlement_urgent", "fraction": 1.0,
                    "price": current_bid, "profit_pct": profit_pct}
        if s_edge is not None and s_edge <= 0 and "settlement_edge_gone" not in fired:
            return {"reason": "settlement_edge_gone", "fraction": 0.80,
                    "price": current_bid, "profit_pct": profit_pct}

    # 5. Edge-exhaustion profit lock (Bayesian WR path, no settlement model)
    if (s_p_win is None and adj_wr is not None and profit_pct >= 0.15
            and gfr is not None and gfr < 0 and "edge_exhausted" not in fired):
        if adj_wr * payout - current_bid <= 0:
            return {"reason": "edge_exhausted_profit_lock", "fraction": 0.85,
                    "price": current_bid, "profit_pct": profit_pct}

    # 6. Tiered time exits
    if (h, m) >= (15, 0) and "time_exit_3pm" not in fired:
        return {"reason": "time_exit_3pm", "fraction": 1.0,
                "price": current_bid, "profit_pct": profit_pct}
    if (h, m) >= (14, 30) and "time_exit_230" not in fired:
        if not (current_bid >= 0.85 and gfr is not None and gfr >= 0.2):
            return {"reason": "time_exit_230", "fraction": 1.0,
                    "price": current_bid, "profit_pct": profit_pct}
    if (h, m) >= (14, 0) and "time_exit_2pm" not in fired:
        if not (current_bid >= 0.85 and gfr is not None and gfr >= 0.5):
            return {"reason": "time_exit_2pm", "fraction": 1.0,
                    "price": current_bid, "profit_pct": profit_pct}

    return None
