"""
Test complete execution workflow with sample trades
Task 2.4.3: End-to-end testing of trading system
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.trader import execute_trade, pre_flight_checks


def create_sample_opportunity(scenario="valid"):
    """
    Create realistic sample opportunities for testing.

    Args:
        scenario: "valid", "poor_liquidity", "stale_price", "high_category_exposure"

    Returns:
        Dict with opportunity data
    """
    base_opportunity = {
        'market_id': 'test_market_crypto_001',
        'question': 'Will Bitcoin hit $100k by end of 2025?',
        'yes_price': 0.93,
        'category': 'Crypto',
        'recommended_size': 150,
        'ai_certainty': 0.95,
        'liquidity_score': {
            'risk_assessment': 'Low Risk',
            'liquidity_ratio': 25,
            'bid_depth': 5000,
            'ask_depth': 4500
        },
        'last_updated': datetime.now().isoformat(),
        'volume': 50000,
        'settlement_date': (datetime.now() + timedelta(days=3)).isoformat()
    }

    if scenario == "valid":
        return base_opportunity

    elif scenario == "poor_liquidity":
        opp = base_opportunity.copy()
        opp['liquidity_score'] = {
            'risk_assessment': 'Poor',
            'liquidity_ratio': 3,
            'bid_depth': 200,
            'ask_depth': 150
        }
        opp['question'] = 'Will obscure event happen? (low liquidity)'
        return opp

    elif scenario == "stale_price":
        opp = base_opportunity.copy()
        opp['last_updated'] = (datetime.now() - timedelta(minutes=10)).isoformat()
        opp['question'] = 'Will event happen? (stale data)'
        return opp

    elif scenario == "high_category_exposure":
        opp = base_opportunity.copy()
        opp['recommended_size'] = 5000  # Way too large
        opp['question'] = 'Will another crypto event happen?'
        return opp

    else:
        return base_opportunity


def test_scenario(scenario_name, opportunity):
    """Test a single scenario"""
    print(f"\n{'='*60}")
    print(f"Testing: {scenario_name}")
    print(f"{'='*60}")
    print(f"Question: {opportunity['question']}")
    print(f"Price: ${opportunity['yes_price']}")
    print(f"Liquidity: {opportunity['liquidity_score']['risk_assessment']}")

    # Test pre-flight checks
    passed = pre_flight_checks(opportunity)

    if passed:
        print(f"✅ Pre-flight checks: PASSED")
    else:
        print(f"❌ Pre-flight checks: FAILED (as expected)")

    return passed


def run_all_scenarios():
    """Run all test scenarios"""
    print("\n" + "🧪" * 30)
    print("TASK 2.4.3 - Execution Workflow Testing")
    print("🧪" * 30)

    results = {}

    # Scenario 1: Valid opportunity (should pass)
    print("\n📊 Scenario 1: Valid Opportunity")
    opp1 = create_sample_opportunity("valid")
    results['valid'] = test_scenario("Valid opportunity", opp1)

    # Scenario 2: Poor liquidity (should fail)
    print("\n📊 Scenario 2: Poor Liquidity")
    opp2 = create_sample_opportunity("poor_liquidity")
    results['poor_liquidity'] = test_scenario("Poor liquidity", opp2)

    # Scenario 3: Stale price (should fail)
    print("\n📊 Scenario 3: Stale Price Data")
    opp3 = create_sample_opportunity("stale_price")
    results['stale_price'] = test_scenario("Stale price", opp3)

    # Summary
    print("\n" + "="*60)
    print("TEST RESULTS SUMMARY")
    print("="*60)

    print(f"\n✅ Valid opportunity: {'PASSED' if results['valid'] else 'FAILED'}")
    print(f"❌ Poor liquidity: {'REJECTED' if not results['poor_liquidity'] else 'FAILED'}")
    print(f"❌ Stale price: {'REJECTED' if not results['stale_price'] else 'FAILED'}")

    # Expected results
    expected_pass = results['valid'] == True
    expected_fail_liquidity = results['poor_liquidity'] == False
    expected_fail_stale = results['stale_price'] == False

    if expected_pass and expected_fail_liquidity and expected_fail_stale:
        print("\n🎉 All scenarios behaved correctly!")
        print("="*60)
        return True
    else:
        print("\n⚠️ Unexpected results - check logic")
        print("="*60)
        return False


if __name__ == "__main__":
    success = run_all_scenarios()
    sys.exit(0 if success else 1)
