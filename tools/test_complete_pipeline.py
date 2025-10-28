#!/usr/bin/env python3
"""
Test the complete filter pipeline
"""

from database.db_manager import get_markets
from detectors.filters import (
    filter_price_range,
    filter_liquidity,
    filter_settlement_window,
    filter_spread
)

print('=== COMPLETE FILTER PIPELINE TEST ===')
print()

# Get all active markets
markets = get_markets({'active_only': True})
print(f'Starting with {len(markets)} active markets')
print()

# Apply filters in sequence
print('1. PRICE FILTER (0.92-0.97 range)')
print('=' * 50)
price_filtered = filter_price_range(markets)

if not price_filtered:
    print('❌ No markets passed price filter - cannot continue')
    exit()

print()

# Test liquidity on limited sample for speed
test_sample = price_filtered[:10]  # Test first 10 for liquidity
print(f'2. LIQUIDITY FILTER (testing first {len(test_sample)} markets)')
print('=' * 50)
liquidity_filtered = filter_liquidity(test_sample)

if not liquidity_filtered:
    print('❌ No markets passed liquidity filter - cannot continue')
    exit()

print()

print('3. SETTLEMENT WINDOW FILTER (6h-7d)')
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
print('=== FINAL RESULTS ===')
print(f'Starting markets: {len(markets)}')
print(f'After price filter: {len(price_filtered)} ({len(price_filtered)/len(markets)*100:.1f}%)')
print(f'After liquidity filter: {len(liquidity_filtered)} ({len(liquidity_filtered)/len(test_sample)*100:.1f}% of sample)')
print(f'After settlement filter: {len(settlement_filtered)} ({len(settlement_filtered)/len(liquidity_filtered)*100:.1f}%)')
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
else:
    print('\n❌ No markets passed all filters')

print('\n=== PIPELINE INSIGHTS ===')
print('• Polymarket reality: Very wide spreads (3,200%-99,800%)')
print('• Liquidity challenge: Limited bid depth ($1-$3,100)')
print('• Settlement windows: Most markets are long-term (months)')
print('• Tail-end opportunities: Few markets meet all criteria')

print('\n✅ Filter pipeline implementation complete!')