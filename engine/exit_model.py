"""
Calibrated exit price estimator.

Lookup priority:
  1. (time_bucket, gfr_bucket, "ALL", gap_bucket) — gap-segmented, pooled dow
  2. (time_bucket, gfr_bucket, dow,   "ALL")       — day-specific, no gap dim
  3. (time_bucket, gfr_bucket, "ALL", "ALL")        — pooled, no gap dim
  4. Linear formula                                  — final fallback

gap_bucket: "small" (0.5–2% gap) or "large" (≥2% gap).
  A 0.5% gap with GFR=0 at 11:30am is a fully-filled gap → token near 50¢.
  A 3% gap with GFR=0 at 11:30am is a complete reversal → token much lower.
  Same (time, gfr) cell hides a 10–20¢ difference between these two cases.

The calibration table is built by running:
  python tools/calibrate_exit_model.py
Output: data/exit_model_calibration.csv (rebuilt nightly by eod_update.py cron)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

_CAL_PATH        = Path("data") / "exit_model_calibration.csv"
_MIN_OBS         = 5    # min obs for dow-specific and pooled-no-gap cells
_MIN_GAP_OBS     = 10   # higher bar for gap-segmented cells (sparser)
_DISCOUNT        = 0.05  # CLOB exit discount: paper mid → real bid haircut
_table: Optional[pd.DataFrame] = None
_table_loaded    = False

_BUCKETS = ["10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00"]


def _load_table() -> Optional[pd.DataFrame]:
    global _table, _table_loaded
    if _table_loaded:
        return _table
    _table_loaded = True
    if not _CAL_PATH.exists():
        return None
    try:
        _table = pd.read_csv(_CAL_PATH)
        # Back-compat: old tables without gap_bucket column
        if "gap_bucket" not in _table.columns:
            _table["gap_bucket"] = "ALL"
        return _table
    except Exception:
        return None


def _linear_formula(gfr: float, entry_price: float) -> float:
    if gfr >= 0:
        est = entry_price + (1.0 - entry_price) * min(gfr, 1.0)
    else:
        est = entry_price + entry_price * max(gfr, -1.0)
    return max(0.0, min(1.0, est))


def _lookup(
    table: pd.DataFrame,
    bucket: str,
    gfr: float,
    dow: str,
    gap_bucket: str,
    min_obs: int,
) -> Optional[float]:
    cell = table[
        (table["time_bucket"] == bucket) &
        (table["gfr_lo"] <= gfr) &
        (table["gfr_hi"] > gfr) &
        (table["dow"] == dow) &
        (table["gap_bucket"] == gap_bucket) &
        (table["n_obs"] >= min_obs)
    ]
    if len(cell) > 0:
        return float(cell.iloc[0]["avg_yes_price"])
    return None


def _gap_label(abs_gap_pct: float) -> str:
    """Map absolute gap percentage to the bucket label used in the calibration table."""
    return "large" if abs_gap_pct >= 2.0 else "small"


def estimate_token_price(
    time_et: str,
    gfr: float,
    entry_price: float,
    dow: str = "ALL",
    abs_gap_pct: float = 0.0,
) -> tuple[float, str]:
    """Estimate current YES token price given time-of-day, GFR, day-of-week, gap size.

    Args:
        time_et:      Current ET time as "HH:MM", e.g. "11:30".
        gfr:          gap_fill_ratio. Positive = gap holding. Negative = reversing.
        entry_price:  Original entry price (used for linear formula fallback).
        dow:          Day of week abbreviation or "ALL".
        abs_gap_pct:  Absolute overnight gap in percent units (e.g. 1.5 = 1.5%).
                      Used to select gap_bucket. Defaults to 0 → "small" bucket.

    Returns:
        (est_price, source) where source describes which lookup tier fired.
        est_price has the CLOB exit discount applied.
    """
    table = _load_table()

    bucket = _BUCKETS[0]
    for b in _BUCKETS:
        if time_et >= b:
            bucket = b

    gap_bucket = _gap_label(abs_gap_pct)
    est_price: Optional[float] = None
    source = "formula"

    if table is not None:
        # Tier 1: gap-segmented, pooled dow
        est_price = _lookup(table, bucket, gfr, "ALL", gap_bucket, _MIN_GAP_OBS)
        if est_price is not None:
            source = f"table_gap_{gap_bucket}"

        # Tier 2: dow-specific, no gap dim
        if est_price is None and dow != "ALL":
            est_price = _lookup(table, bucket, gfr, dow, "ALL", _MIN_OBS)
            if est_price is not None:
                source = "table_dow"

        # Tier 3: pooled, no gap dim
        if est_price is None:
            est_price = _lookup(table, bucket, gfr, "ALL", "ALL", _MIN_OBS)
            if est_price is not None:
                source = "table_all"

    # Tier 4: linear formula
    if est_price is None:
        est_price = _linear_formula(gfr, entry_price)
        source = "formula"

    if gfr < -0.15 and est_price > entry_price:
        est_price = entry_price
        source = f"{source}+capped"

    est_price = max(0.0, min(1.0, est_price * (1.0 - _DISCOUNT)))
    return round(est_price, 4), source


def calibration_available() -> bool:
    t = _load_table()
    if t is None:
        return False
    return len(t[(t["dow"] == "ALL") & (t["gap_bucket"] == "ALL") &
                 (t["n_obs"] >= _MIN_OBS)]) > 0
