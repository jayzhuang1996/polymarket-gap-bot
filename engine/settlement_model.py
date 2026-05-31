"""Settlement probability model — runtime inference.

Loads the logistic regression bundle from data/settlement_model.pkl and
provides predict() for use in the trading session loop.

Features (must match tools/train_settlement_model.py):
    gfr                    gap fill ratio, clipped [-3, 3]
    gfr_velocity           2-min GFR change, clipped [-1, 1]
    log_tbf                log1p(tbf_min)
    gap_abs                abs(gap_pct), clipped [0, 5]
    market_p_win           yes_vwap if gap_up else (1 - yes_vwap)
    dow_thu                1 if Thursday
    vix_high               1 if VIX > 20
    stock_pct_vs_prevclose (current_price - prev_close) / prev_close * 100, clipped [-15, 15]

Output:
    p_yes       P(YES settles) — range [0, 1].
    live_edge   Caller computes: p_yes * 0.99 - yes_ask  (YES trade)
                                 (1-p_yes) * 0.99 - no_ask  (NO trade)
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
    "gfr", "gfr_velocity", "log_tbf", "gap_abs", "market_p_win",
    "dow_thu", "vix_high", "stock_pct_vs_prevclose",
]
_PAYOUT = 0.99


def _load() -> bool:
    global _bundle, _load_attempted
    if _load_attempted:
        return _bundle is not None
    _load_attempted = True
    try:
        with open(_MODEL_PATH, "rb") as f:
            _bundle = pickle.load(f)
        if _bundle.get("feature_names") != _FEATURE_ORDER:
            print(f"[settlement_model] WARNING: bundle features {_bundle.get('feature_names')} "
                  f"!= expected {_FEATURE_ORDER} — model disabled until retrain")
            _bundle = None
            return False
        return True
    except Exception as e:
        print(f"[settlement_model] failed to load: {e}")
        return False


def is_available() -> bool:
    return _load()


def predict(
    gfr: float,
    gfr_velocity: float,
    tbf_min: float,
    gap_pct: float,
    yes_vwap: float,
    gap_up: bool,
    dow: str,
    vix_high: bool,
    stock_pct_vs_prevclose: float,
    current_token_bid: float,
    **_kwargs,
) -> tuple[float, float]:
    """Return (p_yes, live_edge_for_yes_token).

    Args:
        gfr:                    Gap fill ratio — (current_price - open) / (open - prev_close).
        gfr_velocity:           Change in gfr over the last 2-min tick.
        tbf_min:                Minutes before market expiry (390 at open, 2 at close).
        gap_pct:                Overnight gap as a percentage (e.g. 2.1 for +2.1%).
        yes_vwap:               Current YES token VWAP.
        gap_up:                 True if overnight gap was positive.
        dow:                    Day-of-week abbreviation: "Mon"/"Tue"/"Wed"/"Thu"/"Fri".
        vix_high:               True if VIX > 20 at session start.
        stock_pct_vs_prevclose: (current_price - prev_close) / prev_close * 100.
        current_token_bid:      YES token bid price (used to compute live_edge).

    Returns:
        p_yes     — P(YES settles), range [0.01, 0.99].
        live_edge — p_yes * 0.99 - current_token_bid  (YES trade edge only).
                    For NO trade edge: compute (1 - p_yes) * 0.99 - no_bid in caller.
    """
    if not _load():
        p_yes = float(np.clip(yes_vwap, 0.01, 0.99))
        return p_yes, round(p_yes * _PAYOUT - current_token_bid, 4)

    market_p_win = yes_vwap if gap_up else (1.0 - yes_vwap)

    row = np.array([[
        float(np.clip(gfr,                    -3.0,  3.0)),
        float(np.clip(gfr_velocity,           -1.0,  1.0)),
        float(np.log1p(max(tbf_min, 0))),
        float(np.clip(abs(gap_pct),            0.0,  5.0)),
        float(np.clip(market_p_win,            0.0,  1.0)),
        float(dow == "Thu"),
        float(bool(vix_high)),
        float(np.clip(stock_pct_vs_prevclose, -15.0, 15.0)),
    ]])

    X_s   = _bundle["scaler"].transform(row)
    p_yes = float(_bundle["model"].predict_proba(X_s)[0, 1])
    p_yes = float(np.clip(p_yes, 0.01, 0.99))

    live_edge = round(p_yes * _PAYOUT - current_token_bid, 4)
    return round(p_yes, 4), live_edge


def reload() -> bool:
    """Force reload model from disk (call after retraining)."""
    global _bundle, _load_attempted
    _bundle = None
    _load_attempted = False
    return _load()
