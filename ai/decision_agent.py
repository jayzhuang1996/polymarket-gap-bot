"""
AI Decision Agent for Polymarket trading strategy
Task 2.2.2: Create ai/decision_agent.py

Uses Claude API to analyze opportunities and provide trading recommendations.
Integrates with opportunity scorer to make risk-adjusted decisions.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import ANTHROPIC_API_KEY

class DecisionAgent:
    """
    AI-powered decision engine for tail-end arbitrage trading.

    Analyzes opportunity scores, market context, and provides
    trading recommendations with risk assessment.
    """

    def __init__(self, anthropic_api_key=None):
        """
        Initialize decision agent with API key.
        """
        if anthropic_api_key:
            self.api_key = anthropic_api_key
            print("✅ Decision Agent initialized with Claude API")
        else:
            print("❌ No ANTHROPIC_API_KEY found in environment")
            print("⚠️  Decision Agent will be simulated (no API calls)")
            self.api_key = None

    def analyze_opportunity(self, market_data, scores):
        """
        Analyze a trading opportunity and provide recommendation.

        Args:
            market_data (dict): Market with opportunity analysis
            scores (dict): Risk-adjusted scores from OpportunityScorer

        Returns:
            dict: AI analysis and recommendation
        """
        if not self.api_key:
            return self._simulate_analysis(market_data, scores)

        # Create prompt for Claude with market context and scores
        prompt = self._create_analysis_prompt(market_data, scores)

        try:
            # Import Claude (simulate API call)
            import anthropic

            client = anthropic.Anthropic(
                api_key=self.api_key,
                max_retries=2,
                timeout=30
            )

            print(f"\n🤖 Sending opportunity to Claude for analysis...")

            # Get Claude's analysis
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                temperature=0.3,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Get Claude's response
            claude_response = response.content[0].content.strip()

            return self._parse_claude_response(claude_response, market_data, scores)

        except Exception as e:
            print(f"❌ Claude API call failed: {e}")
            return {
                'error': str(e),
                'recommendation': 'API error - cannot analyze opportunity',
                'claude_analysis': None
            }

    def _simulate_analysis(self, market_data, scores):
        """
        Simulate Claude analysis when no API key available.

        Returns mock analysis based on scoring logic.
        """
        print("🔍 Simulating Claude analysis...")

        # Simulate different recommendation scenarios
        if scores['base_profit']['gross_profit_pct'] >= 15:
            recommendation = "STRONG BUY - Exceptional profit opportunity (15%+ edge)"
        elif scores['consensus']['consensus_gap'] >= 0.50:
            recommendation = "AVOID HIGH CONSENSUS - Market makers strongly disagree"
        elif scores['settlement_risk']['days_to_settlement'] > 45:
            recommendation = "AVOID LONG SETTLEMENT - Capital efficiency risk"
        elif scores['liquidity']['liquidity_assessment'] == 'Poor':
            recommendation = "AVOID POOR LIQUIDITY - Exit risk concerns"
        elif scores['finality']['risk_assessment'] == 'High Risk':
            recommendation = "AVOID UNCERTAIN EVENTS - Cancellation/modification risk"
        else:
            recommendation = "CONSIDER CAREFULLY - Good balance of risk factors"

        risk_summary = {
            'profit_edge': scores['base_profit']['gross_profit_pct'],
            'settlement_risk': scores['settlement_risk']['risk_assessment'],
            'liquidity_risk': scores['liquidity']['liquidity_assessment'],
            'consensus_risk': scores['consensus']['risk_assessment'],
            'finality_risk': scores['finality']['risk_assessment'],
            'portfolio_risk': scores['portfolio_fit']['risk_assessment']
        }

        return {
            'recommendation': recommendation,
            'claude_analysis': f"Simulated analysis: {recommendation}",
            'risk_summary': risk_summary,
            'scores': scores
        }

    def _create_analysis_prompt(self, market_data, scores):
        """
        Create comprehensive prompt for Claude analysis.

        """
        market_summary = f"""
Market: {market_data.get('question', 'Unknown')}
Current Price: ${market_data.get('yes_price', 0):.3f}
Probability: {market_data.get('yes_price', 0) * 100:.1f}%
Settlement Date: {market_data.get('end_date', 'Unknown')}
        """

        opportunity_summary = f"""
Opportunity Analysis:
Base Profit Potential: {scores['base_profit']['gross_profit_pct']:.1f}% gross profit
Consensus Risk: {scores['consensus']['risk_assessment']} (gap: {scores['consensus']['consensus_gap']:.1f}%)
Settlement Risk: {scores['settlement_risk']['risk_assessment']} ({scores['settlement_risk']['days_to_settlement']} days)
Liquidity Risk: {scores['liquidity']['liquidity_assessment']} ({scores['liquidity']['liquidity_assessment']})
Event Finality: {scores['finality']['risk_assessment']} ({scores['finality']['risk_assessment']})
Portfolio Risk: {scores['portfolio_fit']['risk_assessment']}

Risk Summary: High Risk - Avoid consensus disagreement
        """

        instructions = f"""
You are a risk management AI assistant for a Polymarket tail-end arbitrage trading bot.

Your task is to analyze this trading opportunity and provide a recommendation. Consider:

1. PROFIT POTENTIAL: {scores['base_profit']['gross_profit_pct']:.1f}% gross profit
   - This represents a {1.00 - market_price} return if YES wins
   - Is this level of profit potential worth the settlement risk?

2. RISK FACTORS:
   - Market consensus: Market makers bid {scores['consensus']['professional_confidence']}% NO probability
   - Settlement timing: {scores['settlement_risk']['days_to_settlement']} days until resolution
   - Liquidity availability: {scores['liquidity']['liquidity_assessment']} for position exits
   - Event finality: {scores['finality']['risk_assessment']} potential cancellation/modification

3. TRADING STRATEGY:
   - This is a tail-end arbitrage strategy
   - Plan: Buy YES position, hold until settlement
   - Success depends on outcome accuracy, not entry timing

4. RECOMMENDATION GUIDELINES:
   - Focus on actual settlement risks, not spread width
   - Strong consensus strength suggests questionable opportunity quality
   - Consider: Is this disagreement a trading signal or information advantage?

Please provide:
1. TRADING RECOMMENDATION: Buy, Sell, or Hold?
2. RISK LEVEL ASSESSMENT: High, Medium, or Low?
3. CONFIDENCE LEVEL IN YOUR ANALYSIS: How confident are you in this assessment?
4. ANY ADDITIONAL FACTORS: News, insider information, market conditions?

Your analysis should help the human operator make an informed decision.
"""

        return prompt + market_summary + opportunity_summary

    def _parse_claude_response(self, claude_response, market_data, scores):
        """
        Parse Claude's response to extract recommendation.

        Claude's responses often include analysis at the end.
        """
        lines = claude_response.split('\n')

        recommendation = "CONSIDER CAREFULLY"

        for line in lines:
            if any(keyword in line.lower() for keyword in ['buy', 'sell', 'hold', 'avoid', 'recommend']):
                recommendation = "AVOID"  # Claude suggests avoiding
            elif any(keyword in line.lower() for keyword in ['strong buy', 'strong sell', 'excellent']):
                recommendation = "STRONG BUY"  # Claude is very confident
            elif any(keyword in line.lower() for keyword in ['avoid', 'risk', 'be cautious']):
                recommendation = "AVOID HIGH RISK"
            elif any(keyword in line.lower() for keyword in ['monitor', 'watch', 'careful']):
                recommendation = "MONITOR CLOSELY"
            elif 'profit' in line.lower() and float(line.split('%')[-1]) > 0.15:  # 15% profit
                recommendation = "STRONG BUY"

        return recommendation

    def get_opportunity_score(self, market_data, scores):
        """
        Generate final opportunity score based on risk-adjusted factors.

        Args:
            market_data (dict): Market information
            scores (dict): Risk assessment scores from OpportunityScorer

        Returns:
            dict: Final scoring with recommendation
        """
        # Extract key metrics for final decision
        profit_edge = scores['base_profit']['gross_profit_pct']
        consensus_risk = scores['consensus']['risk_assessment']
        settlement_risk = scores['settlement_risk']['risk_assessment']
        liquidity_risk = scores['liquidity']['risk_assessment']

        # Simple scoring logic for final recommendation
        if (profit_edge >= 10 and
            consensus_risk == 'Low Risk' and
            settlement_risk == 'Low Risk' and
            liquidity_risk != 'Poor'):
            final_score = min(90, profit_edge * 5)  # Strong opportunity
            recommendation = "STRONG BUY"
        elif (profit_edge >= 5 and
              consensus_risk != 'High Risk' and
              settlement_risk != 'High Risk'):
            final_score = min(70, profit_edge * 4)  # Good opportunity
            recommendation = "CONSIDER BUYING"
        else:
            final_score = min(40, profit_edge * 2)  # Weak opportunity
            recommendation = "AVOID OR MONITOR"

        return {
            'final_score': final_score,
            'recommendation': recommendation,
            'key_factors': {
                'profit_edge_pct': profit_edge,
                'consensus_risk': consensus_risk,
                'settlement_risk': settlement_risk,
                'liquidity_risk': liquidity_risk
            }
        }


if __name__ == "__main__":
    """
    Test decision agent functionality.
    """
    print("=" * 80)
    print("AI Decision Agent - Test")
    print("=" * 80)

    # Create decision agent instance
    agent = DecisionAgent()

    # Test with sample opportunity
    sample_market = {
        'question': 'Will Fed cut interest rates by December 2024?',
        'yes_price': 0.94,
        'end_date': '2024-12-31',
        'bid_depth': 50000,
        'ask_depth': 45000
    }

    sample_scores = {
        'base_profit': {'gross_profit_pct': 6.4},
        'consensus': {'risk_assessment': 'Low Risk', 'consensus_gap': 0.15},
        'settlement_risk': {'risk_assessment': 'Low Risk', 'days_to_settlement': 15},
        'liquidity': {'liquidity_assessment': 'Good'},
        'finality': {'risk_assessment': 'Low Risk'},
        'portfolio_fit': {'risk_assessment': 'Low Risk'}
    }

    print(f"\n🤖 Analyzing opportunity: {sample_market['question'][:50]}...")

    # Get AI analysis
    analysis = agent.analyze_opportunity(sample_market, sample_scores)

    print(f"\n📊 Analysis Results:")
    print(f"   Recommendation: {analysis['recommendation']}")
    print(f"   Risk Summary: {analysis.get('risk_summary', 'N/A')}")

    if 'claude_analysis' in analysis:
        print(f"   AI Analysis: {analysis['claude_analysis'][:100]}...")

    print(f"\n" + "=" * 60)
    print("Decision Agent test complete!")
    print("=" * 80)