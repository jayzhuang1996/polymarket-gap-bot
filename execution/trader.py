"""
Order execution module for Polymarket trading
Task 2.4.1: Create execution/trader.py (order execution interface)
"""

import time
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

from collectors.polymarket_api import place_order, get_order_status, cancel_order
from execution.sizer import PositionSizer
from execution.stop_calculator import StopLossCalculator
from database.db_manager import save_position, update_position, get_active_positions
from config import (BANKROLL_USD, MAX_POSITIONS, MIN_RESERVE_PCT,
                   TRADING_FEE_PCT, ESTIMATED_SLIPPAGE_PCT)

logger = logging.getLogger(__name__)


def execute_trade(opportunity: Dict, human_approval_size: Optional[float] = None) -> Optional[int]:
    """
    Execute approved trade with all safety checks.

    Args:
        opportunity: Market data from AI decision
        human_approval_size: Optional override size from human approval

    Returns:
        position_id if successful, None if failed
    """
    try:
        logger.info(f"Executing trade: {opportunity['question']}")

        # Step 1: Pre-flight checks
        if not pre_flight_checks(opportunity):
            logger.warning(f"Pre-flight checks failed for {opportunity['question']}")
            return None

        # Step 2: Calculate position size
        sizer = PositionSizer(bankroll=BANKROLL_USD)

        if human_approval_size:
            size_usd = min(human_approval_size, MAX_POSITION_SIZE)
            logger.info(f"Using human approved size: ${size_usd}")
        else:
            size_usd = sizer.calculate_kelly_position(
                market_price=opportunity['yes_price'],
                your_confidence=opportunity.get('ai_certainty', 0.95),
                current_positions=get_active_positions()
            )

        # Step 3: Calculate stop-loss
        entry_price = opportunity['yes_price']
        stop_calc = StopLossCalculator()
        stop_result = stop_calc.calculate_adaptive_stop_loss(entry_price, entry_price, opportunity)
        stop_price = stop_result['stop_loss_price']
        stop_pct = stop_result['stop_loss_pct']

        # Step 4: Place entry order
        logger.info(f"Placing entry order: ${size_usd} @ ${entry_price}")
        entry_order = place_order(
            market_id=opportunity['market_id'],
            side="BUY",
            price=entry_price,
            size=size_usd
        )

        if not entry_order:
            logger.error(f"❌ Failed to place entry order for {opportunity['question']}")
            logger.error(f"   Possible causes: API error, insufficient funds, invalid market")
            return None

        logger.info(f"✅ Entry order placed successfully: {entry_order['order_id']}")

        # Step 5: Wait for fill (max 60 seconds)
        fill_result = wait_for_fill(entry_order['order_id'], timeout=60)

        if not fill_result:
            logger.error(f"❌ Order not filled within 60 seconds: {entry_order['order_id']}")
            logger.info(f"Attempting to cancel unfilled order...")
            if cancel_order(entry_order['order_id']):
                logger.info(f"✅ Order cancelled successfully")
            else:
                logger.error(f"⚠️ Failed to cancel order - manual intervention may be needed")
            return None

        logger.info(f"✅ Order filled at ${fill_result['price']}")

        # Step 6: Calculate tokens purchased
        tokens = int(fill_result['tokens'])
        actual_price = fill_result['price']
        actual_size = tokens * actual_price

        # Step 7: Place stop-loss order
        logger.info(f"Placing stop-loss: ${stop_price} for {tokens} tokens")
        stop_order = place_order(
            market_id=opportunity['market_id'],
            side="SELL",
            price=stop_price,
            size=tokens,
            order_type="STOP_LOSS"
        )

        # Step 8: Save position to database
        position_data = {
            'market_id': opportunity['market_id'],
            'market_question': opportunity['question'],
            'category': opportunity.get('category', 'Unknown'),
            'entry_price': actual_price,
            'entry_time': datetime.now(),
            'tokens': tokens,
            'position_size_usd': actual_size,
            'stop_loss_price': stop_price,
            'stop_loss_pct': stop_pct,
            'status': 'active',
            'liquidity_at_entry': opportunity.get('liquidity_ratio', 10),
            'volatility_at_entry': opportunity.get('volatility', 0.02)
        }

        position_id = save_position(position_data)

        logger.info(f"Position {position_id} opened successfully")
        return position_id

    except Exception as e:
        logger.error(f"Error executing trade: {e}")
        import traceback
        traceback.print_exc()
        return None


def verify_api_connection() -> bool:
    """
    Verify Polymarket API is reachable.

    Returns:
        True if API is accessible, False otherwise
    """
    try:
        from collectors.polymarket_api import fetch_markets

        # Try to fetch markets (quick connectivity test)
        markets = fetch_markets()

        if markets and len(markets) > 0:
            logger.info(f"✅ API connected - {len(markets)} markets available")
            return True
        else:
            logger.warning("API returned empty response")
            return False

    except Exception as e:
        logger.error(f"API connection failed: {e}")
        return False


def pre_flight_checks(opportunity: Dict) -> bool:
    """
    Final safety checks before order placement.

    Returns:
        True if all checks pass, False otherwise
    """
    try:
        # Check 1: Portfolio limits
        active_positions = get_active_positions()
        if len(active_positions) >= MAX_POSITIONS:
            logger.warning(f"Max positions reached: {len(active_positions)}/{MAX_POSITIONS}")
            return False

        # Check 2: Reserve requirement
        deployed = sum(pos['position_size_usd'] for pos in active_positions)
        max_deployable = BANKROLL_USD * (1 - MIN_RESERVE_PCT)
        if deployed >= max_deployable:
            logger.warning(f"Insufficient reserve: ${deployed:.0f} deployed, max ${max_deployable:.0f}")
            return False

        # Check 3: Category exposure
        category = opportunity.get('category', 'Unknown')
        category_exposure = sum(pos['position_size_usd']
                              for pos in active_positions
                              if pos.get('category') == category)
        max_category_exposure = BANKROLL_USD * 0.40  # 40% per category
        if category_exposure + opportunity.get('recommended_size', 200) > max_category_exposure:
            logger.warning(f"Category exposure limit: ${category_exposure:.0f} in {category}")
            return False

        # Check 4: Market liquidity
        liquidity_score = opportunity.get('liquidity_score', {})
        if isinstance(liquidity_score, dict):
            risk_level = liquidity_score.get('risk_assessment', 'Unknown')
            if risk_level == 'Poor' or risk_level == 'Critical':
                logger.warning(f"Insufficient liquidity: {risk_level}")
                return False

        # Check 5: Price freshness (reject if price data > 5 minutes old)
        last_updated = opportunity.get('last_updated')
        if last_updated:
            from datetime import datetime, timedelta
            if isinstance(last_updated, str):
                last_updated = datetime.fromisoformat(last_updated)
            age_minutes = (datetime.now() - last_updated).total_seconds() / 60
            if age_minutes > 5:
                logger.warning(f"Stale price data: {age_minutes:.1f} minutes old")
                return False

        # Check 6: API connectivity (verify we can reach Polymarket)
        if not verify_api_connection():
            logger.error("Cannot connect to Polymarket API")
            return False

        logger.info("✅ All pre-flight checks passed")
        return True

    except Exception as e:
        logger.error(f"Error in pre-flight checks: {e}")
        return False


def wait_for_fill(order_id: str, timeout: int = 60) -> Optional[Dict]:
    """
    Wait for order to fill with timeout.

    Args:
        order_id: Order ID from Polymarket
        timeout: Maximum seconds to wait

    Returns:
        Dict with fill details if filled, None if timeout
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            status = get_order_status(order_id)

            if status['status'] == 'filled':
                logger.info(f"Order filled: {order_id}")
                return {
                    'price': status['fill_price'],
                    'tokens': status['tokens_filled'],
                    'fees': status.get('fees', 0)
                }

            elif status['status'] == 'cancelled':
                logger.warning(f"Order cancelled: {order_id}")
                return None

            time.sleep(2)  # Check every 2 seconds

        except Exception as e:
            logger.error(f"Error checking order status: {e}")
            time.sleep(5)

    logger.error(f"Order fill timeout: {order_id}")
    return None


def exit_position(position_id: int, reason: str = "manual") -> Optional[Dict]:
    """
    Exit active position immediately.

    Args:
        position_id: Position ID to exit
        reason: Reason for exit (manual, stop_loss, take_profit, emergency)

    Returns:
        Dict with exit result if successful, None if failed
    """
    try:
        from database.db_manager import get_position
        from collectors.polymarket_api import get_current_price

        # Get position details
        position = get_position(position_id)
        if not position or position['status'] != 'active':
            logger.warning(f"Position {position_id} not found or not active")
            return None

        # Get current market price
        current_price = get_current_price(position['market_id'])
        if not current_price:
            logger.error(f"Cannot get current price for position {position_id}")
            return None

        # Place market order to exit
        logger.info(f"Exiting position {position_id} @ ${current_price} (reason: {reason})")
        exit_order = place_order(
            market_id=position['market_id'],
            side="SELL",
            price=current_price,  # Market order
            size=position['tokens']
        )

        if not exit_order:
            logger.error(f"Failed to place exit order for position {position_id}")
            return None

        # Wait for fill
        fill_result = wait_for_fill(exit_order['order_id'], timeout=30)

        if not fill_result:
            logger.error(f"Exit order not filled: {exit_order['order_id']}")
            cancel_order(exit_order['order_id'])
            return None

        # Calculate P/L
        exit_price = fill_result['price']
        pnl_usd = (exit_price - position['entry_price']) * position['tokens']
        pnl_pct = pnl_usd / position['position_size_usd']

        # Update position in database
        update_data = {
            'status': 'exited',
            'exit_price': exit_price,
            'exit_time': datetime.now(),
            'pnl_usd': pnl_usd,
            'pnl_pct': pnl_pct,
            'exit_reason': reason
        }

        update_position(position_id, update_data)

        logger.info(f"Position {position_id} exited: P/L ${pnl_usd:.0f} ({pnl_pct:.1f}%)")

        return {
            'position_id': position_id,
            'exit_price': exit_price,
            'pnl_usd': pnl_usd,
            'pnl_pct': pnl_pct,
            'reason': reason
        }

    except Exception as e:
        logger.error(f"Error exiting position {position_id}: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    """Test the trader module"""

    # Test data (simulated opportunity)
    test_opportunity = {
        'market_id': 'test_market_123',
        'question': 'Will Warriors beat Lakers? (TEST)',
        'category': 'Sports',
        'yes_price': 0.93,
        'ai_certainty': 0.95,
        'liquidity_ratio': 15,
        'recommended_size': 200
    }

    print("=" * 60)
    print("EXECUTION TRADER TEST")
    print("=" * 60)

    print(f"Test opportunity: {test_opportunity['question']}")
    print(f"Price: ${test_opportunity['yes_price']}")
    print(f"AI Certainty: {test_opportunity['ai_certainty']:.0%}")
    print()

    # Test pre-flight checks
    print("1. Testing pre-flight checks...")
    checks_passed = pre_flight_checks(test_opportunity)
    print(f"   Result: {'✅ PASSED' if checks_passed else '❌ FAILED'}")
    print()

    # Test position sizing
    print("2. Testing position sizing...")
    from execution.sizer import PositionSizer
    sizer = PositionSizer(bankroll=BANKROLL_USD)
    size_result = sizer.calculate_kelly_position(test_opportunity['yes_price'], test_opportunity['ai_certainty'])
    size = size_result.get('position_size_usd', size_result) if isinstance(size_result, dict) else size_result
    print(f"   Calculated size: ${float(size):.0f}")
    print()

    # Test stop-loss calculation
    print("3. Testing stop-loss calculation...")
    from execution.stop_calculator import StopLossCalculator
    stop_calc = StopLossCalculator()
    stop_result = stop_calc.calculate_adaptive_stop_loss(test_opportunity['yes_price'], test_opportunity['yes_price'], test_opportunity)
    print(f"   Stop price: ${stop_result['stop_loss_price']:.4f} ({stop_result['stop_loss_pct']:.1%} below entry)")
    print()

    print("=" * 60)
    print("✅ Trader module test completed")
    print("Note: Actual order execution skipped (test mode)")
    print("=" * 60)