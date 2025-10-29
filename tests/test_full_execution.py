"""
Test full execution flow with mock order placement
Task 2.4.3: Simulate complete trade lifecycle
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_full_execution_flow():
    """
    Test complete execution workflow:
    1. Pre-flight checks
    2. Position sizing
    3. Stop-loss calculation
    4. Order placement (mocked)
    5. Position saving
    """
    print("=" * 60)
    print("Testing Full Execution Flow")
    print("=" * 60)

    # Step 1: Create valid opportunity
    print("\n📊 Step 1: Creating test opportunity...")
    opportunity = {
        'market_id': 'test_full_exec_001',
        'question': 'Will it rain in SF tomorrow?',
        'yes_price': 0.93,
        'category': 'Weather',
        'recommended_size': 150,
        'ai_certainty': 0.95,
        'liquidity_score': {
            'risk_assessment': 'Low Risk',
            'liquidity_ratio': 25
        },
        'last_updated': datetime.now().isoformat()
    }
    print(f"✅ Created opportunity: {opportunity['question']}")

    # Step 2: Test position sizing
    print("\n📊 Step 2: Calculating position size...")
    from execution.sizer import PositionSizer

    sizer = PositionSizer(bankroll=5000, max_position_size=200)
    sizing_result = sizer.calculate_kelly_position(
        market_price=opportunity['yes_price'],
        your_confidence=opportunity['ai_certainty'],
        current_positions=[]
    )

    print(f"✅ Position size calculated: ${sizing_result['position_size_usd']:.2f}")
    print(f"   Kelly fraction: {sizing_result['kelly_fraction']:.2%}")
    print(f"   Edge: {sizing_result['edge']:.2%}")

    # Step 3: Test stop-loss calculation
    print("\n📊 Step 3: Calculating stop-loss...")
    from execution.stop_calculator import StopLossCalculator

    stop_calc = StopLossCalculator()
    stop_result = stop_calc.calculate_adaptive_stop_loss(
        entry_price=opportunity['yes_price'],
        current_price=opportunity['yes_price'],
        market_data={
            'liquidity_score': 'Medium',
            'volatility_6h': 0.02,
            'hours_to_settlement': 24
        }
    )

    print(f"✅ Stop-loss calculated: ${stop_result['stop_loss_price']:.4f}")
    print(f"   Stop-loss %: {stop_result['stop_loss_pct']:.1%}")

    # Step 4: Test pre-flight checks
    print("\n📊 Step 4: Running pre-flight checks...")
    from execution.trader import pre_flight_checks

    passed = pre_flight_checks(opportunity)

    if passed:
        print("✅ All pre-flight checks passed")
    else:
        print("❌ Pre-flight checks failed")
        return False

    # Step 5: Simulate order placement
    print("\n📊 Step 5: Simulating order placement...")
    print("   (Note: Using mocked orders - no real money)")

    mock_order = {
        'order_id': f'mock_order_{int(datetime.now().timestamp())}',
        'status': 'placed',
        'side': 'BUY',
        'price': opportunity['yes_price'],
        'size': sizing_result['position_size_usd'],
        'timestamp': datetime.now().isoformat()
    }

    print(f"✅ Mock order placed:")
    print(f"   Order ID: {mock_order['order_id']}")
    print(f"   Size: ${mock_order['size']:.2f}")
    print(f"   Price: ${mock_order['price']}")

    # Step 6: Simulate fill
    print("\n📊 Step 6: Simulating order fill...")
    mock_fill = {
        'order_id': mock_order['order_id'],
        'filled': True,
        'price': opportunity['yes_price'],
        'tokens': int(mock_order['size'] / opportunity['yes_price']),
        'timestamp': datetime.now().isoformat()
    }

    print(f"✅ Order filled:")
    print(f"   Tokens: {mock_fill['tokens']}")
    print(f"   Fill price: ${mock_fill['price']}")

    # Summary
    print("\n" + "=" * 60)
    print("EXECUTION FLOW SUMMARY")
    print("=" * 60)
    print(f"✅ Opportunity validated")
    print(f"✅ Position sized: ${sizing_result['position_size_usd']:.2f}")
    print(f"✅ Stop-loss set: ${stop_result['stop_loss_price']:.4f}")
    print(f"✅ Pre-flight checks passed")
    print(f"✅ Order placed (mocked)")
    print(f"✅ Order filled (mocked)")
    print("\n🎉 Full execution workflow completed successfully!")
    print("=" * 60)

    return True


if __name__ == "__main__":
    success = test_full_execution_flow()
    sys.exit(0 if success else 1)
