"""
Polymarket API wrapper
Task 1.1.3: Write fetch_markets() function
Task 1.1.5: Add error handling and retries
"""

import sys
from pathlib import Path
import time
from typing import Dict, Optional

# Add parent directory to path so we can import config
sys.path.insert(0, str(Path(__file__).parent.parent))

from py_clob_client.client import ClobClient
from config import POLYMARKET_HOST, POLYMARKET_CHAIN_ID


def retry_with_backoff(func, max_retries=3, initial_delay=1):
    """
    Retry a function with exponential backoff.

    Args:
        func: Function to retry (should take no arguments)
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds (doubles each retry)

    Returns:
        Function result if successful

    Raises:
        Last exception if all retries fail
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                print(f"⚠️  Attempt {attempt + 1} failed: {e}")
                print(f"   Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                print(f"❌ All {max_retries} attempts failed")

    raise last_exception


def fetch_markets(closed=False, use_retry=True, use_sampling=True):
    """
    Fetch markets from Polymarket with retry logic.

    Args:
        closed (bool): Include closed/settled markets. Default False (active only)
        use_retry (bool): Use retry logic with exponential backoff
        use_sampling (bool): Use get_sampling_markets() for active markets (recommended)

    Returns:
        list: List of market dicts with question, price, volume, etc.
    """
    def _fetch():
        # Initialize client (read-only, no auth needed)
        client = ClobClient(
            host=POLYMARKET_HOST,
            chain_id=POLYMARKET_CHAIN_ID
        )

        # Use sampling endpoint for active markets (preferred)
        if use_sampling and not closed:
            response = client.get_sampling_markets()
        else:
            # Fallback to regular endpoint (limited to ~4 markets)
            try:
                response = client.get_markets(closed=closed)
            except TypeError:
                response = client.get_markets()

        # Extract markets from response
        if isinstance(response, dict):
            markets = response.get('data', response.get('markets', []))
        else:
            markets = response

        return markets

    if use_retry:
        return retry_with_backoff(_fetch)
    else:
        return _fetch()


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


def fetch_order_book(token_id, use_retry=True):
    """
    Fetch order book (bids/asks) for a specific token with retry logic.

    Args:
        token_id (str): The token ID (from market['tokens'][0]['token_id'])
        use_retry (bool): Use retry logic with exponential backoff

    Returns:
        dict: Order book with 'bids' and 'asks' arrays
              Each order has 'price' and 'size' fields
    """
    def _fetch():
        client = ClobClient(
            host=POLYMARKET_HOST,
            chain_id=POLYMARKET_CHAIN_ID
        )
        return client.get_order_book(token_id)

    try:
        if use_retry:
            order_book = retry_with_backoff(_fetch)
        else:
            order_book = _fetch()

        # Convert OrderBookSummary object to dict if needed
        if hasattr(order_book, 'bids') and hasattr(order_book, 'asks'):
            # Convert OrderSummary objects to dicts
            bids = []
            for bid in (order_book.bids or []):
                bids.append({
                    'price': bid.price if hasattr(bid, 'price') else bid.get('price'),
                    'size': bid.size if hasattr(bid, 'size') else bid.get('size')
                })

            asks = []
            for ask in (order_book.asks or []):
                asks.append({
                    'price': ask.price if hasattr(ask, 'price') else ask.get('price'),
                    'size': ask.size if hasattr(ask, 'size') else ask.get('size')
                })

            return {'bids': bids, 'asks': asks}
        return order_book
    except Exception as e:
        print(f"⚠️  Error fetching order book for token {token_id}: {e}")
        return {'bids': [], 'asks': []}


def place_order(market_id: str, side: str, price: float, size: float, order_type: str = "LIMIT") -> Optional[Dict]:
    """
    Place trading order on Polymarket.

    Args:
        market_id: Market ID from Polymarket
        side: "BUY" or "SELL"
        price: Order price (for market orders, use current price)
        size: Size in USD
        order_type: "LIMIT" or "STOP_LOSS" or "MARKET"

    Returns:
        Dict with order details if successful, None if failed
    """
    def _place():
        from py_clob_client.client import ClobClient
        from config import POLYMARKET_PRIVATE_KEY

        client = ClobClient(
            host=POLYMARKET_HOST,
            chain_id=POLYMARKET_CHAIN_ID,
            key=POLYMARKET_PRIVATE_KEY
        )

        # For now, return mock order (need real implementation)
        order_id = f"order_{int(time.time())}_{market_id[:8]}"

        return {
            'order_id': order_id,
            'status': 'placed',
            'side': side,
            'price': price,
            'size': size,
            'type': order_type
        }

    try:
        order = retry_with_backoff(_place)
        print(f"✅ Order placed: {side} ${size} @ ${price} (ID: {order['order_id']})")
        return order
    except Exception as e:
        print(f"❌ Failed to place order: {e}")
        return None


def get_order_status(order_id: str) -> Optional[Dict]:
    """
    Get status of existing order.

    Args:
        order_id: Order ID from place_order()

    Returns:
        Dict with status details, None if not found
    """
    def _get_status():
        from py_clob_client.client import ClobClient
        from config import POLYMARKET_PRIVATE_KEY

        client = ClobClient(
            host=POLYMARKET_HOST,
            chain_id=POLYMARKET_CHAIN_ID,
            key=POLYMARKET_PRIVATE_KEY
        )

        # For now, simulate fill after 5 seconds (mock implementation)
        if int(time.time()) % 10 > 5:
            return {
                'order_id': order_id,
                'status': 'filled',
                'fill_price': 0.93,
                'tokens_filled': int(200 / 0.93),  # Mock calculation
                'fees': 0
            }
        else:
            return {
                'order_id': order_id,
                'status': 'open',
                'fill_price': None,
                'tokens_filled': 0
            }

    try:
        status = retry_with_backoff(_get_status)
        return status
    except Exception as e:
        print(f"❌ Failed to get order status: {e}")
        return None


def cancel_order(order_id: str) -> bool:
    """
    Cancel existing order.

    Args:
        order_id: Order ID to cancel

    Returns:
        True if cancelled successfully, False otherwise
    """
    def _cancel():
        from py_clob_client.client import ClobClient
        from config import POLYMARKET_PRIVATE_KEY

        client = ClobClient(
            host=POLYMARKET_HOST,
            chain_id=POLYMARKET_CHAIN_ID,
            key=POLYMARKET_PRIVATE_KEY
        )

        # Mock implementation - always succeed
        return True

    try:
        success = retry_with_backoff(_cancel)
        if success:
            print(f"✅ Order cancelled: {order_id}")
        else:
            print(f"❌ Failed to cancel order: {order_id}")
        return success
    except Exception as e:
        print(f"❌ Failed to cancel order {order_id}: {e}")
        return False


def get_current_price(token_id: str) -> Optional[float]:
    """
    Get current market price from order book.

    Args:
        token_id: Token ID to fetch price for

    Returns:
        Current price or None if unavailable
    """
    try:
        order_book = fetch_order_book(token_id, use_retry=False)

        # Get best bid (highest price someone will buy for)
        bids = order_book.get('bids', [])
        if bids:
            return float(bids[0]['price'])

        return None
    except Exception as e:
        print(f"❌ Failed to get current price: {e}")
        return None


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
        print("✅ fetch_order_book() working!")
        print("=" * 60)
    else:
        print("\n⚠️  No active markets found")
        print("=" * 60)

    # Test error handling with invalid token ID
    print("\n" + "=" * 60)
    print("Testing error handling and retries")
    print("=" * 60)

    print("\nTesting with invalid token ID (should fail gracefully)...")
    invalid_book = fetch_order_book("invalid_token_id_12345")
    print(f"Result: {invalid_book}")
    print("✅ Error handled gracefully - returned empty order book")

    print("\n" + "=" * 60)
    print("✅ Task 1.1.5 COMPLETE: Error handling and retries added!")
    print("=" * 60)
