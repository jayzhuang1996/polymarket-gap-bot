"""
Build the exit model calibration table from full_session_2min.csv.

The calibration table maps (time-of-day, gfr_bucket, dow, gap_bucket) →
empirical avg YES token VWAP from 57,470 real Polymarket observations.

Output: data/exit_model_calibration.csv
  Rows fall into two tiers:
  - gap_bucket="ALL": pooled across gap sizes — existing fallback (tiers 3+4)
  - gap_bucket="small" (<2%) or "large" (≥2%): gap-segmented (tiers 1+2)
    Generated only for dow="ALL" (per-DOW × gap is too sparse at n=273 for large).

Lookup priority in exit_model.py:
  1. (time, gfr, "ALL", gap_bucket)  — gap-segmented, pooled   [main new path]
  2. (time, gfr, dow)                — no gap dim, day-specific [existing]
  3. (time, gfr, "ALL")              — no gap dim, pooled       [existing fallback]
  4. linear formula                   — final fallback

Usage:
  python tools/calibrate_exit_model.py
  (also called by eod_update.py cron pipeline after full_session_analysis.py)
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

DATA_DIR    = Path("data")
INPUT_PATH  = DATA_DIR / "full_session_2min.csv"
OUTPUT_PATH = DATA_DIR / "exit_model_calibration.csv"

MIN_CELL_OBS     = 5    # minimum obs for dow-specific and pooled-no-gap cells
MIN_GAP_CELL_OBS = 10   # higher bar for gap-segmented cells (sparser by design)
MIN_TRADES       = 3    # minimum trades per 2-min window (removes low-signal rows)
MIN_GAP_PCT      = 0.5  # only calibrate on gap days (the strategy's entry condition)

# Time buckets: 30-min windows from 10:30am to 2:00pm
# tbf_min = minutes before 4pm close
_TBF_BINS   = [90, 120, 150, 180, 210, 240, 270, 300, 330]
_TBF_LABELS = ["14:00", "13:30", "13:00", "12:30", "12:00", "11:30", "11:00", "10:30"]

# GFR bins: how much of the overnight gap has been filled intraday
_GFR_BINS = [-99.0, -0.5, -0.2, 0.1, 0.4, 0.7, 99.0]

# Gap size buckets — two tiers keeps cells dense enough to trust
# Data: small=1,967 rows, large=273 rows across 48 (time×gfr) cells
_GAP_BINS   = [0.5, 2.0, 99.0]
_GAP_LABELS = ["small", "large"]   # small: 0.5–2%, large: ≥2%


def build_calibration_table() -> None:
    if not INPUT_PATH.exists():
        print(f"ERROR: {INPUT_PATH} not found. Run tools/full_session_analysis.py first.")
        sys.exit(1)

    df = pd.read_csv(INPUT_PATH)
    print(f"Loaded {len(df):,} rows from {INPUT_PATH.name}")

    df = df[df["n_trades"] >= MIN_TRADES]
    df = df[df["gap_pct"].abs() >= MIN_GAP_PCT].copy()
    print(f"After filters (n_trades≥{MIN_TRADES}, |gap_pct|≥{MIN_GAP_PCT}%): {len(df):,} rows")

    df["gfr"] = df["gfr"].clip(-2.0, 2.0)

    df["time_bucket"] = pd.cut(
        df["tbf_min"], bins=_TBF_BINS, labels=_TBF_LABELS, right=True,
    )
    df = df[df["time_bucket"].notna()].copy()
    df["time_bucket"] = df["time_bucket"].astype(str)
    print(f"After time window filter (10:30am–2:00pm): {len(df):,} rows")

    df["gfr_bin"] = pd.cut(df["gfr"], bins=_GFR_BINS, right=False)
    df = df[df["gfr_bin"].notna()].copy()

    df["gap_bin"] = pd.cut(df["gap_pct"].abs(), bins=_GAP_BINS, labels=_GAP_LABELS, right=False)
    df = df[df["gap_bin"].notna()].copy()
    df["gap_bin"] = df["gap_bin"].astype(str)

    results = []

    for time_label in _TBF_LABELS:
        t_df = df[df["time_bucket"] == time_label]

        for interval in df["gfr_bin"].cat.categories:
            gfr_lo = interval.left
            gfr_hi = interval.right
            cell_all = t_df[t_df["gfr_bin"] == interval]

            if len(cell_all) == 0:
                continue

            # ── Tier 3+4: gap_bucket="ALL" — existing behaviour ──────────────
            # Pooled across all gap sizes
            results.append(_make_row(time_label, gfr_lo, gfr_hi, "ALL", "ALL",
                                     cell_all, MIN_CELL_OBS))

            # Per-DOW, no gap segmentation
            for dow in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
                cell_dow = cell_all[cell_all["dow"] == dow]
                if len(cell_dow) == 0:
                    continue
                results.append(_make_row(time_label, gfr_lo, gfr_hi, dow, "ALL",
                                         cell_dow, MIN_CELL_OBS))

            # ── Tier 1+2: gap-segmented, pooled dow only ─────────────────────
            # Per-DOW × gap_bucket is too sparse (large bucket has ~5 obs/cell avg).
            for gap_label in _GAP_LABELS:
                cell_gap = cell_all[cell_all["gap_bin"] == gap_label]
                if len(cell_gap) == 0:
                    continue
                results.append(_make_row(time_label, gfr_lo, gfr_hi, "ALL", gap_label,
                                         cell_gap, MIN_GAP_CELL_OBS))

    cal_df = pd.DataFrame(results)
    cal_df.to_csv(OUTPUT_PATH, index=False)
    _print_summary(cal_df)


def _make_row(
    time_bucket: str,
    gfr_lo: float,
    gfr_hi: float,
    dow: str,
    gap_bucket: str,
    cell: pd.DataFrame,
    min_obs: int,
) -> dict:
    n = len(cell)
    return {
        "time_bucket":   time_bucket,
        "gfr_lo":        float(gfr_lo),
        "gfr_hi":        float(gfr_hi),
        "dow":           dow,
        "gap_bucket":    gap_bucket,
        "avg_yes_price": round(cell["yes_vwap"].mean(), 4),
        "std_yes_price": round(cell["yes_vwap"].std(), 4),
        "n_obs":         n,
        "note":          "OK" if n >= min_obs else "LOW_OBS",
    }


def _print_summary(cal_df: pd.DataFrame) -> None:
    def _usable(sub: pd.DataFrame, min_n: int) -> pd.DataFrame:
        return sub[sub["n_obs"] >= min_n]

    gap_rows    = cal_df[cal_df["gap_bucket"] != "ALL"]
    no_gap_rows = cal_df[cal_df["gap_bucket"] == "ALL"]
    pooled      = no_gap_rows[no_gap_rows["dow"] == "ALL"]
    dow_rows    = no_gap_rows[no_gap_rows["dow"] != "ALL"]

    print(f"\nCalibration table → {OUTPUT_PATH}  ({len(cal_df)} rows total)")
    print(f"  Gap-segmented cells (tier 1-2): {len(gap_rows):>4} total | "
          f"{len(_usable(gap_rows, MIN_GAP_CELL_OBS)):>4} usable (n≥{MIN_GAP_CELL_OBS})")
    print(f"  Pooled no-gap (tier 3):         {len(pooled):>4} total | "
          f"{len(_usable(pooled, MIN_CELL_OBS)):>4} usable (n≥{MIN_CELL_OBS})")
    print(f"  Per-DOW no-gap (tier 4):        {len(dow_rows):>4} total | "
          f"{len(_usable(dow_rows, MIN_CELL_OBS)):>4} usable")

    print(f"\n  Gap-segmented usable cells (sample):")
    print(f"  {'Time':<8} {'GFR Range':<20} {'Gap':<8} {'Avg YES¢':<10} {'Std':<7} {'n'}")
    print(f"  {'─'*60}")
    sample = _usable(gap_rows, MIN_GAP_CELL_OBS).sort_values(["time_bucket", "gfr_lo", "gap_bucket"])
    for _, r in sample.head(16).iterrows():
        gfr_str = f"[{r['gfr_lo']:+.1f},{r['gfr_hi']:+.1f})"
        print(f"  {r['time_bucket']:<8} {gfr_str:<20} {r['gap_bucket']:<8} "
              f"{r['avg_yes_price']*100:<10.1f} {r['std_yes_price']*100:<7.1f} {int(r['n_obs'])}")


if __name__ == "__main__":
    build_calibration_table()
