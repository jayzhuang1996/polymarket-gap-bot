"""
Test pre-flight checks
Task 2.4.2: Verify enhanced safety checks
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.trader import pre_flight_checks


def test_preflight_checks():
    """Test all pre-flight check scenarios"""

    print("=" * 60)
    print("Testing Pre-Flight Checks")
    print("=" * 60)

    # Test 1: Valid opportunity (should pass)
    print("\n✅ Test 1: Valid opportunity")
    valid_opportunity = {
        'market_id': 'test_123',
        'question': 'Will it rain tomorrow?',
        'yes_price': 0.93,
        'category': 'Weather',
        'recommended_size': 100,
        'liquidity_score': {
            'risk_assessment': 'Low Risk',
            'liquidity_ratio': 25
        },
        'last_updated': datetime.now().isoformat()
    }

    result = pre_flight_checks(valid_opportunity)
    print(f"Result: {result}")
    assert result == True, "Valid opportunity should pass"

    # Test 2: Poor liquidity (should fail)
    print("\n❌ Test 2: Poor liquidity")
    poor_liquidity = valid_opportunity.copy()
    poor_liquidity['liquidity_score'] = {
        'risk_assessment': 'Poor',
        'liquidity_ratio': 3
    }

    result = pre_flight_checks(poor_liquidity)
    print(f"Result: {result}")
    assert result == False, "Poor liquidity should fail"

    # Test 3: Stale price (should fail)
    print("\n❌ Test 3: Stale price data")
    stale_price = valid_opportunity.copy()
    stale_price['last_updated'] = (datetime.now() - timedelta(minutes=10)).isoformat()

    result = pre_flight_checks(stale_price)
    print(f"Result: {result}")
    assert result == False, "Stale price should fail"

    # Test 4: No last_updated field (should pass - optional check)
    print("\n✅ Test 4: No timestamp (passes with warning)")
    no_timestamp = valid_opportunity.copy()
    del no_timestamp['last_updated']

    result = pre_flight_checks(no_timestamp)
    print(f"Result: {result}")

    print("\n" + "=" * 60)
    print("✅ All pre-flight check tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    test_preflight_checks()
