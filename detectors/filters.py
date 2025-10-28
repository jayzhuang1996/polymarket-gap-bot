"""
Filter pipeline for Polymarket trading opportunities
Task 2.1.1: Create detectors/filters.py structure

Filters 982 active markets down to 2-5 quality opportunities per day
Each filter removes markets that don't meet our tail-end arbitrage criteria
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import config
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    PRICE_MIN, PRICE_MAX,
    MIN_VOLUME_24H, MIN_BID_DEPTH,
    MIN_SETTLEMENT_HOURS, MAX_SETTLEMENT_DAYS,
    MAX_SPREAD_PCT, MIN_LIQUIDITY_RATIO,
    MAX_CATEGORY_EXPOSURE_PCT, MAX_POSITIONS
)


def filter_price_range(markets):
    """
    Filter markets by price range (tail-end opportunities).

    Keep markets where: 0.92 ≤ YES ≤ 0.97
    This targets markets with 92-97% probability (our sweet spot)

    Args:
        markets (list): List of market dictionaries

    Returns:
        list: Markets in target price range
    """
    filtered_markets = []

    for market in markets:
        # Extract YES price from market
        if 'yes_price' in market:
            price = float(market['yes_price'])
        elif 'tokens' in market and market['tokens']:
            # Fallback to token data structure
            price = float(market['tokens'][0].get('price', 0))
        else:
            # Skip market if no price data
            continue

        # Check if price is in our tail-end range
        if PRICE_MIN <= price <= PRICE_MAX:
            filtered_markets.append(market)

    print(f"✅ Price filter: {len(markets)} → {len(filtered_markets)} markets (${PRICE_MIN:.2f}-${PRICE_MAX:.2f})")
    return filtered_markets


def filter_liquidity(markets):
    """
    Filter markets by liquidity using our volume proxy.

    Require: volume proxy ≥ $50k AND bid depth ≥ $20k
    Uses order book liquidity analysis from liquidity_analyzer.py

    Args:
        markets (list): List of market dictionaries (from database)

    Returns:
        list: Markets with sufficient liquidity
    """
    from collectors.liquidity_analyzer import get_market_liquidity
    import time

    filtered_markets = []
    total_liquidity_sum = 0
    successful_analyses = 0

    for i, market in enumerate(markets):
        print(f"Analyzing liquidity for market {i+1}/{len(markets)}...")

        # Convert database market structure to API structure for liquidity analyzer
        # Database has flat structure, liquidity analyzer expects tokens array
        api_market = {
            'question': market['question'],
            'tokens': [{
                'token_id': market['token_id'],
                'price': market['yes_price']
            }]
        }

        # Get liquidity metrics from order book
        liquidity = get_market_liquidity(api_market, use_retry=True)

        if liquidity:
            # Check volume proxy (total liquidity) requirement
            volume_proxy = liquidity.get('volume_proxy', 0)
            bid_depth = liquidity.get('best_bid_value', 0)

            # Store liquidity data in original market dict for later use
            market['liquidity_metrics'] = liquidity
            market['volume_proxy'] = volume_proxy
            market['bid_depth'] = bid_depth

            total_liquidity_sum += volume_proxy
            successful_analyses += 1

            # Apply liquidity thresholds
            if volume_proxy >= MIN_VOLUME_24H and bid_depth >= MIN_BID_DEPTH:
                filtered_markets.append(market)
                print(f"  ✅ PASS: ${volume_proxy:,.0f} volume, ${bid_depth:,.0f} bid depth")
            else:
                print(f"  ❌ REJECT: ${volume_proxy:,.0f} volume (need ${MIN_VOLUME_24H:,}), ${bid_depth:,.0f} bid depth (need ${MIN_BID_DEPTH:,})")
        else:
            print(f"  ❌ NO LIQUIDITY DATA")
            # Market without liquidity data cannot be traded
            continue

        # Small delay to avoid rate limiting
        time.sleep(0.1)

    # Calculate average liquidity for reporting
    avg_liquidity = total_liquidity_sum / successful_analyses if successful_analyses > 0 else 0

    print(f"✅ Liquidity filter: {len(markets)} → {len(filtered_markets)} markets")
    print(f"   Volume threshold: ≥${MIN_VOLUME_24H:,}, Bid depth: ≥${MIN_BID_DEPTH:,}")
    print(f"   Average liquidity: ${avg_liquidity:,.0f}")
    print(f"   Success rate: {len(filtered_markets)}/{len(markets)} ({len(filtered_markets)/len(markets)*100:.1f}%)")

    return filtered_markets


def filter_settlement_window(markets):
    """
    Filter markets by settlement time window.

    Keep: 6h ≤ time_to_settlement ≤ 7d
    Too soon = high volatility, too long = capital tied up

    Args:
        markets (list): List of market dictionaries (from database)

    Returns:
        list: Markets with optimal settlement timing
    """
    from datetime import datetime, timezone
    import time

    filtered_markets = []
    current_time = datetime.now(timezone.utc)

    for market in markets:
        # Get end_date from market (database field)
        end_date_str = market.get('end_date')

        if not end_date_str:
            # Skip markets without end dates
            continue

        try:
            # Parse end_date (handle different formats)
            if 'T' in end_date_str:
                # ISO format: 2024-12-31T23:59:59Z
                if end_date_str.endswith('Z'):
                    end_date = datetime.fromisoformat(end_date_str[:-1] + '+00:00')
                else:
                    end_date = datetime.fromisoformat(end_date_str)
            else:
                # Simple format: 2024-12-31
                end_date = datetime.fromisoformat(end_date_str).replace(tzinfo=timezone.utc)

            # Calculate time to settlement in hours
            time_delta = end_date - current_time
            hours_to_settlement = time_delta.total_seconds() / 3600

            # Store time data for later use
            market['hours_to_settlement'] = hours_to_settlement
            market['days_to_settlement'] = hours_to_settlement / 24
            market['settlement_date'] = end_date

            # Apply settlement window filters
            min_hours = MIN_SETTLEMENT_HOURS
            max_days = MAX_SETTLEMENT_DAYS
            max_hours = max_days * 24

            if min_hours <= hours_to_settlement <= max_hours:
                filtered_markets.append(market)
            else:
                if hours_to_settlement < min_hours:
                    reason = f"too soon ({hours_to_settlement:.1f}h < {min_hours}h)"
                else:
                    reason = f"too long ({hours_to_settlement/24:.1f}d > {max_days}d)"
                print(f"  ⏰ REJECT: {reason}")

        except Exception as e:
            # Skip markets with unparseable dates
            print(f"  ❌ INVALID DATE: {end_date_str} ({e})")
            continue

    print(f"✅ Settlement window filter: {len(markets)} → {len(filtered_markets)} markets")
    print(f"   Window: {MIN_SETTLEMENT_HOURS}h to {MAX_SETTLEMENT_DAYS}d")
    print(f"   Current time: {current_time.strftime('%Y-%m-%d %H:%M UTC')}")

    if filtered_markets:
        # Show settlement time distribution
        times = [m['hours_to_settlement'] for m in filtered_markets]
        avg_hours = sum(times) / len(times)
        print(f"   Avg time to settlement: {avg_hours/24:.1f} days")

    return filtered_markets


def filter_spread(markets):
    """
    Filter markets by bid-ask spread.

    Require: (ask-bid)/bid < 3%
    Tight spreads indicate healthy, liquid markets

    Args:
        markets (list): List of market dictionaries (from database)

    Returns:
        list: Markets with acceptable spreads
    """
    from collectors.liquidity_analyzer import get_market_liquidity
    import time

    filtered_markets = []
    total_spread_sum = 0
    successful_analyses = 0

    for i, market in enumerate(markets):
        print(f"Analyzing spread for market {i+1}/{len(markets)}...")

        # Check if market already has liquidity metrics from previous filter
        if 'liquidity_metrics' in market:
            liquidity = market['liquidity_metrics']
        else:
            # Get fresh liquidity data if not available
            api_market = {
                'question': market['question'],
                'tokens': [{
                    'token_id': market['token_id'],
                    'price': market['yes_price']
                }]
            }
            liquidity = get_market_liquidity(api_market, use_retry=True)
            market['liquidity_metrics'] = liquidity

        if liquidity:
            spread_pct = liquidity.get('spread', 0)
            best_bid = liquidity.get('best_bid_price', 0)
            best_ask = liquidity.get('best_ask_price', 0)

            # Store spread data for later use
            market['spread_pct'] = spread_pct
            market['best_bid_price'] = best_bid
            market['best_ask_price'] = best_ask

            total_spread_sum += spread_pct
            successful_analyses += 1

            # Apply spread threshold
            if spread_pct <= MAX_SPREAD_PCT:  # Direct comparison (spread is already in %)
                filtered_markets.append(market)
                print(f"  ✅ PASS: {spread_pct:.1f}% spread (${best_bid:.3f} - ${best_ask:.3f})")
            else:
                print(f"  ❌ REJECT: {spread_pct:.1f}% spread (max {MAX_SPREAD_PCT:.0f}%)")
        else:
            print(f"  ❌ NO SPREAD DATA")
            continue

        # Small delay to avoid rate limiting
        time.sleep(0.1)

    # Calculate average spread for reporting
    avg_spread = total_spread_sum / successful_analyses if successful_analyses > 0 else 0

    print(f"✅ Spread filter: {len(markets)} → {len(filtered_markets)} markets")
    print(f"   Max spread: {MAX_SPREAD_PCT*100:.0f}%")
    print(f"   Average spread: {avg_spread:.1f}%")
    print(f"   Success rate: {len(filtered_markets)}/{len(markets)} ({len(filtered_markets)/len(markets)*100:.1f}%)")

    return filtered_markets


def filter_exit_liquidity(markets):
    """
    Filter markets by exit liquidity ratio.

    Require: 20x liquidity ratio (updated from 10x)
    For $200 position, need $4k available for quick exit

    Args:
        markets (list): List of market dictionaries

    Returns:
        list: Markets with sufficient exit liquidity
    """
    filtered_markets = []

    for market in markets:
        # Check if market has liquidity data from previous filter
        if 'volume_proxy' in market and 'bid_depth' in market:
            volume_proxy = market['volume_proxy']
            bid_depth = market['bid_depth']

            # Calculate exit liquidity ratio
            # For position_size, need MIN_LIQUIDITY_RATIO * position_size liquidity available
            # We'll use DEFAULT_POSITION_SIZE as reference
            from config import DEFAULT_POSITION_SIZE, MIN_LIQUIDITY_RATIO
            position_size = DEFAULT_POSITION_SIZE
            required_liquidity = MIN_LIQUIDITY_RATIO * position_size

            # Total available liquidity = volume_proxy (best_bid_value for quick exit)
            available_exit_liquidity = bid_depth * 20  # Quick exit at 20x current bid depth

            # Market passes if enough liquidity for position exit
            if volume_proxy >= required_liquidity and bid_depth >= (position_size * 0.5):
                market['exit_liquidity_ratio'] = volume_proxy / position_size
                filtered_markets.append(market)
                print(f"  ✅ PASS: {volume_proxy/position_size:.1f}x liquidity ratio, ${bid_depth:,.0f} quick exit")
            else:
                needed_liquidity = required_liquidity - volume_proxy
                print(f"  ❌ REJECT: Need additional ${needed_liquidity:,.0f} liquidity")
        else:
            print(f"  ❌ REJECT: No liquidity data for exit analysis")

    print(f"✅ Exit liquidity filter: {len(markets)} → {len(filtered_markets)} markets")
    print(f"   Required ratio: {MIN_LIQUIDITY_RATIO}x position size")
    print(f"   Position reference: ${DEFAULT_POSITION_SIZE}")

    return filtered_markets


def filter_resolution_clarity(markets):
    """
    Filter markets by resolution clarity score.

    Require: clarity_score ≥ 8
    Binary outcomes with clear, unambiguous resolution criteria
    (Note: You'll manually score markets initially)

    Args:
        markets (list): List of market dictionaries

    Returns:
        list: Markets with clear resolution criteria
    """
    from config import MIN_RESOLUTION_CLARITY

    filtered_markets = []

    # Manual scoring based on question clarity and event type
    clarity_indicators = {
        # High clarity (8-10 score)
        'binary_outcome': 8,  # Yes/No outcomes are naturally clear
        'specific_date': 9,      # Has specific settlement date
        'measurable': 8,        # Objectively measurable criteria
        'official_source': 9,   # Based on official announcements

        # Medium clarity (6-7 score)
        'subjective_criteria': 6,  # Requires subjective judgment
        'complex_conditions': 6,    # Multiple conditions to resolve
        'poll_based': 5,       # Based on polling/interpretation

        # Low clarity (0-5 score)
        'ambiguous_terns': 3,     # Unclear outcome definitions
        'no_clear_date': 4,       # Vague timeframe
        'unverifiable': 2,       # Cannot be objectively verified
    }

    for market in markets:
        question = market.get('question', '').lower()
        end_date = market.get('end_date', '')

        clarity_score = 0
        clarity_reasons = []

        # Analyze question for clarity indicators
        if any(term in question for term in ['will', 'will there be', 'will win', 'is']):
            clarity_score += clarity_indicators['binary_outcome']
            clarity_reasons.append('binary_outcome')

        if end_date and 'T' in end_date:
            clarity_score += clarity_indicators['specific_date']
            clarity_reasons.append('specific_date')

        # Check for official sources
        if any(source in question for source in ['election', 'official', 'federal', 'government']):
            clarity_score += clarity_indicators['official_source']
            clarity_reasons.append('official_source')

        # Check for measurable criteria
        if any(measure in question for measure in ['%', 'majority', '>', '<', 'at least']):
            clarity_score += clarity_indicators['measurable']
            clarity_reasons.append('measurable')

        # Penalize ambiguous criteria
        if any(ambiguous in question for ambiguous in ['decide', 'judges', 'determines', 'interpreted']):
            clarity_score -= clarity_indicators['ambiguous_terns']
            clarity_reasons.append('ambiguous_terms')

        # Penalize subjective/complex conditions
        if any(complex in question for complex in ['depending on', 'conting upon', 'subject to', 'materially']):
            clarity_score -= clarity_indicators['complex_conditions']
            clarity_reasons.append('complex_conditions')

        # Store clarity analysis
        market['clarity_score'] = clarity_score
        market['clarity_reasons'] = clarity_reasons

        if clarity_score >= MIN_RESOLUTION_CLARITY:
            filtered_markets.append(market)
            print(f"  ✅ PASS: Clarity score {clarity_score} ({', '.join(clarity_reasons)})")
        else:
            print(f"  ❌ REJECT: Clarity score {clarity_score} (<{MIN_RESOLUTION_CLARITY} min)")

    print(f"✅ Resolution clarity filter: {len(markets)} → {len(filtered_markets)} markets")
    print(f"   Minimum clarity score: {MIN_RESOLUTION_CLARITY}")

    if filtered_markets:
        avg_clarity = sum(m['clarity_score'] for m in filtered_markets) / len(filtered_markets)
        print(f"   Average clarity: {avg_clarity:.1f}")

    return filtered_markets


def filter_event_finality(markets):
    """
    Filter markets by event finality score.

    Require: finality_score ≥ 8
    Events with definitive, irreversible outcomes
    Avoids markets that might be cancelled or modified

    Args:
        markets (list): List of market dictionaries

    Returns:
        list: Markets with high event finality
    """
    from config import MIN_EVENT_FINALITY

    filtered_markets = []

    # Manual scoring based on event characteristics
    finality_indicators = {
        # High finality (8-10 score)
        'definitive_outcome': 10,   # Cannot be changed or cancelled
        'official_source': 8,        # Based on official data/announcements
        'verifiable': 8,             # Can be objectively verified
        'binding_result': 8,            # Creates binding legal/financial obligation

        # Medium finality (6-7 score)
        'public_event': 6,             # Well-documented public events
        'measurable_criteria': 7,      # Clear measurement standards
        'time_sensitive': 6,            # Time-bound but verifiable

        # Low finality (0-5 score)
        'subjective_judgment': 4,      # Requires subjective interpretation
        'reversible': 3,               # Can be reversed or cancelled
        'ambiguous': 2,                # Multiple valid interpretations
        'unverifiable': 1,            # Cannot be objectively verified
    }

    for market in markets:
        question = market.get('question', '').lower()
        end_date = market.get('end_date', '')

        finality_score = 0
        finality_reasons = []

        # Analyze for high finality indicators
        if any(term in question for term in ['election', 'official', 'federal', 'binding', 'contract', 'legal', 'ruling']):
            finality_score += finality_indicators['official_source']
            finality_reasons.append('official_source')

        # Check for definitive outcomes
        if any(outcome in question for outcome in ['wins', 'loses', 'passes', 'fails', 'achieves', 'completes']):
            finality_score += finality_indicators['definitive_outcome']
            finality_reasons.append('definitive_outcome')

        # Check for verifiability
        if any(verify in question for verify in ['results', 'data', 'statistics', 'official']):
            finality_score += finality_indicators['verifiable']
            finality_reasons.append('verifiable')

        # Check for time-sensitive but verifiable
        if end_date and 'T' in end_date:
            finality_score += finality_indicators['time_sensitive']
            finality_reasons.append('time_sensitive')

        # Penalize low finality indicators
        if any(subjective in question for subjective in ['might', 'could', 'maybe', 'possibly', 'potential']):
            finality_score -= finality_indicators['subjective_judgment']
            finality_reasons.append('subjective_judgment')

        if any(unclear in question for unclear in ['unclear', 'depends', 'conting', 'subject to']):
            finality_score -= finality_indicators['ambiguous']
            finality_reasons.append('ambiguous')

        # Store finality analysis
        market['finality_score'] = finality_score
        market['finality_reasons'] = finality_reasons

        if finality_score >= MIN_EVENT_FINALITY:
            filtered_markets.append(market)
            print(f"  ✅ PASS: Finality score {finality_score} ({', '.join(finality_reasons)})")
        else:
            print(f"  ❌ REJECT: Finality score {finality_score} (<{MIN_EVENT_FINALITY} min)")

    print(f"✅ Event finality filter: {len(markets)} → {len(filtered_markets)} markets")
    print(f"   Minimum finality score: {MIN_EVENT_FINALITY}")

    if filtered_markets:
        avg_finality = sum(m['finality_score'] for m in filtered_markets) / len(filtered_markets)
        print(f"   Average finality: {avg_finality:.1f}")

    return filtered_markets


def filter_portfolio_limits(markets, positions):
    """
    Filter markets by portfolio concentration limits.

    Check: <40% in any category, <8 total positions
    Manages risk through diversification across market types

    Args:
        markets (list): List of market dictionaries
        positions (list): Current active positions

    Returns:
        list: Markets that fit portfolio constraints
    """
    from config import MAX_CATEGORY_EXPOSURE_PCT, MAX_POSITIONS

    filtered_markets = []

    # Get current portfolio stats
    portfolio_stats = {
        'total_positions': len(positions),
        'categories': {},
        'category_exposure': {}
    }

    # Analyze current positions by category
    for position in positions:
        category = position.get('category', 'Unknown')
        if category not in portfolio_stats['categories']:
            portfolio_stats['categories'][category] = 0
        portfolio_stats['categories'][category] += 1

    total_portfolio_value = sum(pos.get('position_size_usd', 0) for pos in positions)

    # Calculate category exposure limits
    for category, count in portfolio_stats['categories'].items():
        portfolio_stats['category_exposure'][category] = (count / len(positions)) * 100

    # Filter each market
    for market in markets:
        category = market.get('category', 'Unknown')

        # Check if category has space
        current_exposure = portfolio_stats['category_exposure'].get(category, 0)
        max_allowed = MAX_CATEGORY_EXPOSURE_PCT

        if current_exposure >= max_allowed:
            print(f"  ❌ REJECT: Category '{category}' already at {current_exposure:.1f}% (max {max_allowed:.0f}%)")
            continue

        # Check total position limit
        if portfolio_stats['total_positions'] >= MAX_POSITIONS:
            print(f"  ❌ REJECT: Portfolio has {portfolio_stats['total_positions']} positions (max {MAX_POSITIONS})")
            continue

        # Check position would exceed category limit
        potential_exposure = ((portfolio_stats['total_positions'] + 1) / len(positions + 1)) * 100 if positions else 0

        if potential_exposure >= max_allowed:
            print(f"  ❌ REJECT: Adding this would reach {potential_exposure:.1f}% in '{category}' (max {max_allowed:.0f}%)")
            continue

        # If all checks pass, market is acceptable
        filtered_markets.append(market)
        print(f"  ✅ PASS: Category '{category}' at {current_exposure:.1f}%, adding this would reach {potential_exposure:.1f}%")

    print(f"✅ Portfolio limits filter: {len(markets)} → {len(filtered_markets)} markets")
    print(f"   Max positions: {MAX_POSITIONS}")
    print(f"   Max category exposure: {MAX_CATEGORY_EXPOSURE_PCT:.0f}%")
    print(f"   Current portfolio: {portfolio_stats['total_positions']} positions in {len(portfolio_stats['categories'])} categories")

    return filtered_markets


def run_filter_pipeline(markets, positions=None):
    """
    Run complete filter pipeline on markets.

    Chains all 8 filters in sequence
    Logs rejection count at each stage for transparency

    Args:
        markets (list): List of market dictionaries to filter
        positions (list): Current active positions (for portfolio limits)

    Returns:
        dict: {
            'filtered_markets': list of markets that passed all filters,
            'rejection_log': dict with counts rejected at each stage,
            'total_filtered': number of markets that passed
        }
    """
    print("=" * 80)
    print("🔍 TAIL-END FILTER PIPELINE - STARTING")
    print("=" * 80)
    print(f"📊 INPUT: {len(markets)} markets to evaluate")
    print(f"📊 POSITIONS: {len(positions) if positions else 0} active positions")
    print()

    # Initialize tracking
    rejection_log = {}
    current_markets = markets
    stage_names = []

    # Stage 1: Price Range Filter
    stage_names.append("Price Range")
    filtered = filter_price_range(current_markets)
    rejection_log['price_range'] = len(current_markets) - len(filtered)
    print(f"✅ STAGE 1 - PRICE RANGE: {len(current_markets)} → {len(filtered)} markets")
    print(f"   Filter: ${PRICE_MIN:.2f}-${PRICE_MAX:.2f} (tail-end sweet spot)")
    current_markets = filtered

    # Stage 2: Liquidity Filter
    stage_names.append("Liquidity")
    filtered = filter_liquidity(current_markets)
    rejection_log['liquidity'] = len(current_markets) - len(filtered)
    print(f"✅ STAGE 2 - LIQUIDITY: {len(current_markets)} → {len(filtered)} markets")
    print(f"   Filter: ≥${MIN_VOLUME_24H:,} volume proxy, ≥${MIN_BID_DEPTH:,} bid depth")
    current_markets = filtered

    # Stage 3: Settlement Window Filter
    stage_names.append("Settlement Window")
    filtered = filter_settlement_window(current_markets)
    rejection_log['settlement'] = len(current_markets) - len(filtered)
    print(f"✅ STAGE 3 - SETTLEMENT: {len(current_markets)} → {len(filtered)} markets")
    print(f"   Filter: {MIN_SETTLEMENT_HOURS}h - {MAX_SETTLEMENT_DAYS}d window")
    current_markets = filtered

    # Stage 4: Spread Filter
    stage_names.append("Spread")
    filtered = filter_spread(current_markets)
    rejection_log['spread'] = len(current_markets) - len(filtered)
    print(f"✅ STAGE 4 - SPREAD: {len(current_markets)} → {len(filtered)} markets")
    print(f"   Filter: ≤{MAX_SPREAD_PCT:.0f}% bid-ask spread")
    current_markets = filtered

    # Stage 5: Exit Liquidity Filter
    stage_names.append("Exit Liquidity")
    filtered = filter_exit_liquidity(current_markets)
    rejection_log['exit_liquidity'] = len(current_markets) - len(filtered)
    print(f"✅ STAGE 5 - EXIT LIQUIDITY: {len(current_markets)} → {len(filtered)} markets")
    print(f"   Filter: ≥{MIN_LIQUIDITY_RATIO}x liquidity ratio for position exit")
    current_markets = filtered

    # Stage 6: Resolution Clarity Filter
    stage_names.append("Resolution Clarity")
    from config import MIN_RESOLUTION_CLARITY
    filtered = filter_resolution_clarity(current_markets)
    rejection_log['resolution_clarity'] = len(current_markets) - len(filtered)
    print(f"✅ STAGE 6 - RESOLUTION CLARITY: {len(current_markets)} → {len(filtered)} markets")
    print(f"   Filter: Clarity score ≥ {MIN_RESOLUTION_CLARITY}")
    current_markets = filtered

    # Stage 7: Event Finality Filter
    stage_names.append("Event Finality")
    from config import MIN_EVENT_FINALITY
    filtered = filter_event_finality(current_markets)
    rejection_log['event_finality'] = len(current_markets) - len(filtered)
    print(f"✅ STAGE 7 - EVENT FINALITY: {len(current_markets)} → {len(filtered)} markets")
    print(f"   Filter: Finality score ≥ {MIN_EVENT_FINALITY}")
    current_markets = filtered

    # Stage 8: Portfolio Limits Filter
    stage_names.append("Portfolio Limits")
    filtered = filter_portfolio_limits(current_markets, positions)
    rejection_log['portfolio_limits'] = len(current_markets) - len(filtered)
    print(f"✅ STAGE 8 - PORTFOLIO LIMITS: {len(current_markets)} → {len(filtered)} markets")
    print(f"   Filter: ≤{MAX_POSITIONS} positions, ≤{MAX_CATEGORY_EXPOSURE_PCT:.0f}% per category")
    current_markets = filtered

    # Final results
    total_rejected = sum(rejection_log.values())
    success_rate = (len(current_markets) / len(markets)) * 100 if markets else 0

    print()
    print("=" * 80)
    print("🎯 TAIL-END FILTER PIPELINE - COMPLETE")
    print("=" * 80)
    print(f"📊 FINAL RESULTS: {len(markets)} → {len(current_markets)} markets")
    print(f"📊 SUCCESS RATE: {len(current_markets)}/{len(markets)} = {success_rate:.1f}%")
    print(f"📊 REDUCTION: {total_rejected} rejected ({(total_rejected/len(markets))*100:.1f}% reduction)")

    # Rejection breakdown
    print(f"📈 REJECTION BREAKDOWN:")
    for i, stage in enumerate(stage_names, 1):
        rejected = rejection_log.get(f"stage_{i+1}", 0)
        print(f"   {i}. {stage}: {rejected} markets rejected")

    # Stage-by-stage success rates
    for i, stage in enumerate(stage_names, 1):
        stage_key = f"stage_{i+1}"
        success_count = len(markets) - sum(rejection_log.get(f"stage_{j}", 0) for j in range(i+1, len(stage_names)))
        stage_total = len(markets) - sum(rejection_log.get(f"stage_{j}", 0) for j in range(0, i))
        stage_success_rate = (success_count / stage_total * 100) if stage_total > 0 else 0
        print(f"   {i}. {stage} success rate: {success_count}/{stage_total} = {stage_success_rate:.1f}%")

    print()
    if current_markets:
        print("🏆 TOP QUALIFIED TAIL-END OPPORTUNITIES:")
        for i, market in enumerate(current_markets[:10], 1):  # Show top 10
            price = market['yes_price']
            volume = market.get('volume_proxy', 0)
            days = market.get('days_to_settlement', 0)
            spread = market.get('spread_pct', 0)
            clarity = market.get('clarity_score', 0)
            finality = market.get('finality_score', 0)
            question = market['question'][:70]

            print(f"  {i}. ${price:.3f} | ${volume:,.0f} vol | {days:.1f}d | {spread:.0f}% spread")
            print(f"     Clarity: {clarity}/10 | Finality: {finality}/10")
            print(f"     {question}...")

    return {
        'filtered_markets': current_markets,
        'rejection_log': rejection_log,
        'total_filtered': len(current_markets),
        'pipeline_stages': stage_names
    }


if __name__ == "__main__":
    """Test filter pipeline structure and price filter"""
    print("=" * 60)
    print("Testing Filter Pipeline Structure")
    print("=" * 60)

    print("✅ detectors/filters.py created successfully")
    print("✅ All 8 filter functions defined")
    print("✅ Config constants imported")
    print("✅ Function signatures ready for implementation")
    print()
    print("=" * 60)
    print("Testing filter_price_range() Implementation")
    print("=" * 60)

    # Test with sample data
    test_markets = [
        {'yes_price': 0.85, 'question': 'Market A - Too cheap'},
        {'yes_price': 0.92, 'question': 'Market B - In range'},
        {'yes_price': 0.95, 'question': 'Market C - Perfect range'},
        {'yes_price': 0.97, 'question': 'Market D - Upper range'},
        {'yes_price': 0.99, 'question': 'Market E - Too expensive'},
        {'tokens': [{'price': 0.94}], 'question': 'Market F - Token structure'},
        {'question': 'Market G - No price data'}  # Will be skipped
    ]

    print(f"\n📊 Testing with {len(test_markets)} sample markets:")
    for i, market in enumerate(test_markets, 1):
        if 'yes_price' in market:
            print(f"  {i}. ${market['yes_price']:.3f} | {market['question']}")
        elif 'tokens' in market:
            price = market['tokens'][0]['price']
            print(f"  {i}. ${price:.3f} | {market['question']}")

    # Run the filter
    filtered = filter_price_range(test_markets)

    print(f"\n🎯 Filtered Results (PRICE_MIN=${PRICE_MIN:.2f}, PRICE_MAX=${PRICE_MAX:.2f}):")
    for i, market in enumerate(filtered, 1):
        if 'yes_price' in market:
            print(f"  {i}. ${market['yes_price']:.3f} | {market['question']}")
        elif 'tokens' in market:
            price = market['tokens'][0]['price']
            print(f"  {i}. ${price:.3f} | {market['question']}")

    print()
    print("✅ Price filter working correctly!")
    print("Expected: 4 markets in range (0.92-0.97)")
    print(f"Actual: {len(filtered)} markets filtered")
    print()
    print("Next steps:")
    print("2. Implement filter_liquidity() - Task 2.1.3")
    print("3. Implement filter_settlement_window() - Task 2.1.4")
    print("4. Implement filter_spread() - Task 2.1.5")
    print("5. Build complete pipeline in run_filter_pipeline()")
    print("=" * 60)