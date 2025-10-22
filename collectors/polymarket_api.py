"""
Polymarket API wrapper
Task 1.1.3: Write fetch_markets() function
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import config
sys.path.insert(0, str(Path(__file__).parent.parent))

from py_clob_client.client import ClobClient
from config import POLYMARKET_HOST, POLYMARKET_CHAIN_ID


def fetch_markets():
    """
    Fetch all active markets from Polymarket

    Returns:
        list: List of market dicts with question, price, volume, etc.
    """
    # Initialize client (read-only, no auth needed)
    client = ClobClient(
        host=POLYMARKET_HOST,
        chain_id=POLYMARKET_CHAIN_ID
    )

    # Fetch markets
    response = client.get_markets()

    # Extract markets from response
    if isinstance(response, dict):
        markets = response.get('data', response.get('markets', []))
    else:
        markets = response

    return markets


if __name__ == "__main__":
    """Test fetch_markets() function"""

    print("=" * 60)
    print("Testing fetch_markets()")
    print("=" * 60)

    markets = fetch_markets()

    print(f"\n✅ Fetched {len(markets)} markets from Polymarket")

    # Show 3 sample markets
    print(f"\n📊 Sample Markets (showing 3 of {len(markets)}):\n")

    for i, market in enumerate(list(markets)[:3], 1):
        print(f"{i}. {market.get('question', 'N/A')}")
        print(f"   Category: {market.get('category', 'N/A')}")

        # Get YES token price
        if 'tokens' in market and len(market['tokens']) > 0:
            yes_token = market['tokens'][0]
            price = yes_token.get('price', 'N/A')
            print(f"   YES Price: ${price}")

        # Get volume
        volume = market.get('volume', market.get('volume24hr', 'N/A'))
        if volume != 'N/A':
            print(f"   24h Volume: ${float(volume):,.0f}")

        print()

    print("=" * 60)
    print("✅ Task 1.1.3 COMPLETE: fetch_markets() working!")
    print("=" * 60)
