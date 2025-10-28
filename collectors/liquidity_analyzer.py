"""
Liquidity analyzer for Polymarket markets
Provides volume/liquidity estimates when API doesn't return volume data
"""

import sys
from pathlib import Path
import time

# Add parent directory to path so we can import config
sys.path.insert(0, str(Path(__file__).parent.parent))

from py_clob_client.client import ClobClient
from config import POLYMARKET_HOST, POLYMARKET_CHAIN_ID

def get_market_liquidity(market, use_retry=True):
    """
    Calculate liquidity metrics for a market using order book data.

    Since API doesn't provide volume data, we analyze order books to estimate:
    - Total liquidity available
    - Bid/ask spread
    - Market depth
    - Volume proxy (total order book value)

    Args:
        market (dict): Market data with tokens[0].token_id
        use_retry (bool): Use retry logic

    Returns:
        dict: Liquidity metrics including volume proxy
    """
    def _fetch():
        client = ClobClient(POLYMARKET_HOST, POLYMARKET_CHAIN_ID)

        if 'tokens' not in market or not market['tokens']:
            return None

        token_id = market['tokens'][0]['token_id']

        try:
            order_book = client.get_order_book(token_id)

            # Handle different order book formats
            if hasattr(order_book, 'bids') and hasattr(order_book, 'asks'):
                bids = order_book.bids or []
                asks = order_book.asks or []
            elif isinstance(order_book, dict):
                bids = order_book.get('bids', [])
                asks = order_book.get('asks', [])
            else:
                return None

            # Calculate liquidity metrics
            metrics = {}

            # Total bid liquidity (people wanting to buy YES)
            if bids:
                best_bid = bids[0]
                metrics['best_bid_price'] = float(best_bid.price) if hasattr(best_bid, 'price') else float(best_bid.get('price', 0))
                metrics['best_bid_size'] = float(best_bid.size) if hasattr(best_bid, 'size') else float(best_bid.get('size', 0))
                metrics['best_bid_value'] = metrics['best_bid_price'] * metrics['best_bid_size']

                # Total bid liquidity (sum of all bids)
                metrics['total_bid_liquidity'] = sum(
                    (float(bid.price) if hasattr(bid, 'price') else float(bid.get('price', 0))) *
                    (float(bid.size) if hasattr(bid, 'size') else float(bid.get('size', 0)))
                    for bid in bids
                )
                metrics['bid_levels'] = len(bids)
            else:
                metrics['best_bid_price'] = 0
                metrics['best_bid_size'] = 0
                metrics['best_bid_value'] = 0
                metrics['total_bid_liquidity'] = 0
                metrics['bid_levels'] = 0

            # Total ask liquidity (people wanting to sell YES)
            if asks:
                best_ask = asks[0]
                metrics['best_ask_price'] = float(best_ask.price) if hasattr(best_ask, 'price') else float(best_ask.get('price', 0))
                metrics['best_ask_size'] = float(best_ask.size) if hasattr(best_ask, 'size') else float(best_ask.get('size', 0))
                metrics['best_ask_value'] = metrics['best_ask_price'] * metrics['best_ask_size']

                # Total ask liquidity (sum of all asks)
                metrics['total_ask_liquidity'] = sum(
                    (float(ask.price) if hasattr(ask, 'price') else float(ask.get('price', 0))) *
                    (float(ask.size) if hasattr(ask, 'size') else float(ask.get('size', 0)))
                    for ask in asks
                )
                metrics['ask_levels'] = len(asks)
            else:
                metrics['best_ask_price'] = 0
                metrics['best_ask_size'] = 0
                metrics['best_ask_value'] = 0
                metrics['total_ask_liquidity'] = 0
                metrics['ask_levels'] = 0

            # Calculate total liquidity and spread
            metrics['total_liquidity'] = metrics['total_bid_liquidity'] + metrics['total_ask_liquidity']

            # Volume proxy (use total liquidity as volume estimate)
            metrics['volume_proxy'] = metrics['total_liquidity']

            # Bid-ask spread (in percentage)
            if metrics['best_bid_price'] > 0 and metrics['best_ask_price'] > 0:
                metrics['spread'] = (metrics['best_ask_price'] - metrics['best_bid_price']) / metrics['best_bid_price'] * 100
            else:
                metrics['spread'] = 0

            # Market depth (total levels)
            metrics['market_depth'] = metrics['bid_levels'] + metrics['ask_levels']

            # Liquidity quality score (0-5)
            score = 0
            if metrics['total_liquidity'] >= 10000:  # $10K+ liquidity
                score += 2
            elif metrics['total_liquidity'] >= 5000:  # $5K+ liquidity
                score += 1

            if metrics['market_depth'] >= 20:  # 20+ order levels
                score += 1

            if metrics['spread'] <= 5:  # 5% or less spread
                score += 1

            if metrics['bid_levels'] >= 5 and metrics['ask_levels'] >= 5:  # Balanced market
                score += 1

            metrics['liquidity_score'] = score

            return metrics

        except Exception as e:
            print(f"Error fetching order book: {e}")
            return None

    if use_retry:
        # Simple retry for order book (quick operations)
        for attempt in range(2):
            try:
                return _fetch()
            except Exception as e:
                if attempt == 0:
                    time.sleep(0.5)
                else:
                    print(f"Failed to get liquidity after 2 attempts: {e}")
                    return None
    else:
        return _fetch()


def analyze_liquidity_for_markets(markets, max_markets=20, delay=0.1):
    """
    Analyze liquidity for multiple markets.

    Args:
        markets (list): List of market dicts
        max_markets (int): Maximum markets to analyze (API rate limiting)
        delay (float): Delay between requests to avoid rate limiting

    Returns:
        list: Markets with added liquidity metrics
    """
    markets_with_liquidity = []

    for i, market in enumerate(markets[:max_markets]):
        print(f"Analyzing liquidity for market {i+1}/{min(len(markets), max_markets)}...")

        liquidity = get_market_liquidity(market)
        if liquidity:
            market['liquidity_metrics'] = liquidity
            markets_with_liquidity.append(market)

        # Small delay to avoid rate limiting
        if delay > 0:
            time.sleep(delay)

    return markets_with_liquidity


if __name__ == "__main__":
    # Test liquidity analyzer with sample markets
    from collectors.polymarket_api import fetch_markets

    print("=" * 60)
    print("Testing Liquidity Analyzer")
    print("=" * 60)

    # Get some active markets
    markets = fetch_markets(use_sampling=True)
    active_markets = [m for m in markets if 'tokens' in m and m['tokens'] and 0.01 < float(m['tokens'][0].get('price', 0)) < 0.99]

    print(f"Found {len(active_markets)} active markets")
    print(f"Analyzing liquidity for first 5 markets...\n")

    # Test on first 5 markets
    test_markets = active_markets[:5]

    for i, market in enumerate(test_markets, 1):
        question = market.get('question', 'N/A')[:60]
        price = float(market['tokens'][0]['price'])

        print(f"{i}. {question}...")
        print(f"   Price: ${price:.3f}")

        liquidity = get_market_liquidity(market)

        if liquidity:
            print(f"   Total Liquidity: ${liquidity['total_liquidity']:,.2f}")
            print(f"   Volume Proxy: ${liquidity['volume_proxy']:,.2f}")
            print(f"   Best Bid: ${liquidity['best_bid_price']:.3f} (${liquidity['best_bid_value']:.2f})")
            print(f"   Best Ask: ${liquidity['best_ask_price']:.3f} (${liquidity['best_ask_value']:.2f})")
            print(f"   Spread: {liquidity['spread']:.1f}%")
            print(f"   Market Depth: {liquidity['market_depth']} levels")
            print(f"   Liquidity Score: {liquidity['liquidity_score']}/5")
        else:
            print("   ❌ No liquidity data available")

        print()

    print("=" * 60)
    print("✅ Liquidity analyzer test complete!")
    print("=" * 60)