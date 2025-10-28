"""
Collection loop for Polymarket trading bot
Task 1.4.1: Write collect_and_store_markets()
Task 1.4.2: Write collect_and_store_news()
Task 1.4.3: Set up APScheduler
"""

import sys
from pathlib import Path
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.polymarket_api import fetch_markets, filter_active_markets
from database.db_manager import save_market, save_news_event, get_markets
from collectors.news_scraper import (
    extract_keywords_from_question,
    search_news_for_keywords,
    match_news_to_markets
)


def collect_and_store_markets():
    """
    Fetch markets from Polymarket API and store in database.

    This function:
    1. Fetches all active markets from Polymarket
    2. Saves each market to database (UPSERT)
    3. Logs summary of results

    Returns:
        dict: Summary of collection results
    """

    print("🔄 Starting market collection...")
    start_time = time.time()

    try:
        # Fetch markets from API
        print("📡 Fetching markets from Polymarket API...")
        all_markets = fetch_markets()

        if not all_markets:
            print("❌ No markets fetched from API")
            return {
                'success': False,
                'fetched': 0,
                'saved': 0,
                'updated': 0,
                'error': 'No markets from API'
            }

        print(f"✅ Fetched {len(all_markets)} total markets from API")

        # Filter for active markets (price 0.01-0.99)
        print("🔍 Filtering for active markets...")
        markets = filter_active_markets(all_markets)

        if not markets:
            print("⚠️ No active markets found (all settled)")
            return {
                'success': True,
                'fetched': len(all_markets),
                'saved': 0,
                'updated': 0,
                'active_markets': 0,
                'note': 'All markets are settled'
            }

        print(f"✅ Found {len(markets)} active markets (not settled)")

        # Save markets to database
        saved_count = 0
        error_count = 0

        print("💾 Saving markets to database...")

        for i, market in enumerate(markets, 1):
            try:
                success = save_market(market)
                if success:
                    saved_count += 1
                else:
                    error_count += 1

                # Progress indicator every 100 markets
                if i % 100 == 0:
                    print(f"   Processed {i}/{len(markets)} markets...")

            except Exception as e:
                print(f"❌ Error processing market {i}: {e}")
                error_count += 1

        # Calculate statistics
        elapsed_time = time.time() - start_time
        total_in_db = len(get_markets())

        results = {
            'success': True,
            'fetched': len(all_markets),
            'active_found': len(markets),
            'saved': saved_count,
            'updated': saved_count - (len(markets) - error_count),  # Estimate updates
            'errors': error_count,
            'total_in_db': total_in_db,
            'elapsed_time': round(elapsed_time, 2)
        }

        # Log summary
        print(f"\n📊 Market Collection Summary:")
        print(f"   Fetched: {results['fetched']} markets")
        print(f"   Active: {results['active_found']} markets")
        print(f"   Saved: {results['saved']} markets")
        print(f"   Errors: {results['errors']} markets")
        print(f"   Total in DB: {results['total_in_db']} markets")
        print(f"   Time: {results['elapsed_time']} seconds")
        print(f"   Rate: {results['saved']/results['elapsed_time']:.1f} markets/sec")

        return results

    except Exception as e:
        print(f"❌ Critical error in market collection: {e}")
        return {
            'success': False,
            'fetched': 0,
            'saved': 0,
            'updated': 0,
            'error': str(e)
        }


def collect_and_store_news():
    """
    Collect news and match to existing markets in database.

    This function:
    1. Gets all active markets from database
    2. Extracts keywords from market questions
    3. Searches RSS feeds for those keywords
    4. Matches news to markets based on keyword overlap
    5. Saves relevant news events to database

    Returns:
        dict: Summary of collection results
    """

    print("🔄 Starting news collection...")
    start_time = time.time()

    try:
        # Get active markets from database
        print("📋 Fetching active markets from database...")
        active_markets = get_markets({'active_only': True})

        if not active_markets:
            print("❌ No active markets found in database")
            return {
                'success': False,
                'markets': 0,
                'news_found': 0,
                'news_saved': 0,
                'error': 'No active markets in DB'
            }

        print(f"✅ Found {len(active_markets)} active markets")

        # Extract keywords from all market questions
        print("🏷️ Extracting keywords from market questions...")
        all_keywords = set()
        market_keywords = {}

        for market in active_markets:
            keywords = extract_keywords_from_question(market['question'])
            market_keywords[market['market_id']] = keywords
            all_keywords.update(keywords)

        print(f"✅ Extracted {len(all_keywords)} unique keywords")

        if not all_keywords:
            print("⚠️ No keywords extracted from markets")
            return {
                'success': True,
                'markets': len(active_markets),
                'news_found': 0,
                'news_saved': 0,
                'error': 'No keywords extracted'
            }

        # Search news for extracted keywords
        print("🔍 Searching news for keywords...")
        news_items = search_news_for_keywords(list(all_keywords), max_items_per_keyword=3)

        print(f"✅ Found {len(news_items)} relevant news items")

        if not news_items:
            print("⚠️ No news items found for keywords")
            return {
                'success': True,
                'markets': len(active_markets),
                'news_found': 0,
                'news_saved': 0,
                'keywords': len(all_keywords)
            }

        # Match news to markets
        print("🔗 Matching news to markets...")
        markets_with_news = match_news_to_markets(news_items, active_markets)

        print(f"✅ Matched news to {len(markets_with_news)} markets")

        # Save news events to database
        saved_news_count = 0
        error_count = 0

        print("💾 Saving news events to database...")

        for market_news in markets_with_news:
            market = market_news['market']
            market_id = market['market_id']

            for news_data in market_news['relevant_news']:
                try:
                    news_item = news_data['news_item']

                    # Prepare news event data
                    news_event = {
                        'title': news_item['title'],
                        'summary': news_item['summary'],
                        'source': news_item['source'],
                        'url': news_item['url'],
                        'published_at': news_item['published_at'],
                        'keywords': news_data['matched_keywords'],
                        'related_market_ids': [market_id],
                        'flagged': len(news_data['matched_keywords']) >= 2  # Flag if multiple keywords match
                    }

                    # Save to database
                    event_id = save_news_event(news_event)
                    if event_id:
                        saved_news_count += 1
                    else:
                        error_count += 1

                except Exception as e:
                    print(f"❌ Error saving news event: {e}")
                    error_count += 1

        # Calculate statistics
        elapsed_time = time.time() - start_time

        results = {
            'success': True,
            'markets': len(active_markets),
            'keywords': len(all_keywords),
            'news_found': len(news_items),
            'markets_with_news': len(markets_with_news),
            'news_saved': saved_news_count,
            'errors': error_count,
            'elapsed_time': round(elapsed_time, 2)
        }

        # Log summary
        print(f"\n📊 News Collection Summary:")
        print(f"   Active markets: {results['markets']}")
        print(f"   Keywords extracted: {results['keywords']}")
        print(f"   News items found: {results['news_found']}")
        print(f"   Markets with news: {results['markets_with_news']}")
        print(f"   News events saved: {results['news_saved']}")
        print(f"   Errors: {results['errors']}")
        print(f"   Time: {results['elapsed_time']} seconds")

        return results

    except Exception as e:
        print(f"❌ Critical error in news collection: {e}")
        return {
            'success': False,
            'markets': 0,
            'news_found': 0,
            'news_saved': 0,
            'error': str(e)
        }


if __name__ == "__main__":
    """Test collection loop functions"""
    print("=" * 60)
    print("Testing Collection Loop Functions")
    print("=" * 60)

    # Test market collection
    print("\n" + "=" * 60)
    print("Testing collect_and_store_markets()")
    print("=" * 60)

    market_results = collect_and_store_markets()

    if market_results['success']:
        print(f"✅ Market collection successful!")

        # Test news collection
        print("\n" + "=" * 60)
        print("Testing collect_and_store_news()")
        print("=" * 60)

        news_results = collect_and_store_news()

        if news_results['success']:
            print(f"✅ News collection successful!")
            print("\n" + "=" * 60)
            print("✅ Tasks 1.4.1 & 1.4.2 COMPLETE: Collection loop working!")
            print("🎯 Ready for Task 1.4.3: Set up APScheduler")
            print("=" * 60)
        else:
            print(f"❌ News collection failed: {news_results.get('error', 'Unknown error')}")
    else:
        print(f"❌ Market collection failed: {market_results.get('error', 'Unknown error')}")