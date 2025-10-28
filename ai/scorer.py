"""
Opportunity Scorer for Polymarket tail-end trading strategy
Task 2.2.2: Create ai/scorer.py

Provides weighted scoring system that balances:
- Arbitrage profit potential (edge over market)
- Risk factors (settlement time, liquidity, market consensus)
- Probability weighting (higher probability = higher score)

This scorer replaces simple probability-based scoring with
comprehensive risk-adjusted opportunity assessment.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    PRICE_MIN, PRICE_MAX,
    MIN_VOLUME_24H, MIN_BID_DEPTH,
    MIN_SETTLEMENT_HOURS, MAX_SETTLEMENT_DAYS,
    MAX_SPREAD_PCT, MIN_LIQUIDITY_RATIO,
    MIN_RESOLUTION_CLARITY, MIN_EVENT_FINALITY,
    MAX_CATEGORY_EXPOSURE_PCT, MAX_POSITIONS,
    BANKROLL_USD, DEFAULT_POSITION_SIZE,
    TRADING_FEE_PCT
)

class OpportunityScorer:
    """
    Scores trading opportunities on multiple risk-adjusted factors.

    Scoring Criteria:
    - Base profit potential (arbitrage edge)
    - Settlement time risk (optimal windows)
    - Liquidity sufficiency (order book depth)
    - Market consensus strength (crowd vs professional disagreement)
    - Event finality (definitive outcomes)
    - Resolution clarity (unambiguous criteria)
    - Category concentration risk
    - Portfolio fit (position limits)

    Each factor contributes 0-10 points to final score.
    """

    def __init__(self):
        """Initialize the scorer with default weights."""
        print("Opportunity Scorer initialized")
        print("   Risk-adjusted scoring for tail-end arbitrage")

    def calculate_base_profit_potential(self, market):
        """
        Calculate base arbitrage profit potential.

        For tail-end markets (85-97% probability), calculate:
        - Expected value: probability × $1.00 settlement
        - Current cost: market price
        - Gross profit: $1.00 - market price
        - Gross profit %: (1.00 - market price) / market price × 100

        Higher markets = lower profit potential but higher win probability
        """
        probability = market['yes_price']
        current_price = probability

        # Expected value if YES wins
        expected_value = probability * 1.00  # Settles at $1.00

        # Current price (what we pay)
        # For tail-end strategy: we buy YES position
        current_cost = current_price

        # Gross profit if YES wins
        gross_profit = 1.00 - current_cost
        gross_profit_pct = gross_profit / current_cost * 100

        # Base profit score (0-10 points)
        # Higher profit potential = higher score
        base_profit_score = min(10, gross_profit_pct * 10)

        return {
            'base_profit_score': base_profit_score,
            'gross_profit_pct': gross_profit_pct,
            'expected_value': expected_value,
            'current_cost': current_cost
            'probability': probability
        }

    def calculate_settlement_risk_score(self, market):
        """
        Score settlement time risk.

        Optimal: 6h - 30 days (perfect for capital efficiency)
        Too soon: <6h (high volatility)
        Too long: >30 days (capital tied up)

        Risk score: 0-10 points
        """
        days_to_settlement = market.get('days_to_settlement', 0)

        if days_to_settlement < 6:
            settlement_risk_score = 0  # Too soon = high volatility risk
        elif days_to_settlement > 30:
            settlement_risk_score = -5  # Too long = capital inefficiency risk
        else:
            settlement_risk_score = 10  # Optimal window

        return {
            'settlement_risk_score': settlement_risk_score,
            'days_to_settlement': days_to_settlement,
            'risk_assessment': 'Optimal' if settlement_risk_score == 10 else 'Too soon' if settlement_risk_score == 0 else 'Too long'
        }

    def calculate_liquidity_risk_score(self, market):
        """
        Score liquidity sufficiency.

        Good: ≥$50K total liquidity AND ≥$200 bid depth
        Moderate: ≥$20K total liquidity OR ≥$100 bid depth
        Poor: <$10K total liquidity AND <$50 bid depth

        Risk score: 0-10 points
        """
        volume_proxy = market.get('volume_proxy', 0)
        bid_depth = market.get('bid_depth', 0)

        if volume_proxy >= 50000 and bid_depth >= 200:
            liquidity_risk_score = 10  # Excellent liquidity
        elif volume_proxy >= 20000 or bid_depth >= 100:
            liquidity_risk_score = 7  # Good liquidity
        elif volume_proxy >= 10000 or bid_depth >= 50:
            liquidity_risk_score = 4  # Moderate liquidity
        else:
            liquidity_risk_score = 0  # Poor liquidity

        return {
            'liquidity_risk_score': liquidity_risk_score,
            'volume_proxy': volume_proxy,
            'bid_depth': bid_depth,
            'liquidity_assessment': 'Excellent' if liquidity_risk_score >= 7 else 'Good' if liquidity_risk_score >= 4 else 'Moderate' if liquidity_risk_score >= 1 else 'Poor'
        }

    def calculate_consensus_risk_score(self, market):
        """
        Score market consensus strength vs. professional disagreement.

        Risk: Large disagreement suggests uncertain outcome

        For tail-end strategy, we need to estimate if professionals disagree significantly
        This is a proxy for market maker confidence levels.

        Score: 0-10 points
        """
        from config import DEFAULT_POSITION_SIZE

        # Get liquidity data to estimate professional bid levels
        best_bid = market.get('best_bid_price', 0)

        # Calculate professional confidence based on bid price
        if best_bid <= 0.05:  # 5¢ bid = 95% NO confidence
            professional_confidence = 0  # Disagree with consensus
        elif best_bid <= 0.10:  # 10¢ bid = 90% NO confidence
            professional_confidence = 2  # Minor disagreement
        elif best_bid <= 0.15:  # 15¢ bid = 85% NO confidence
            professional_confidence = 4  # Moderate disagreement
        elif best_bid <= 0.20:  # 20¢ bid = 80% NO confidence
            professional_confidence = 6  # Some disagreement
        else:
            professional_confidence = 8  # Strong disagreement with consensus

        # Calculate consensus gap
        market_price = market['yes_price']
        professional_probability = 1 - professional_confidence / 10  # Convert to probability
        consensus_gap = abs(market_price - professional_probability)

        # Risk scoring (higher gap = higher risk)
        if consensus_gap >= 0.30:  # 30% or more disagreement
            consensus_risk_score = -8  # Dangerous disagreement
        elif consensus_gap >= 0.20:  # 20-29% disagreement
            consensus_risk_score = -5  # Significant disagreement
        elif consensus_gap >= 0.10:  # 10-19% disagreement
            consensus_risk_score = -2  # Minor disagreement
        else:
            consensus_risk_score = 0  # Good agreement

        return {
            'consensus_risk_score': consensus_risk_score,
            'consensus_gap': consensus_gap,
            'professional_confidence': professional_confidence,
            'professional_probability': professional_probability,
            'risk_assessment': 'Dangerous disagreement' if consensus_risk_score <= -5 else 'Significant disagreement' if consensus_risk_score <= -2 else 'Minor disagreement' else 'Good agreement'
        }

    def calculate_finality_risk_score(self, market):
        """
        Score event finality and outcome definiteness.

        Risk: Events that could be cancelled, modified, or have ambiguous outcomes

        Score: 0-10 points
        """
        question = market.get('question', '').lower()
        finality_score = 0

        # High finality indicators (8-10 points each)
        if any(term in question for term in [
            'election', 'official', 'federal', 'government', 'binding', 'contract', 'legal', 'ruling',
            'outcome', 'wins', 'passes', 'achieves', 'completes'
        ]):
            finality_score += 8  # Definitive outcome

        if any(source in question for source in [
            'official', 'federal', 'court', 'results', 'data', 'statistics'
        ]):
            finality_score += 8  # Based on official data

        if any(measure in question for measure in [
            '%', 'majority', '>', '<', 'at least', 'votes', 'polling'
        ]):
            finality_score += 8  # Objectively measurable

        # Medium finality indicators (6-7 points each)
        if any(event_type in question for event_type in [
            'reference', 'benchmark', 'comparison', 'relative', 'estimated', 'forecast'
        ]):
            finality_score += 7  # Well-documented but verifiable

        # Low finality indicators (0-5 points each)
        if any(unclear in question for unclear in [
            'unclear', 'depends', 'subject to', 'might', 'could', 'possibly', 'potential'
        ]):
            finality_score -= 5  # Unverifiable

        # Risk assessment
        if finality_score >= 8:
            risk_assessment = 'Very Low Risk'
        elif finality_score >= 6:
            risk_assessment = 'Low Risk'
        elif finality_score >= 4:
            risk_assessment = 'Medium Risk'
        else:
            risk_assessment = 'High Risk'

        return {
            'finality_risk_score': finality_score,
            'risk_assessment': risk_assessment,
            'finality_indicators': [
                'definitive_outcome' if 'definitive' in question else 0,
                'official_source' if any(source in question for source in ['official', 'federal']) else 0,
                'verifiable' if any(measure in question for measure in ['%', 'votes', 'data']) else 0
            ]
        ]
        }

    def calculate_resolution_clarity_score(self, market):
        """
        Score resolution clarity based on market question analysis.

        Score: 0-10 points
        """
        question = market.get('question', '').lower()
        clarity_score = 0

        # High clarity indicators (8-10 points each)
        if any(term in question for term in ['will', 'will there be', 'will win', 'is']):
            clarity_score += 8  # Binary outcome naturally clear

        if any(term in question for term in ['date', 'deadline', 'by', 'before', 'after']):
            clarity_score += 8  # Specific timing

        if any(source in question for source in [
            'election', 'official', 'federal', 'government', 'supreme court'
        ]):
            clarity_score += 8  # Based on official sources

        # Medium clarity indicators (6-7 points each)
        if any(measure in question for measure in [
            '%', 'majority', '>', '<', 'at least'
        ]):
            clarity_score += 7  # Objectively measurable criteria

        # Penalize ambiguous criteria
        if any(ambiguous in question for ambiguous in [
            'unclear', 'uncertain', 'depends on', 'subject to', 'complex', 'multiple'
        ]):
            clarity_score -= 5  # Ambiguous terms

        # Low clarity indicators (0-5 points each)
        if any(vague in question for vague in [
            'vague', 'unclear', 'subjective', 'opinion'
        ]):
            clarity_score -= 2  # Vague language

        # Risk assessment
        if clarity_score >= 8:
            risk_assessment = 'Very Low Risk'
        elif clarity_score >= 6:
            risk_assessment = 'Low Risk'
        elif clarity_score >= 4:
            risk_assessment = 'Medium Risk'
        else:
            risk_assessment = 'High Risk'

        return {
            'resolution_clarity_score': clarity_score,
            'risk_assessment': risk_assessment,
            'clarity_indicators': [
                'binary_outcome' if any(term in question for term in ['will', 'will there be', 'will win', 'is']) else 0,
                'specific_date' if any(date in question for date in ['date', 'deadline', 'by', 'before', 'after']) else 0,
                'official_source' if any(source in question for source in ['election', 'official', 'federal']) else 0,
                'measurable' if any(measure in question for measure in ['%', 'majority', '>', '<', 'at least']) else 0
            ]
        ]
        }

    def calculate_portfolio_fit_score(self, market, positions):
        """
        Score portfolio fit based on concentration limits.

        Score: 0-10 points
        """
        from config import MAX_CATEGORY_EXPOSURE_PCT, MAX_POSITIONS

        category = market.get('category', 'Unknown')

        # Get current portfolio composition
        category_counts = {}
        for position in positions:
            pos_category = position.get('category', 'Unknown')
            category_counts[pos_category] = category_counts.get(pos_category, 0) + 1

        # Calculate category exposure
        total_positions = len(positions)
        category_exposure = category_counts.get(category, 0) / total_positions * 100 if total_positions > 0 else 0

        # Risk assessment
        if category_exposure >= MAX_CATEGORY_EXPOSURE_PCT:
            portfolio_fit_score = -10  # Over-concentrated category
        elif category_exposure >= 70:
            portfolio_fit_score = -5  # High concentration
        elif category_exposure >= 40:
            portfolio_fit_score = 0  # Moderate concentration
        else:
            portfolio_fit_score = 5  # Well diversified

        # Position limit check
        if total_positions >= MAX_POSITIONS:
            portfolio_fit_score = -10  # Position limit exceeded
        else:
            portfolio_fit_score = 5  # Within limits

        # Overall portfolio score
        overall_score = min(portfolio_fit_score, 0)  # Start at 5, penalize for over-concentration

        return {
            'portfolio_fit_score': overall_score,
            'category': category,
            'category_exposure': category_exposure,
            'total_positions': total_positions,
            'max_positions': MAX_POSITIONS,
            'risk_assessment': 'Very Low Risk' if overall_score < 0 else 'Low Risk'
        }

    def score_opportunity(self, market, positions=None):
        """
        Calculate comprehensive opportunity score.

        Combines all scoring factors into a single score (0-100).
        Higher score = better opportunity.
        """
        scores = {}

        # Individual factor scores (0-10 points each)
        scores['base_profit'] = self.calculate_base_profit_potential(market)
        scores['settlement_risk'] = self.calculate_settlement_risk_score(market)
        scores['liquidity'] = self.calculate_liquidity_risk_score(market)
        scores['consensus'] = self.calculate_consensus_risk_score(market)
        scores['finality'] = self.calculate_finality_risk_score(market)
        scores['resolution_clarity'] = self.calculate_resolution_clarity_score(market)
        scores['portfolio_fit'] = self.calculate_portfolio_fit_score(market, positions)

        # Calculate weighted scores
        # Profit potential is most important (30% weight)
        weights = {
            'base_profit': 0.30,        # 30% - profit edge is critical
            'settlement_risk': 0.20,      # Settlement timing affects capital efficiency
            'liquidity': 0.20,          # Liquidity needed for trading
            'consensus': 0.25,         # Market consensus disagreement
            'finality': 0.10,           # Definitive outcomes
            'resolution_clarity': 0.15,     # Clear resolution criteria
            'portfolio_fit': 0.10           # Portfolio diversification
        }

        # Calculate weighted score
        total_score = sum(
            scores[factor] * weights[factor]
            for factor, scores[factor] in scores.items()
        )

        # Normalize to 0-100 scale
        final_score = max(0, min(100, total_score))

        # Risk assessment based on score
        if final_score >= 70:
            risk_assessment = 'Low Risk - High Quality Opportunity'
        elif final_score >= 50:
            risk_assessment = 'Medium Risk - Good Opportunity'
        elif final_score >= 30:
            risk_assessment = 'Medium Risk - Acceptable Opportunity'
        else:
            risk_assessment = 'High Risk - Speculative Opportunity'

        # Determine recommendation
        if final_score >= 60:
            recommendation = 'STRONG BUY - High conviction'
        elif final_score >= 40:
            recommendation = 'BUY - Good opportunity'
        elif final_score >= 20:
            recommendation = 'CONSIDER - Monitor closely'
        else:
            recommendation = 'AVOID - High risk opportunity'

        return {
            'final_score': final_score,
            'scores': scores,
            'total_score': total_score,
            'recommendation': recommendation,
            'risk_assessment': risk_assessment
        }

    def get_scoring_breakdown(self, market):
        """Return detailed breakdown for a single market score."""
        scores = self.score_opportunity(market)

        breakdown = {}
        breakdown['base_profit'] = {
            'score': scores['base_profit'],
            'weight': weights['base_profit'],
            'weighted': scores['base_profit'] * weights['base_profit'],
            'details': {
                'gross_profit_pct': scores['base_profit']['gross_profit_pct'],
                'expected_value': scores['base_profit']['expected_value'],
                'current_cost': scores['base_profit']['current_cost'],
                'probability': scores['base_profit']['probability']
            }
        }

        for factor_name in ['settlement_risk', 'liquidity', 'consensus', 'finality', 'resolution_clarity', 'portfolio_fit']:
            breakdown[factor_name] = {
                'score': scores[factor_name],
                'weight': weights[factor_name],
                'weighted': scores[factor_name] * weights[factor_name],
                'raw_score': scores[factor_name]
            }

        return {
            'total_score': scores['final_score'],
            'breakdown': breakdown,
            'weights': weights,
            'recommendation': scores['recommendation']
        }


if __name__ == "__main__":
    """
    Test the Opportunity Scorer with sample data.
    """
    print("=" * 80)
    print("Opportunity Scorer Test")
    print("=" * 80)

    # Sample markets with different characteristics
    test_markets = [
        {
            'question': 'Will Trump win 2024 election?',
            'yes_price': 0.85,
            'volume_proxy': 50000,
            'bid_depth': 200,
            'days_to_settlement': 365
        },
        {
            'question': 'Will Fed cut rates by December?',
            'yes_price': 0.88,
            'volume_proxy': 15000,
            'bid_depth': 50,
            'days_to_settlement': 30
        },
        {
            'question': 'Will Company X beat earnings?',
            'yes_price': 0.75,
            'volume_proxy': 250000,
            'bid_depth': 500,
            'days_to_settlement': 90
        },
        {
            'question': 'Will legislation pass by year end?',
            'yes_price': 0.92,
            'volume_proxy': 800000,
            'bid_depth': 1000,
            'days_to_settlement': 15
        }
    ]

    scorer = OpportunityScorer()

    print("\n" + "=" * 80)
    print("Scoring Test Markets")
    print("=" * 80)

    for i, market in enumerate(test_markets, 1):
        print(f"\n{i}. {market['question']}")

        score_result = scorer.score_opportunity(market)

        print(f"   Total Score: {score_result['final_score']:.1f}")
        print(f"  Recommendation: {score_result['recommendation']}")
        print(f"   Risk Assessment: {score_result['risk_assessment']}")

        breakdown = scorer.get_scoring_breakdown(market)
        print(f"   Base Profit: {breakdown['base_profit']['score']:.1f} (weighted: {breakdown['base_profit']['weighted']:.1f})")
        print(f"     Gross Profit: {breakdown['base_profit']['gross_profit_pct']:.1f}%")
        print(f"     Current Cost: ${breakdown['base_profit']['current_cost']:.3f}")
        print(f"     Expected Value: ${breakdown['base_profit']['expected_value']:.3f}")

        print(f"\n   Factor Scores:")
        for factor_name, factor_data in breakdown.items():
            if factor_name != 'base_profit':
                print(f"   {factor_name}: {factor_data['score']:.1f} (weighted: {factor_data['weighted']:.1f})")
                if factor_name == 'settlement_risk':
                    print(f"      Risk: {factor_data['raw_score']} days={breakdown['settlement_risk']['days_to_settlement']:.0f}d")
                elif factor_name == 'liquidity':
                    print(f"      Risk: {factor_data['risk_assessment']} volume=${breakdown['liquidity']['volume_proxy']:,.0f}")
                elif factor_name == 'consensus':
                    print(f"      Risk: {factor_data['risk_assessment']} gap={breakdown['consensus']['consensus_gap']:.1f}")

        print(f"\n" + "-" * 60)

    print("=" * 80)
    print("Opportunity Scorer Test Complete!")
    print("=" * 80)