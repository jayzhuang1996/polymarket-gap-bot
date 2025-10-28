"""
Adaptive Stop-Loss Calculator for Polymarket trading strategy
Task 2.2.4: Create execution/stop_calculator.py

Implements dynamic stop-loss adjustment based on:
- Market volatility (6-hour price standard deviation)
- Liquidity depth (bid/ask order book depth)
- Time to settlement (widen stops in final 6 hours)
- Base risk tolerance (10% default)
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import math

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import STOP_LOSS_PCT, MIN_SETTLEMENT_HOURS

class StopLossCalculator:
    """
    Adaptive stop-loss calculator for tail-end arbitrage positions.

    Dynamically adjusts stop-loss based on market conditions:
    - Base: 10% below entry price
    - Volatility adjustment: +/- based on price movements
    - Liquidity adjustment: Widen for thin markets, tighten for deep markets
    - Time adjustment: Widen 50% when <6h to settlement
    """

    def __init__(self, base_stop_loss_pct=None):
        """
        Initialize stop-loss calculator.

        Args:
            base_stop_loss_pct (float): Base stop-loss percentage
        """
        self.base_stop_loss_pct = base_stop_loss_pct or STOP_LOSS_PCT

        print(f"✅ Stop-Loss Calculator initialized:")
        print(f"   Base Stop-Loss: {self.base_stop_loss_pct:.1%}")

    def calculate_adaptive_stop_loss(self, entry_price, current_price, market_data=None):
        """
        Calculate adaptive stop-loss level based on market conditions.

        Args:
            entry_price (float): Entry price of position
            current_price (float): Current market price
            market_data (dict): Additional market context
                - liquidity_score: Market liquidity assessment
                - volatility_6h: 6-hour price volatility
                - hours_to_settlement: Time until market settlement
                - price_history: Recent price movements

        Returns:
            dict: Stop-loss calculation with breakdown
        """
        if market_data is None:
            market_data = {}

        # Extract market data with defaults
        liquidity_score = market_data.get('liquidity_score', 'Medium')
        volatility_6h = market_data.get('volatility_6h', 0.02)  # 2% default
        hours_to_settlement = market_data.get('hours_to_settlement', 24)
        price_history = market_data.get('price_history', [])

        # Start with base stop-loss
        adjusted_stop_pct = self.base_stop_loss_pct

        # 1. Volatility Adjustment
        volatility_adjustment = self._calculate_volatility_adjustment(volatility_6h, price_history)
        adjusted_stop_pct += volatility_adjustment

        # 2. Liquidity Adjustment
        liquidity_adjustment = self._calculate_liquidity_adjustment(liquidity_score)
        adjusted_stop_pct += liquidity_adjustment

        # 3. Time Adjustment (manipulation window)
        time_adjustment = self._calculate_time_adjustment(hours_to_settlement)
        adjusted_stop_pct += time_adjustment

        # Ensure stop-loss is within reasonable bounds
        final_stop_pct = max(0.08, min(adjusted_stop_pct, 0.18))  # 8% - 18% range

        # Calculate actual stop-loss price
        stop_loss_price = entry_price * (1 - final_stop_pct)

        # Determine if current price is close to stop
        price_distance_pct = (current_price - stop_loss_price) / entry_price
        near_stop = price_distance_pct < 0.02  # Within 2% of stop

        return {
            'stop_loss_price': stop_loss_price,
            'stop_loss_pct': final_stop_pct,
            'base_pct': self.base_stop_loss_pct,
            'volatility_adjustment': volatility_adjustment,
            'liquidity_adjustment': liquidity_adjustment,
            'time_adjustment': time_adjustment,
            'current_distance_pct': price_distance_pct,
            'near_stop': near_stop,
            'recommendation': self._get_stop_recommendation(near_stop, final_stop_pct, market_data)
        }

    def _calculate_volatility_adjustment(self, volatility_6h, price_history):
        """
        Calculate stop-loss adjustment based on market volatility.

        Higher volatility = wider stops to avoid being stopped out by noise
        Lower volatility = tighter stops for better risk control

        Args:
            volatility_6h (float): 6-hour price volatility (std dev)
            price_history (list): Recent price points

        Returns:
            float: Adjustment percentage (+/-)
        """
        if volatility_6h > 0.05:  # >5% volatility = high volatility
            return 0.03  # Widen stop by 3%
        elif volatility_6h > 0.02:  # 2-5% volatility = moderate
            return 0.01  # Widen stop by 1%
        elif volatility_6h < 0.01:  # <1% volatility = low
            return -0.02  # Tighten stop by 2%
        else:
            return 0.0  # No adjustment for normal volatility

    def _calculate_liquidity_adjustment(self, liquidity_score):
        """
        Calculate stop-loss adjustment based on market liquidity.

        Poor liquidity = wider stops (harder to execute)
        Excellent liquidity = tighter stops (easy execution)

        Args:
            liquidity_score (str): Liquidity assessment

        Returns:
            float: Adjustment percentage (+/-)
        """
        if liquidity_score == 'Poor':
            return 0.04  # Widen stop by 4%
        elif liquidity_score == 'Fair':
            return 0.02  # Widen stop by 2%
        elif liquidity_score == 'Excellent':
            return -0.02  # Tighten stop by 2%
        else:  # Good/Normal
            return 0.0  # No adjustment

    def _calculate_time_adjustment(self, hours_to_settlement):
        """
        Calculate time-based stop adjustment for manipulation window.

        Final 6 hours before settlement can have manipulation attempts
        requiring wider stops to avoid false triggers.

        Args:
            hours_to_settlement (float): Hours until settlement

        Returns:
            float: Adjustment percentage (+/-)
        """
        if hours_to_settlement < 6:
            return 0.05  # Widen stop by 5% (50% of base 10%)
        elif hours_to_settlement < 12:
            return 0.02  # Widen stop by 2%
        else:
            return 0.0  # No adjustment for normal time windows

    def _get_stop_recommendation(self, near_stop, stop_pct, market_data):
        """
        Generate recommendations based on stop-loss analysis.

        Args:
            near_stop (bool): If price is near stop-loss
            stop_pct (float): Final stop-loss percentage
            market_data (dict): Market context

        Returns:
            str: Recommendation message
        """
        if near_stop:
            return "URGENT: Price within 2% of stop-loss - consider manual review"

        if stop_pct > 0.15:
            return "Wide stop-loss due to market conditions - monitor closely"
        elif stop_pct < 0.10:
            return "Tight stop-loss - good risk control"
        else:
            return "Normal stop-loss parameters"

    def calculate_trailing_stop(self, entry_price, current_price, highest_price, trail_pct=0.05):
        """
        Calculate trailing stop-loss for profitable positions.

        Args:
            entry_price (float): Original entry price
            current_price (float): Current market price
            highest_price (float): Highest price since entry
            trail_pct (float): Trail distance percentage

        Returns:
            dict: Trailing stop calculation
        """
        # Only trail if position is profitable
        if current_price <= entry_price:
            return {
                'trailing_stop_price': None,
                'trail_active': False,
                'reason': 'Position not profitable - using fixed stop-loss'
            }

        # Calculate trailing stop level
        trailing_stop_price = highest_price * (1 - trail_pct)

        # Don't trail below break-even
        break_even_stop = entry_price * 1.01  # 1% above entry for fees
        final_trailing_stop = max(trailing_stop_price, break_even_stop)

        return {
            'trailing_stop_price': final_trailing_stop,
            'trail_active': True,
            'trail_distance_pct': trail_pct,
            'profit_protected_pct': (final_trailing_stop - entry_price) / entry_price,
            'reason': f'Trailing stop {trail_pct:.1%} below peak of ${highest_price:.3f}'
        }

    def check_stop_trigger(self, current_price, stop_loss_price, trailing_stop_price=None):
        """
        Check if stop-loss should be triggered.

        Args:
            current_price (float): Current market price
            stop_loss_price (float): Fixed stop-loss price
            trailing_stop_price (float): Optional trailing stop price

        Returns:
            dict: Stop trigger analysis
        """
        triggered = False
        trigger_type = None
        trigger_price = stop_loss_price

        # Check trailing stop first (if active and higher)
        if trailing_stop_price and trailing_stop_price > stop_loss_price:
            trigger_price = trailing_stop_price
            if current_price <= trailing_stop_price:
                triggered = True
                trigger_type = 'trailing_stop'
        else:
            if current_price <= stop_loss_price:
                triggered = True
                trigger_type = 'fixed_stop'

        return {
            'triggered': triggered,
            'trigger_type': trigger_type,
            'trigger_price': trigger_price,
            'current_price': current_price,
            'distance_to_stop_pct': (current_price - trigger_price) / trigger_price
        }


if __name__ == "__main__":
    """
    Test stop-loss calculator functionality.
    """
    print("=" * 80)
    print("Stop-Loss Calculator - Test")
    print("=" * 80)

    # Create calculator instance
    calculator = StopLossCalculator()

    # Test scenarios
    test_scenarios = [
        {
            'name': 'Normal Market Conditions',
            'entry_price': 0.94,
            'current_price': 0.94,
            'market_data': {
                'liquidity_score': 'Good',
                'volatility_6h': 0.02,
                'hours_to_settlement': 24
            }
        },
        {
            'name': 'High Volatility Market',
            'entry_price': 0.93,
            'current_price': 0.93,
            'market_data': {
                'liquidity_score': 'Fair',
                'volatility_6h': 0.06,  # High volatility
                'hours_to_settlement': 18
            }
        },
        {
            'name': 'Poor Liquidity + Final Hours',
            'entry_price': 0.95,
            'current_price': 0.945,  # Slight drop
            'market_data': {
                'liquidity_score': 'Poor',
                'volatility_6h': 0.03,
                'hours_to_settlement': 4  # Final 4 hours
            }
        },
        {
            'name': 'Excellent Liquidity + Low Volatility',
            'entry_price': 0.92,
            'current_price': 0.92,
            'market_data': {
                'liquidity_score': 'Excellent',
                'volatility_6h': 0.008,  # Low volatility
                'hours_to_settlement': 36
            }
        },
        {
            'name': 'Near Stop-Loss Trigger',
            'entry_price': 0.94,
            'current_price': 0.852,  # Close to 10% stop
            'market_data': {
                'liquidity_score': 'Good',
                'volatility_6h': 0.02,
                'hours_to_settlement': 12
            }
        }
    ]

    print(f"\n📊 Testing {len(test_scenarios)} scenarios...")

    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n{i}. {scenario['name']}")
        print(f"   Entry Price: ${scenario['entry_price']:.3f}")
        print(f"   Current Price: ${scenario['current_price']:.3f}")

        # Calculate adaptive stop-loss
        stop_result = calculator.calculate_adaptive_stop_loss(
            scenario['entry_price'],
            scenario['current_price'],
            scenario['market_data']
        )

        print(f"   Stop-Loss Price: ${stop_result['stop_loss_price']:.3f}")
        print(f"   Stop-Loss %: {stop_result['stop_loss_pct']:.1%}")
        print(f"   Adjustments: Volatility {stop_result['volatility_adjustment']:+.1%}, "
              f"Liquidity {stop_result['liquidity_adjustment']:+.1%}, "
              f"Time {stop_result['time_adjustment']:+.1%}")
        print(f"   Distance to Stop: {stop_result['current_distance_pct']:.1%}")
        print(f"   Near Stop: {stop_result['near_stop']}")
        print(f"   Recommendation: {stop_result['recommendation']}")

    print(f"\n" + "=" * 60)

    # Test trailing stop
    print(f"\n🔄 Testing Trailing Stop...")

    trailing_scenarios = [
        {
            'name': 'Profitable Position',
            'entry_price': 0.92,
            'current_price': 0.96,
            'highest_price': 0.97
        },
        {
            'name': 'Unprofitable Position',
            'entry_price': 0.94,
            'current_price': 0.93,
            'highest_price': 0.945
        }
    ]

    for scenario in trailing_scenarios:
        print(f"\n   {scenario['name']}:")
        trailing_result = calculator.calculate_trailing_stop(
            scenario['entry_price'],
            scenario['current_price'],
            scenario['highest_price']
        )
        print(f"     Trailing Active: {trailing_result['trail_active']}")
        if trailing_result['trail_active']:
            print(f"     Trailing Stop: ${trailing_result['trailing_stop_price']:.3f}")
            print(f"     Profit Protected: {trailing_result['profit_protected_pct']:.1%}")
        print(f"     Reason: {trailing_result['reason']}")

    # Test stop trigger
    print(f"\n⚡ Testing Stop Trigger...")

    trigger_test = calculator.check_stop_trigger(
        current_price=0.845,
        stop_loss_price=0.846,
        trailing_stop_price=0.860
    )

    print(f"   Stop Triggered: {trigger_test['triggered']}")
    print(f"   Trigger Type: {trigger_test['trigger_type']}")
    print(f"   Trigger Price: ${trigger_test['trigger_price']:.3f}")
    print(f"   Distance to Stop: {trigger_test['distance_to_stop_pct']:.1%}")

    print("\nStop-Loss Calculator test complete!")
    print("=" * 80)