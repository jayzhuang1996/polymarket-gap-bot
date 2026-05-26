"""
Settlement probability model — runtime inference.

Loads the logistic regression bundle from data/settlement_model.pkl and
provides predict() for use in the trading session loop.

Features (must match tools/train_settlement_model.py):
    gfr           gap fill ratio, clipped [-3, 3]
    gfr_velocity  2-min change in gfr, clipped [-1, 1]
    log_tbf       log1p(tbf_min)
    gap_abs       abs(gap_pct), clipped at 0.15
    market_p_win  P(our trade wins) per the market: yes_vwap if gap_up else 1-yes_vwap
    dow_thu       1 if Thursday
    vix_high      1 if VIX > 20 today (passed from session-start VIX fetch)

Output:
    p_win     — model's P(trade wins), range [0, 1]
    live_edge — p_win * 0.99 - current_token_bid
                Positive = still has edge; negative = edge gone, consider exiting.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Optional

import numpy as np

_MODEL_PATH = Path("data/settlement_model.pkl")
_bundle: Optional[dict] = None
_load_attempted = False

_FEATURE_ORDER = [
    "gfr", "gfr_velocity", "log_tbf", "gap_abs",
    "market_p_win", "dow_thu", "vix_high",
]

_PAYOUT = 0.99  # 1% Polymarket fee


def _load() -> bool:
    global _bundle, _load_attempted
    if _load_attempted:
        return _bundle is not None
    _load_attempted = True
    try:
        with open(_MODEL_PATH, "rb") as f:
            _bundle = pickle.load(f)
        return True
    except Exception:
        return False


def is_available() -> bool:
    return _load()


def predict(
    gfr: float,
    gfr_velocity: float,
    tbf_min: float,
    gap_pct: float,
    yes_vwap: float,
    dow: str,
    vix_high: bool,
    current_token_bid: float,
) -> tuple[float, float]:
    """Return (p_win, live_edge) for the current position.

    Args:
        gfr:               Gap fill ratio (server.py computes this every 5s).
        gfr_velocity:      Change in gfr since 2 minutes ago.
        tbf_min:           Minutes before market expiry (390 at open, 2 at close).
        gap_pct:           Overnight gap as fraction: (open-prev_close)/prev_close.
                           Positive = gap up, negative = gap down.
        yes_vwap:          Current YES token VWAP (best proxy for token fair value).
        dow:               Day-of-week abbreviation: "Mon"/"Tue"/"Wed"/"Thu"/"Fri".
        vix_high:          True if VIX > 20 today (fetched once at session start).
        current_token_bid: Bid price of the token we hold (YES bid if gap_up, NO bid
                           if gap_down). Used to compute live_edge.

    Returns:
        p_win     — model probability our trade wins (0.0–1.0).
        live_edge — p_win * 0.99 − current_token_bid.
                    > 0.05: hold, edge intact.
                    0–0.05: watch, edge thin.
                    < 0: exit, market priced past our estimate.
    """
    if not _load():
        # Model file missing — return neutral estimate based on market price
        p_win = yes_vwap if gap_pct > 0 else (1.0 - yes_vwap)
        return round(p_win, 4), round(p_win * _PAYOUT - current_token_bid, 4)

    gap_up       = gap_pct > 0
    market_p_win = yes_vwap if gap_up else (1.0 - yes_vwap)

    row = np.array([[
        float(np.clip(gfr,          -3.0, 3.0)),
        float(np.clip(gfr_velocity, -1.0, 1.0)),
        float(np.log1p(max(tbf_min, 0))),
        float(np.clip(abs(gap_pct),  0.0, 5.0)),
        float(np.clip(market_p_win,  0.0, 1.0)),
        float(dow == "Thu"),
        float(vix_high),
    ]])

    scaler = _bundle["scaler"]
    model  = _bundle["model"]
    X_s    = scaler.transform(row)
    p_win  = float(model.predict_proba(X_s)[0, 1])
    p_win  = float(np.clip(p_win, 0.01, 0.99))

    live_edge = round(p_win * _PAYOUT - current_token_bid, 4)
    return round(p_win, 4), live_edge


def reload() -> bool:
    """Force reload model from disk (call after retraining)."""
    global _bundle, _load_attempted
    _bundle = None
    _load_attempted = False
    return _load()
