"""Settlement probability model — runtime inference.

Loads the logistic regression bundle from data/settlement_model.pkl and
provides predict() for use in the trading session loop.

Features (must match tools/train_settlement_model.py / retraining script):
    stock_pos   stock_pct_vs_prevclose: (current_price - prev_close) / prev_close * 100
                = gap_pct_pct * (1 + gfr).  Positive = stock above prev_close.
    momentum    Change in stock_pos over the last 30 min (15 × 2-min ticks).
    log_tbf     log1p(tbf_min)
    yes_vwap    Current YES token VWAP — market's P(YES) estimate.
    dow_thu     1 if Thursday

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

_FEATURE_ORDER = ["stock_pos", "momentum", "log_tbf", "yes_vwap", "dow_thu"]
_PAYOUT = 0.99


def _load() -> bool:
    global _bundle, _load_attempted
    if _load_attempted:
        return _bundle is not None
    _load_attempted = True
    try:
        with open(_MODEL_PATH, "rb") as f:
            _bundle = pickle.load(f)
        # Validate bundle has expected features
        if _bundle.get("feature_names") != _FEATURE_ORDER:
            print(f"[settlement_model] WARNING: bundle features {_bundle.get('feature_names')} "
                  f"!= expected {_FEATURE_ORDER} — predictions may be wrong")
        return True
    except Exception as e:
        print(f"[settlement_model] failed to load: {e}")
        return False


def is_available() -> bool:
    return _load()


def predict(
    stock_pct_vs_prevclose: float,
    momentum_30min: float,
    tbf_min: float,
    yes_vwap: float,
    dow: str,
    current_token_bid: float,
    **_kwargs,  # absorb legacy keyword args from old callers
) -> tuple[float, float]:
    """Return (p_yes, live_edge_for_yes_token).

    Args:
        stock_pct_vs_prevclose: (current_price - prev_close) / prev_close * 100.
            Positive = stock above yesterday's close.
            Computed live as: gap_pct_fraction * 100 * (1 + gfr).
        momentum_30min: change in stock_pct_vs_prevclose over last 30 min.
            Positive = stock moving further above prev_close.
        tbf_min:  Minutes before market expiry (390 at open, 2 at close).
        yes_vwap: Current YES token VWAP — market's best estimate of P(YES).
        dow:      Day-of-week abbreviation: "Mon"/"Tue"/"Wed"/"Thu"/"Fri".
        current_token_bid: Bid price of the YES token (used to compute live_edge).

    Returns:
        p_yes     — P(YES settles), range [0.01, 0.99].
        live_edge — p_yes * 0.99 - current_token_bid.
                    Use this for YES trade edge only.
                    For NO trade edge: compute (1 - p_yes) * 0.99 - no_bid in caller.
    """
    if not _load():
        # No model file — fall back to market estimate
        p_yes = float(np.clip(yes_vwap, 0.01, 0.99))
        return p_yes, round(p_yes * _PAYOUT - current_token_bid, 4)

    row = np.array([[
        float(np.clip(stock_pct_vs_prevclose, -15.0, 15.0)),
        float(np.clip(momentum_30min,         -10.0, 10.0)),
        float(np.log1p(max(tbf_min, 0))),
        float(np.clip(yes_vwap,                0.0,  1.0)),
        float(dow == "Thu"),
    ]])

    scaler = _bundle["scaler"]
    model  = _bundle["model"]
    X_s    = scaler.transform(row)
    p_yes  = float(model.predict_proba(X_s)[0, 1])
    p_yes  = float(np.clip(p_yes, 0.01, 0.99))

    live_edge = round(p_yes * _PAYOUT - current_token_bid, 4)
    return round(p_yes, 4), live_edge


def reload() -> bool:
    """Force reload model from disk (call after retraining)."""
    global _bundle, _load_attempted
    _bundle = None
    _load_attempted = False
    return _load()
