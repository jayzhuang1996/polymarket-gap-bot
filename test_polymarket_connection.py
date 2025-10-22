"""
Test Polymarket API connection
Task 1.1.1: Install py-clob-client and test connection
"""

from py_clob_client.client import ClobClient

def test_connection():
    """Test basic connection to Polymarket API"""

    print("Testing Polymarket API connection...")

    # Initialize client (read-only, no auth needed for public data)
    client = ClobClient(
        host="https://clob.polymarket.com",
        chain_id=137  # Polygon mainnet
    )

    # Test: Fetch a few markets
    print("\nFetching sample markets...")

    # This is a read-only operation, no private key needed
    # We're just testing the API is accessible
    response = client.get_markets()

    if response:
        print(f"✅ Success! API is accessible")

        # Response is a dict, extract markets
        if isinstance(response, dict):
            markets = response.get('data', response.get('markets', []))
            if not markets and 'limit' in response:
                # Response is paginated metadata
                print(f"✅ API returned {response.get('count', 'N/A')} markets")
                print("   (Use get_markets() with pagination for full list)")
                return True
        else:
            markets = response

        if markets and len(markets) > 0:
            print(f"✅ Found {len(markets)} markets")

            # Show 3 sample markets
            print("\n📊 Sample Markets:")
            for i, market in enumerate(list(markets)[:3], 1):
                print(f"\n{i}. {market.get('question', 'N/A')}")
                print(f"   Category: {market.get('category', 'N/A')}")
                if 'tokens' in market and len(market['tokens']) > 0:
                    yes_token = market['tokens'][0]
                    print(f"   Price: ${yes_token.get('price', 'N/A')}")
        else:
            print(f"✅ API connected (response: {type(response).__name__})")

        return True
    else:
        print("❌ Failed to fetch markets")
        return False

if __name__ == "__main__":
    success = test_connection()

    if success:
        print("\n" + "="*50)
        print("✅ Task 1.1.1 COMPLETE")
        print("="*50)
        print("\npy-clob-client installed and working!")
        print("API connection verified!")
        print("\nReady for Task 1.1.2: Create config.py")
    else:
        print("\n❌ Connection test failed. Check your internet connection.")
