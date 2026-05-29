"""
End-of-day pipeline — runs all four steps in order after 4pm ET.

Steps (each must succeed before the next runs):
  1. eod_update      → scrapes today's resolved Polymarket market, appends raw
                        trades to *_trades.parquet, stores gap+outcome in DB,
                        updates daily_wr
  2. extend_2min     → appends today's 2-min VWAP intervals to full_session_2min.csv
                        and regenerates settlement_probability.csv
                        (uses parquet metadata pre-May-2026, Gamma API after)
  3. calibrate_exit  → reads full_session_2min.csv, rebuilds
                        data/exit_model_calibration.csv
  4. train_model     → reads full_session_2min.csv, retrains
                        data/settlement_model.pkl

Usage:
    python tools/eod_pipeline.py              # run for today
    python tools/eod_pipeline.py --date 2026-05-23   # specific date (step 1 only uses date)
    python tools/eod_pipeline.py --skip-models       # run steps 1+2 only, skip model refit
"""

import argparse
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
TOOLS = ROOT / "tools"
LOGS = ROOT / "logs"


def _run(label: str, script: Path, extra_args: list[str] = []) -> bool:
    """Run a script as a subprocess. Returns True on success."""
    cmd = [PYTHON, str(script)] + extra_args
    print(f"\n[{label}] Running: {' '.join(str(c) for c in cmd)}")
    print("-" * 60)
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"\n[{label}] FAILED (exit code {result.returncode})")
        return False
    print(f"\n[{label}] OK")
    return True


def main():
    parser = argparse.ArgumentParser(description="Full end-of-day data pipeline")
    parser.add_argument("--date", default=None, help="Date for step 1 (YYYY-MM-DD, default: today)")
    parser.add_argument("--skip-models", action="store_true",
                        help="Skip model refit (steps 3+4) — useful when data is thin")
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"EOD Pipeline started at {started_at}")
    print(f"Working directory: {ROOT}")

    # ── Step 1: Scrape today's resolution + append trades + update daily_wr ──
    step1_args = ["--date", args.date] if args.date else []
    if not _run("Step 1/4  eod_update", TOOLS / "eod_update.py", step1_args):
        print("\nPipeline aborted — step 1 failed. DB not updated.")
        sys.exit(1)

    # ── Step 2: Append today's 2-min intervals to full_session_2min.csv ─────
    today_str = args.date or date.today().isoformat()
    if not _run("Step 2/4  extend_2min_data", TOOLS / "extend_2min_data.py",
                ["--from", today_str, "--to", today_str]):
        print("\nStep 2 failed — 2-min data not refreshed. Models NOT retrained.")
        sys.exit(1)

    if args.skip_models:
        print("\n--skip-models set. Stopping after step 2.")
        return

    # ── Step 3: Rebuild exit model calibration table ──
    if not _run("Step 3/4  calibrate_exit_model", TOOLS / "calibrate_exit_model.py"):
        print("\nStep 3 failed — exit calibration not updated. Continuing to step 4 anyway.")

    # ── Step 4: Retrain settlement probability model ──
    if not _run("Step 4/4  train_settlement_model", TOOLS / "train_settlement_model.py"):
        print("\nStep 4 failed — settlement model not updated.")

    print(f"\nEOD Pipeline complete at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
