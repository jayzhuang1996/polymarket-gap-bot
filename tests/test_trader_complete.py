"""
Test complete trader workflow with enhanced pre-flight checks
Task 2.4.2: Verify API integration and error handling
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.trader import pre_flight_checks, verify_api_connection


def test_api_connectivity():
    """Test API connection check"""
    print("=" * 60)
    print("Testing API Connectivity")
    print("=" * 60)

    result = verify_api_connection()
    print(f"\nAPI Connection Result: {result}")

    if result:
        print("✅ API is reachable")
    else:
        print("❌ API connection failed")

    return result


def test_complete_preflight():
    """Test all pre-flight checks including new enhancements"""
    print("\n" + "=" * 60)
    print("Testing Complete Pre-Flight Checks")
    print("=" * 60)

    # Test opportunity with all fields
    opportunity = {
        'market_id': 'test_market_123',
        'question': 'Will Bitcoin hit $100k by end of 2025?',
        'yes_price': 0.93,
        'category': 'Crypto',
        'recommended_size': 150,
        'liquidity_score': {
            'risk_assessment': 'Low Risk',
            'liquidity_ratio': 25,
            'bid_depth': 5000,
            'ask_depth': 4500
        },
        'last_updated': datetime.now().isoformat()
    }

    print("\n📊 Testing opportunity:")
    print(f"   Question: {opportunity['question']}")
    print(f"   Price: ${opportunity['yes_price']}")
    print(f"   Category: {opportunity['category']}")
    print(f"   Liquidity: {opportunity['liquidity_score']['risk_assessment']}")

    result = pre_flight_checks(opportunity)

    print(f"\n{'✅' if result else '❌'} Pre-flight checks: {'PASSED' if result else 'FAILED'}")

    return result


def run_all_tests():
    """Run complete test suite"""
    print("\n" + "🚀" * 30)
    print("TASK 2.4.2 - Complete Integration Test")
    print("🚀" * 30)

    # Test 1: API Connection
    api_ok = test_api_connectivity()

    # Test 2: Complete pre-flight checks
    preflight_ok = test_complete_preflight()

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"API Connectivity: {'✅ PASS' if api_ok else '❌ FAIL'}")
    print(f"Pre-flight Checks: {'✅ PASS' if preflight_ok else '❌ FAIL'}")

    if api_ok and preflight_ok:
        print("\n🎉 All tests passed! Task 2.4.2 COMPLETE")
        print("=" * 60)
        return True
    else:
        print("\n⚠️ Some tests failed - review logs above")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
