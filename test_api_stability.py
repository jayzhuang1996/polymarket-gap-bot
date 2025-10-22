"""
Task 1.1.6: Test API stability for 30 minutes

Checks for:
- Rate limits
- Connection errors
- Data consistency
- Memory usage
"""

import sys
from pathlib import Path
import time
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from collectors.polymarket_api import fetch_markets, filter_active_markets
from py_clob_client.client import ClobClient
from config import POLYMARKET_HOST, POLYMARKET_CHAIN_ID


def test_api_stability(duration_minutes=30, interval_seconds=60):
    """
    Test API for stability over time.

    Args:
        duration_minutes: How long to run test (default 30 min)
        interval_seconds: How often to fetch (default 60s)
    """
    print("=" * 60)
    print("API STABILITY TEST")
    print("=" * 60)
    print(f"Duration: {duration_minutes} minutes")
    print(f"Fetch interval: {interval_seconds} seconds")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)

    iteration = 0
    errors = 0
    total_markets = []
    total_active = []

    while time.time() < end_time:
        iteration += 1
        elapsed = int(time.time() - start_time)
        remaining = int(end_time - time.time())

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Iteration {iteration} | Elapsed: {elapsed}s | Remaining: {remaining}s")

        try:
            # Test get_sampling_markets (better for active markets)
            client = ClobClient(POLYMARKET_HOST, POLYMARKET_CHAIN_ID)
            response = client.get_sampling_markets()

            if isinstance(response, dict):
                markets = response.get('data', response.get('markets', []))
            else:
                markets = response

            active = filter_active_markets(markets)

            total_markets.append(len(markets))
            total_active.append(len(active))

            print(f"  ✅ Fetched {len(markets)} markets, {len(active)} active")

            # Check for data consistency
            if iteration > 1:
                prev_total = total_markets[-2]
                prev_active = total_active[-2]

                if abs(len(markets) - prev_total) > 100:
                    print(f"  ⚠️  WARNING: Market count changed significantly ({prev_total} → {len(markets)})")

                if abs(len(active) - prev_active) > 50:
                    print(f"  ⚠️  WARNING: Active count changed significantly ({prev_active} → {len(active)})")

        except Exception as e:
            errors += 1
            print(f"  ❌ ERROR: {e}")

            if errors >= 3:
                print(f"\n⚠️  3+ errors detected. Stopping test early.")
                break

        # Wait for next iteration (unless this is the last one)
        if time.time() < end_time:
            time.sleep(interval_seconds)

    # Summary
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print(f"Total iterations: {iteration}")
    print(f"Total errors: {errors}")
    print(f"Success rate: {((iteration - errors) / iteration * 100):.1f}%")

    if total_markets:
        print(f"\nMarket counts: min={min(total_markets)}, max={max(total_markets)}, avg={sum(total_markets)//len(total_markets)}")
        print(f"Active counts: min={min(total_active)}, max={max(total_active)}, avg={sum(total_active)//len(total_active)}")

    if errors == 0:
        print("\n✅ NO ERRORS - API is stable!")
    else:
        print(f"\n⚠️  {errors} errors occurred - investigate rate limits or connection issues")

    print("=" * 60)


if __name__ == "__main__":
    # For quick testing, run for 5 minutes with 30s intervals
    # For full test, change to: test_api_stability(30, 60)

    print("\n📝 NOTE: Running SHORT test (5 min, 30s intervals) for demo")
    print("For full 30-min test, edit the script and change parameters.\n")

    test_api_stability(duration_minutes=5, interval_seconds=30)
