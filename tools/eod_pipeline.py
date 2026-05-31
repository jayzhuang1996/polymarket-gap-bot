"""
End-of-day pipeline — runs all four steps in order after 4pm ET.

Steps (each must succeed before the next runs):
  1. eod_update      → scrapes today's resolved Polymarket market, appends raw
                        trades to *_trades.parquet, stores gap+outcome in DB,
                        updates daily_wr
  2. extend_2min     → appends today's 2-min VWAP intervals to full_session_2min.csv
                        and regenerates settlement_probability.csv
  3. calibrate_exit  → reads full_session_2min.csv, rebuilds
                        data/exit_model_calibration.csv
  4. train_model     → reads full_session_2min.csv, retrains
                        data/settlement_model.pkl
  5. git deploy      → commits and pushes the new model files to Railway

Auto-backfill: if the cron was missed (Mac was asleep), the pipeline detects
all trading days missing from scraped_observations (up to 5 days back) and
processes each one before running model retraining once at the end.

Usage:
    python tools/eod_pipeline.py              # run for today + backfill any missed days
    python tools/eod_pipeline.py --date 2026-05-23   # specific date only, no backfill
    python tools/eod_pipeline.py --skip-models       # skip retraining (steps 3-5)
    python tools/eod_pipeline.py --skip-deploy       # skip git push (steps 1-4 only)
"""

import argparse
import sqlite3
import subprocess
import sys
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent
TOOLS  = ROOT / "tools"

# Always use the project venv for model training so the saved pkl is compatible
# with Railway's runtime (which also uses this venv).  Fall back to sys.executable
# if the venv doesn't exist (e.g. first-run on a fresh machine).
_VENV_PY = ROOT / ".venv" / "bin" / "python"
PYTHON = str(_VENV_PY) if _VENV_PY.exists() else sys.executable


def _run(label: str, script: Path, extra_args: list[str] = []) -> bool:
    """Run a script as a subprocess. Returns True on success."""
    cmd = [PYTHON, str(script)] + extra_args
    print(f"\n[{label}] Running: {' '.join(str(c) for c in cmd)}")
    print("-" * 60)
    result = subprocess.run(cmd, cwd=str(ROOT))
    ok = result.returncode == 0
    print(f"\n[{label}] {'OK' if ok else f'FAILED (exit {result.returncode})'}")
    return ok


def _git_deploy(date_str: str) -> bool:
    """Commit updated model files and push to Railway."""
    files = [
        "data/settlement_model.pkl",
        "data/exit_model_calibration.csv",
    ]
    try:
        subprocess.run(["git", "add"] + files, cwd=str(ROOT), check=True)
        # Check if there's anything staged before committing
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(ROOT)
        )
        if result.returncode == 0:
            print("\n[Step 5/5  git deploy] No model changes to commit — already up to date.")
            return True
        msg = f"chore: auto-deploy EOD model update {date_str}"
        subprocess.run(["git", "commit", "-m", msg], cwd=str(ROOT), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(ROOT), check=True)
        print(f"\n[Step 5/5  git deploy] Pushed model to Railway for {date_str}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[Step 5/5  git deploy] FAILED: {e}")
        return False


def _missing_trading_days(lookback: int = 5) -> list[str]:
    """Return trading days in the past `lookback` days not yet in scraped_observations."""
    # Import calendar helper from eod_update
    sys.path.insert(0, str(ROOT))
    from tools.eod_update import is_market_closed

    db_path = ROOT / "data" / "polymarket.db"
    try:
        conn = sqlite3.connect(str(db_path))
        existing = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM scraped_observations"
            ).fetchall()
        }
        conn.close()
    except Exception:
        existing = set()

    missing = []
    today = date.today()
    for days_back in range(1, lookback + 1):
        d = today - timedelta(days=days_back)
        if d.isoformat() in existing:
            continue
        closed, _ = is_market_closed(d)
        if not closed:
            missing.append(d.isoformat())

    return sorted(missing)  # oldest first


def main():
    parser = argparse.ArgumentParser(description="Full end-of-day data pipeline")
    parser.add_argument("--date", default=None,
                        help="Process this specific date only, no auto-backfill (YYYY-MM-DD)")
    parser.add_argument("--skip-models", action="store_true",
                        help="Skip model refit and deploy (steps 3-5)")
    parser.add_argument("--skip-deploy", action="store_true",
                        help="Skip git push (run steps 1-4 only)")
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"EOD Pipeline started at {started_at}")
    print(f"Working directory: {ROOT}")

    # ── Determine which dates to process ──────────────────────────────────────
    if args.date:
        dates_to_process = [args.date]
    else:
        today_str = date.today().isoformat()
        missed    = _missing_trading_days(lookback=5)
        dates_to_process = missed + [today_str]
        if missed:
            print(f"\n  Auto-backfill: {len(missed)} missed day(s): {', '.join(missed)}")
        print(f"  Processing: {', '.join(dates_to_process)}")

    # ── Steps 1 + 2 for each date ─────────────────────────────────────────────
    processed = []
    for d_str in dates_to_process:
        print(f"\n{'='*60}\n  Date: {d_str}\n{'='*60}")

        if not _run(f"Step 1/5  eod_update  [{d_str}]",
                    TOOLS / "eod_update.py", ["--date", d_str]):
            print(f"\n  eod_update failed for {d_str} — skipping this date.")
            continue

        if not _run(f"Step 2/5  extend_2min [{d_str}]",
                    TOOLS / "extend_2min_data.py", ["--from", d_str, "--to", d_str]):
            print(f"\n  extend_2min failed for {d_str} — skipping this date.")
            continue

        processed.append(d_str)

    if not processed:
        print("\nNo dates processed successfully — aborting.")
        sys.exit(1)

    latest = processed[-1]

    if args.skip_models:
        print(f"\n--skip-models set. Done after step 2. Processed: {processed}")
        return

    # ── Steps 3 + 4: retrain once on full updated CSV ─────────────────────────
    print(f"\n{'='*60}\n  Model retraining (on full dataset)\n{'='*60}")

    if not _run("Step 3/5  calibrate_exit_model", TOOLS / "calibrate_exit_model.py"):
        print("\nStep 3 failed — exit calibration not updated. Continuing to step 4.")

    if not _run("Step 4/5  train_settlement_model", TOOLS / "train_settlement_model.py"):
        print("\nStep 4 failed — settlement model not updated.")
        sys.exit(1)

    # ── Step 5: deploy to Railway ──────────────────────────────────────────────
    if not args.skip_deploy:
        _git_deploy(latest)

    print(f"\nEOD Pipeline complete at {datetime.now(timezone.utc).isoformat()}")
    print(f"  Processed dates: {', '.join(processed)}")


if __name__ == "__main__":
    main()
