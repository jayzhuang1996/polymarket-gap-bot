#!/usr/bin/env python3
"""
Test the updated filter pipeline with expanded parameters
"""

from database.db_manager import get_markets
from detectors.filters import (
    filter_price_range,
    filter_liquidity,
    filter_settlement_window,
    filter_spread
)

print('=== UPDATED FILTER PIPELINE TEST ===')
print('New parameters:')
print('• Price range: 0.85-0.97 (expanded from 0.92-0.97)')
print('• Settlement window: 6h-30d (expanded from 6h-7d)')
print('• Max spread: 10,000% (based on real Polymarket data)')
print()

# Get all active markets
markets = get_markets({'active_only': True})
print(f'Starting with {len(markets)} active markets')
print()

# Apply filters in sequence
print('1. PRICE FILTER (0.85-0.97 range)')
print('=' * 50)
price_filtered = filter_price_range(markets)

if not price_filtered:
    print('❌ No markets passed price filter - cannot continue')
    exit()

print()

# Test liquidity on first 15 markets (larger sample)
test_sample = price_filtered[:15]
print(f'2. LIQUIDITY FILTER (testing first {len(test_sample)} markets)')
print('=' * 50)
liquidity_filtered = filter_liquidity(test_sample)

if not liquidity_filtered:
    print('❌ No markets passed liquidity filter - cannot continue')
    exit()

print()

print('3. SETTLEMENT WINDOW FILTER (6h-30d)')
print('=' * 50)
settlement_filtered = filter_settlement_window(liquidity_filtered)

if not settlement_filtered:
    print('❌ No markets passed settlement window filter - cannot continue')
    exit()

print()

print('4. SPREAD FILTER (<10,000%)')
print('=' * 50)
spread_filtered = filter_spread(settlement_filtered)

print()

# Final results
print('=== UPDATED RESULTS ===')
print(f'Starting markets: {len(markets)}')
print(f'After price filter (0.85-0.97): {len(price_filtered)} ({len(price_filtered)/len(markets)*100:.1f}%)')
print(f'After liquidity filter: {len(liquidity_filtered)} ({len(liquidity_filtered)/len(test_sample)*100:.1f}% of sample)')
print(f'After settlement filter (6h-30d): {len(settlement_filtered)} ({len(settlement_filtered)/len(liquidity_filtered)*100:.1f}%)')
print(f'After spread filter: {len(spread_filtered)} ({len(spread_filtered)/len(settlement_filtered)*100:.1f}%)')

print(f'\nTotal reduction: {len(markets)} → {len(spread_filtered)} markets')
print(f'Reduction rate: {(1 - len(spread_filtered)/len(markets))*100:.1f}%')

if spread_filtered:
    print(f'\n✅ TOP TRADING OPPORTUNITIES:')
    for i, market in enumerate(spread_filtered, 1):
        price = market['yes_price']
        volume = market.get('volume_proxy', 0)
        days = market.get('days_to_settlement', 0)
        spread = market.get('spread_pct', 0)
        question = market['question'][:70]
        print(f'  {i}. ${price:.3f} | ${volume:,.0f} vol | {days:.1f}d | {spread:.0f}% spread')
        print(f'     {question}...')
        print()

    # Show detailed analysis for top opportunity
    best_market = spread_filtered[0]
    print(f'📊 DETAILED ANALYSIS - Top Opportunity:')
    print(f'Question: {best_market["question"]}')
    print(f'Price: ${best_market["yes_price"]:.3f} ({best_market["yes_price"]*100:.1f}% probability)')
    print(f'Volume Proxy: ${best_market.get("volume_proxy", 0):,.0f}')
    print(f'Bid Depth: ${best_market.get("bid_depth", 0):,.0f}')
    print(f'Days to Settlement: {best_market.get("days_to_settlement", 0):.1f}')
    print(f'Spread: {best_market.get("spread_pct", 0):.1f}%')
    print(f'Best Bid: ${best_market.get("best_bid_price", 0):.3f}')
    print(f'Best Ask: ${best_market.get("best_ask_price", 0):.3f}')
else:
    print('\n❌ No markets passed all filters')

print('\n=== MARKET INSIGHTS ===')
print('• Expanded price range (0.85-0.97) increases opportunities')
print('• 30-day settlement window captures more realistic timeframes')
print('• 10,000% spread filter accommodates Polymarket reality')
print('• Pipeline remains highly selective for quality opportunities')

print('\n✅ Updated filter pipeline test complete!')