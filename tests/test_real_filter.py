#!/usr/bin/env python3
"""
Test price filter with real database data
"""

from database.db_manager import get_markets
from detectors.filters import filter_price_range

print('Testing price filter with real database data...')
print()

# Get all active markets
markets = get_markets({'active_only': True})
print(f'Total active markets: {len(markets)}')

# Apply price filter
filtered_markets = filter_price_range(markets)
print(f'\nTail-end opportunities: {len(filtered_markets)} markets')

if filtered_markets:
    print('\nSample tail-end markets:')
    for i, market in enumerate(filtered_markets[:5], 1):
        price = market['yes_price']
        question = market['question'][:60]
        print(f'  {i}. ${price:.3f} | {question}...')

print(f'\n✅ Price filter reduces {len(markets)} → {len(filtered_markets)} markets')
print(f'   Reduction: {(1 - len(filtered_markets)/len(markets))*100:.1f}%')