"""
Position Sizer for Polymarket trading strategy
Task 2.2.3: Create execution/sizer.py

Implements Kelly Criterion with safety margins for position sizing.
Manages portfolio risk and position limits according to strategy.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    BANKROLL_USD, MAX_POSITION_SIZE, MAX_POSITIONS,
    MIN_POSITION_SIZE, MIN_RESERVE_PCT
)

class PositionSizer:
    """
    Kelly Criterion position sizer with safety margins.

    Calculates optimal position sizes based on:
    - Edge vs market price
    - Confidence level
    - Portfolio constraints
    - Risk management rules
    """

    def __init__(self, bankroll=None, max_position_size=None, max_positions=None):
        """
        Initialize position sizer with portfolio parameters.

        Args:
            bankroll (float): Total trading capital
            max_position_size (float): Maximum per position
            max_positions (int): Maximum concurrent positions
        """
        self.bankroll = bankroll or BANKROLL_USD
        self.max_position_size = max_position_size or MAX_POSITION_SIZE
        self.max_positions = max_positions or MAX_POSITIONS

        print(f"✅ Position Sizer initialized:")
        print(f"   Bankroll: ${self.bankroll:,.2f}")
        print(f"   Max position: ${self.max_position_size:,.2f}")
        print(f"   Max positions: {self.max_positions}")

    def calculate_kelly_position(self, market_price, your_confidence, current_positions=None):
        """
        Calculate optimal position size using Kelly Criterion with safety margins.

        Kelly Formula: Edge / (1 - Market_Price)
        Where Edge = Your_Confidence - Market_Price

        Args:
            market_price (float): Current YES price (0-1)
            your_confidence (float): Your estimated true probability (0-1)
            current_positions (list): Current portfolio positions

        Returns:
            dict: Position sizing recommendation
        """
        if not current_positions:
            current_positions = []

        # Calculate edge
        edge = your_confidence - market_price

        # Handle negative edge (no advantage)
        if edge <= 0:
            return {
                'recommendation': 'NO_POSITION',
                'position_size_usd': 0,
                'kelly_fraction': 0,
                'edge': -abs(edge),
                'reason': 'Negative or zero edge - no advantage over market'
            }

        # Calculate full Kelly
        if market_price >= 1.0:
            return {
                'recommendation': 'NO_POSITION',
                'position_size_usd': 0,
                'kelly_fraction': 0,
                'edge': edge,
                'reason': 'Market price >= 100% - no upside potential'
            }

        full_kelly = edge / (1 - market_price)

        # Apply 1/4 Kelly for safety (as per strategy)
        safe_kelly = full_kelly / 4

        # Calculate position size in USD
        raw_position_size = safe_kelly * self.bankroll

        # Apply portfolio constraints
        available_capital = self._calculate_available_capital(current_positions)
        max_by_capital = min(raw_position_size, available_capital)

        # Apply hard limits
        final_position_size = min(
            max_by_capital,
            self.max_position_size,
            self.bankroll * 0.20  # Max 20% per position as safety rule
        )

        # Apply minimum position size
        if final_position_size < MIN_POSITION_SIZE:
            return {
                'recommendation': 'POSITION_TOO_SMALL',
                'position_size_usd': final_position_size,
                'kelly_fraction': safe_kelly,
                'edge': edge,
                'reason': f'Position size ${final_position_size:.2f} below minimum ${MIN_POSITION_SIZE}'
            }

        # Check portfolio limits
        if len(current_positions) >= self.max_positions:
            return {
                'recommendation': 'PORTFOLIO_FULL',
                'position_size_usd': final_position_size,
                'kelly_fraction': safe_kelly,
                'edge': edge,
                'reason': f'Maximum positions ({self.max_positions}) already reached'
            }

        return {
            'recommendation': 'TAKE_POSITION',
            'position_size_usd': final_position_size,
            'kelly_fraction': safe_kelly,
            'edge': edge,
            'full_kelly': full_kelly,
            'expected_return': (1 - market_price) / market_price,
            'risk_amount': final_position_size * 0.10,  # Assuming 10% stop-loss
            'reason': f'Positive edge of {edge:.1%} warrants ${final_position_size:.2f} position'
        }

    def _calculate_available_capital(self, current_positions):
        """
        Calculate available capital considering reserves and allocated capital.

        Args:
            current_positions (list): Current portfolio positions

        Returns:
            float: Available capital for new position
        """
        # Reserve requirement (always keep this much cash)
        reserve_amount = self.bankroll * MIN_RESERVE_PCT

        # Capital already allocated to positions
        allocated_capital = sum(pos.get('size_usd', 0) for pos in current_positions)

        # Available capital
        available = self.bankroll - reserve_amount - allocated_capital

        return max(0, available)

    def calculate_position_shares(self, position_size_usd, price):
        """
        Convert USD position size to number of shares.

        Args:
            position_size_usd (float): Position size in USD
            price (float): Price per share

        Returns:
            int: Number of shares to buy
        """
        if price <= 0:
            return 0

        shares = position_size_usd / price
        return int(shares)

    def check_portfolio_constraints(self, current_positions, new_market_category=None):
        """
        Check if new position would violate portfolio constraints.

        Args:
            current_positions (list): Current portfolio positions
            new_market_category (str): Category of new market

        Returns:
            dict: Constraint check results
        """
        constraints = {
            'position_count': len(current_positions) < self.max_positions,
            'capital_usage': self._check_capital_usage(current_positions),
            'category_concentration': self._check_category_limits(current_positions, new_market_category)
        }

        all_constraints_met = all(constraints.values())
        constraints['all_met'] = all_constraints_met

        return constraints

    def _check_capital_usage(self, current_positions, max_usage=0.80):
        """
        Check if capital usage is within limits.

        Args:
            current_positions (list): Current positions
            max_usage (float): Maximum capital usage (default 80%)

        Returns:
            bool: True if within limits
        """
        allocated_capital = sum(pos.get('size_usd', 0) for pos in current_positions)
        usage_ratio = allocated_capital / self.bankroll
        return usage_ratio <= max_usage

    def _check_category_limits(self, current_positions, new_category, max_category_pct=0.40):
        """
        Check category concentration limits.

        Args:
            current_positions (list): Current positions
            new_category (str): Category of new position
            max_category_pct (float): Max concentration per category

        Returns:
            bool: True if within limits
        """
        if not new_category:
            return True  # No category specified, allow

        category_exposure = sum(
            pos.get('size_usd', 0)
            for pos in current_positions
            if pos.get('category') == new_category
        )

        new_total_exposure = category_exposure + self.max_position_size
        exposure_ratio = new_total_exposure / self.bankroll

        return exposure_ratio <= max_category_pct

    def get_portfolio_summary(self, current_positions):
        """
        Get summary of current portfolio state.

        Args:
            current_positions (list): Current portfolio positions

        Returns:
            dict: Portfolio summary
        """
        total_capital = sum(pos.get('size_usd', 0) for pos in current_positions)
        available_capital = self._calculate_available_capital(current_positions)

        # Category breakdown
        categories = {}
        for pos in current_positions:
            cat = pos.get('category', 'Unknown')
            categories[cat] = categories.get(cat, 0) + pos.get('size_usd', 0)

        return {
            'total_bankroll': self.bankroll,
            'allocated_capital': total_capital,
            'available_capital': available_capital,
            'capital_usage_pct': (total_capital / self.bankroll) * 100,
            'position_count': len(current_positions),
            'remaining_slots': self.max_positions - len(current_positions),
            'category_breakdown': categories,
            'reserve_requirement': self.bankroll * MIN_RESERVE_PCT
        }


if __name__ == "__main__":
    """
    Test position sizer functionality.
    """
    print("=" * 80)
    print("Position Sizer - Test")
    print("=" * 80)

    # Create sizer instance
    sizer = PositionSizer(bankroll=5000, max_position_size=500, max_positions=8)

    # Test scenarios
    test_scenarios = [
        {
            'name': 'Strong Edge Opportunity',
            'market_price': 0.94,
            'your_confidence': 0.98,
            'current_positions': []
        },
        {
            'name': 'Small Edge Opportunity',
            'market_price': 0.92,
            'your_confidence': 0.95,
            'current_positions': []
        },
        {
            'name': 'No Edge Opportunity',
            'market_price': 0.95,
            'your_confidence': 0.94,
            'current_positions': []
        },
        {
            'name': 'Portfolio Nearly Full',
            'market_price': 0.93,
            'your_confidence': 0.97,
            'current_positions': [
                {'size_usd': 400, 'category': 'Sports'},
                {'size_usd': 350, 'category': 'Politics'},
                {'size_usd': 450, 'category': 'Economics'},
                {'size_usd': 300, 'category': 'Sports'},
                {'size_usd': 500, 'category': 'Technology'},
                {'size_usd': 250, 'category': 'Politics'},
                {'size_usd': 400, 'category': 'Economics'}
            ]
        }
    ]

    print(f"\n📊 Testing {len(test_scenarios)} scenarios...")

    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n{i}. {scenario['name']}")
        print(f"   Market Price: ${scenario['market_price']:.2f}")
        print(f"   Your Confidence: {scenario['your_confidence']:.1%}")

        # Calculate position size
        result = sizer.calculate_kelly_position(
            scenario['market_price'],
            scenario['your_confidence'],
            scenario['current_positions']
        )

        print(f"   Recommendation: {result['recommendation']}")
        print(f"   Position Size: ${result['position_size_usd']:.2f}")
        print(f"   Kelly Fraction: {result['kelly_fraction']:.1%}")
        print(f"   Edge: {result['edge']:.1%}")
        print(f"   Reason: {result['reason']}")

        # Calculate shares if taking position
        if result['recommendation'] == 'TAKE_POSITION':
            shares = sizer.calculate_position_shares(
                result['position_size_usd'],
                scenario['market_price']
            )
            print(f"   Shares to Buy: {shares}")

    print(f"\n" + "=" * 60)

    # Test portfolio constraints
    print(f"\n🔍 Testing Portfolio Constraints...")

    current_positions = [
        {'size_usd': 400, 'category': 'Sports'},
        {'size_usd': 350, 'category': 'Politics'},
        {'size_usd': 300, 'category': 'Sports'}
    ]

    constraints = sizer.check_portfolio_constraints(current_positions, 'Sports')
    print(f"   Position Count: {constraints['position_count']}")
    print(f"   Capital Usage: {constraints['capital_usage']}")
    print(f"   Category Concentration: {constraints['category_concentration']}")
    print(f"   All Constraints Met: {constraints['all_met']}")

    # Portfolio summary
    summary = sizer.get_portfolio_summary(current_positions)
    print(f"\n📊 Portfolio Summary:")
    print(f"   Total Bankroll: ${summary['total_bankroll']:,.2f}")
    print(f"   Allocated Capital: ${summary['allocated_capital']:,.2f}")
    print(f"   Available Capital: ${summary['available_capital']:,.2f}")
    print(f"   Capital Usage: {summary['capital_usage_pct']:.1f}%")
    print(f"   Position Count: {summary['position_count']}/{summary['remaining_slots'] + summary['position_count']}")

    print("\nPosition Sizer test complete!")
    print("=" * 80)