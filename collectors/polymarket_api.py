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


def fetch_markets(closed=False):
    """
    Fetch markets from Polymarket

    Args:
        closed (bool): Include closed/settled markets. Default False (active only)

    Returns:
        list: List of market dicts with question, price, volume, etc.
    """
    # Initialize client (read-only, no auth needed)
    client = ClobClient(
        host=POLYMARKET_HOST,
        chain_id=POLYMARKET_CHAIN_ID
    )

    # Fetch markets (try with closed parameter)
    try:
        response = client.get_markets(closed=closed)
    except TypeError:
        # If API doesn't support 'closed' param, fetch all
        response = client.get_markets()

    # Extract markets from response
    if isinstance(response, dict):
        markets = response.get('data', response.get('markets', []))
    else:
        markets = response

    return markets


def filter_active_markets(markets, min_volume=None):
    """
    Filter for active markets (not settled).

    Args:
        markets (list): List of market dicts from fetch_markets()
        min_volume (float): Minimum 24h volume in USD (optional, often 0 in API)

    Returns:
        list: Markets that are actively trading (price between 0.01-0.99)
    """
    active = []
    for market in markets:
        if 'tokens' not in market or len(market['tokens']) == 0:
            continue

        price = float(market['tokens'][0].get('price', 0))

        # Active if: price not settled (0.01-0.99)
        if 0.01 < price < 0.99:
            # If volume filter requested, apply it
            if min_volume is not None:
                volume = float(market.get('volume', 0))
                if volume < min_volume:
                    continue
            active.append(market)

    return active


def fetch_order_book(token_id):
    """
    Fetch order book (bids/asks) for a specific token.

    Args:
        token_id (str): The token ID (from market['tokens'][0]['token_id'])

    Returns:
        dict: Order book with 'bids' and 'asks' arrays
              Each order has 'price' and 'size' fields
    """
    client = ClobClient(
        host=POLYMARKET_HOST,
        chain_id=POLYMARKET_CHAIN_ID
    )

    try:
        order_book = client.get_order_book(token_id)
        return order_book
    except Exception as e:
        print(f"⚠️  Error fetching order book for token {token_id}: {e}")
        return {'bids': [], 'asks': []}


if __name__ == "__main__":
    """Test fetch_markets() function"""

    print("=" * 60)
    print("Testing fetch_markets()")
    print("=" * 60)

    # Test both endpoints
    markets_default = fetch_markets()
    print(f"\n✅ fetch_markets() returned {len(markets_default)} markets")

    # Try sampling endpoint
    from py_clob_client.client import ClobClient
    client = ClobClient(POLYMARKET_HOST, POLYMARKET_CHAIN_ID)
    response = client.get_sampling_markets()
    if isinstance(response, dict):
        markets = response.get('data', response.get('markets', []))
    else:
        markets = response

    print(f"✅ get_sampling_markets() returned {len(markets)} markets")

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
    print("✅ fetch_markets() working!")
    print("=" * 60)

    # Test filter_active_markets()
    print("\n" + "=" * 60)
    print("Testing filter_active_markets()")
    print("=" * 60)

    # Filter by price only (volume data seems unreliable in API)
    active_markets = filter_active_markets(markets)
    print(f"\n✅ Found {len(active_markets)} active markets (out of {len(markets)} total)")

    if active_markets:
        print(f"\n📊 Sample active markets:")
        for i, market in enumerate(active_markets[:3], 1):
            yes_token = market['tokens'][0]
            print(f"\n{i}. {market.get('question', 'N/A')}")
            print(f"   YES Price: ${yes_token.get('price')}")
            print(f"   24h Volume: ${float(market.get('volume', 0)):,.0f}")

    # Test fetch_order_book() with first active market
    print("\n" + "=" * 60)
    print("Testing fetch_order_book()")
    print("=" * 60)

    test_market = active_markets[0] if active_markets else None

    if test_market:
        yes_token = test_market['tokens'][0]
        token_id = yes_token.get('token_id')

        print(f"\nFetching order book for: {test_market.get('question', 'N/A')}")
        print(f"YES Price: ${yes_token.get('price')}")
        print(f"24h Volume: ${float(test_market.get('volume', 0)):,.0f}")
        print(f"Token ID: {token_id}\n")

        order_book = fetch_order_book(token_id)

        # Display top 3 bids and asks
        print("📗 Top 3 BIDS (people buying YES):")
        for i, bid in enumerate(order_book.get('bids', [])[:3], 1):
            price = bid.get('price', 'N/A')
            size = bid.get('size', 'N/A')
            print(f"  {i}. Price: ${price} | Size: {size} shares")

        print("\n📕 Top 3 ASKS (people selling YES):")
        for i, ask in enumerate(order_book.get('asks', [])[:3], 1):
            price = ask.get('price', 'N/A')
            size = ask.get('size', 'N/A')
            print(f"  {i}. Price: ${price} | Size: {size} shares")

        print("\n" + "=" * 60)
        print("✅ COMPLETE: All functions working with live active markets!")
        print("=" * 60)
    else:
        print("\n⚠️  No active markets found")
        print("=" * 60)
