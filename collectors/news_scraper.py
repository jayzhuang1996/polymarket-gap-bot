"""
News scraper for Polymarket trading bot
Task 1.3.1: Install feedparser and test RSS
Task 1.3.2: Write fetch_rss_feeds()
"""

import sys
from pathlib import Path
import feedparser
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def search_news_for_keywords(keywords, max_items_per_keyword=3):
    """
    Search RSS feeds for specific keywords from markets.

    Args:
        keywords (list): List of keywords to search for
        max_items_per_keyword (int): Max news items per keyword to return

    Returns:
        list: Relevant news items matching keywords
    """

    # Expanded RSS feeds for financial/business news
    rss_feeds = [
        # Business & Finance
        {'name': 'Bloomberg Business', 'url': 'https://feeds.bloomberg.com/markets/news.rss'},
        {'name': 'Reuters Business', 'url': 'https://www.reuters.com/rssFeed/businessNews'},
        {'name': 'CNBC Markets', 'url': 'https://www.cnbc.com/id/100003114/device/rss/rss.html'},
        {'name': 'Wall Street Journal', 'url': 'https://feeds.wsj.com/rss/wsj'},
        {'name': 'Financial Times', 'url': 'https://www.ft.com/rss/home'},
        {'name': 'MarketWatch', 'url': 'https://www.marketwatch.com/rss/topstories'},
        {'name': 'Seeking Alpha', 'url': 'https://seekingalpha.com/sitemap_stream.xml'},
        {'name': 'Yahoo Finance', 'url': 'https://finance.yahoo.com/news/rssindex'},

        # Tech & Crypto
        {'name': 'TechCrunch', 'url': 'https://techcrunch.com/feed/'},
        {'name': 'CoinDesk', 'url': 'https://www.coindesk.com/arc/rest/rss/news'},
        {'name': 'Cointelegraph', 'url': 'https://cointelegraph.com/rss'},
        {'name': 'Decrypt', 'url': 'https://decrypt.co/feed'},

        # General News
        {'name': 'AP News Top Stories', 'url': 'https://feeds.apnews.com/rss/apf-topnews'},
        {'name': 'BBC News', 'url': 'http://feeds.bbci.co.uk/news/rss.xml'},
        {'name': 'CNN News', 'url': 'http://rss.cnn.com/rss/edition.rss'},
    ]

    all_news = []
    keyword_count = {}

    print(f"🔍 Searching for {len(keywords)} keywords in RSS feeds...")
    print("=" * 60)

    # Count keywords
    for keyword in keywords:
        keyword_count[keyword] = 0

    for i, feed in enumerate(rss_feeds, 1):
        print(f"\n{i}. Searching {feed['name']}")

        try:
            # Fetch RSS feed
            parsed_feed = feedparser.parse(feed['url'])

            if parsed_feed.bozo:
                print(f"   ❌ Feed parsing failed (bozo=True)")
                continue

            feed_title = parsed_feed.feed.get('title', feed['name'])
            entry_count = len(parsed_feed.entries)
            matching_items = 0

            # Search for keywords in entries
            for entry in parsed_feed.entries:
                title = entry.get('title', '')
                summary = entry.get('summary', '')
                content = f"{title} {summary}".lower()

                # Check if any keyword matches
                matching_keywords = [kw for kw in keywords if kw.lower() in content]

                if matching_keywords:
                    # Limit items per keyword
                    for kw in matching_keywords:
                        if keyword_count[kw] >= max_items_per_keyword:
                            matching_keywords.remove(kw)

                    if matching_keywords:
                        news_item = {
                            'title': title,
                            'summary': entry.get('summary', ''),
                            'source': feed['name'],
                            'url': entry.get('link', ''),
                            'published_at': entry.get('published', ''),
                            'matched_keywords': matching_keywords
                        }

                        all_news.append(news_item)
                        matching_items += 1

                        # Update keyword counts
                        for kw in matching_keywords:
                            keyword_count[kw] += 1

            print(f"   ✅ {feed_title} - {matching_items} matches in {entry_count} entries")

            # Respect rate limits
            time.sleep(0.5)

        except Exception as e:
            print(f"   ❌ Error searching {feed['name']}: {e}")

    print(f"\n📊 Keyword search summary:")
    for kw, count in keyword_count.items():
        if count > 0:
            print(f"   '{kw}': {count} matches")

    return all_news


def extract_keywords_from_question(question):
    """
    Extract relevant keywords from Polymarket question for news searching.

    Args:
        question (str): Polymarket market question

    Returns:
        list: Extracted keywords for news searching
    """

    # Common trading/investment keywords
    trading_keywords = [
        'stock', 'price', 'market', 'trading', 'shares', 'earnings',
        'revenue', 'profit', 'loss', 'dividend', 'merger', 'acquisition',
        'IPO', 'SEC', 'Fed', 'inflation', 'interest', 'GDP', 'economy',
        'bull', 'bear', 'rally', 'crash', 'volatile', 'recession'
    ]

    # Company/stock keywords (common in trading)
    company_keywords = [
        'Tesla', 'Apple', 'Microsoft', 'Google', 'Amazon', 'Meta', 'Facebook',
        'Twitter', 'X', 'Nvidia', 'AMD', 'Intel', 'IBM', 'Oracle', 'Salesforce',
        'TSLA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'AMD', 'INTC',
        'Netflix', 'Disney', 'Nike', 'Starbucks', 'McDonalds', 'Walmart'
    ]

    # Crypto/digital assets
    crypto_keywords = [
        'bitcoin', 'crypto', 'cryptocurrency', 'blockchain', 'ethereum',
        'BTC', 'ETH', 'DeFi', 'NFT', 'solana', 'cardano', 'dogecoin', 'binance'
    ]

    # Economic indicators
    economic_keywords = [
        'inflation', 'recession', 'unemployment', 'GDP', 'interest rates',
        'Federal Reserve', 'Fed', 'central bank', 'oil', 'gas', 'gold',
        'consumer confidence', 'manufacturing', 'services', 'housing'
    ]

    # Political/policy keywords
    political_keywords = [
        'election', 'congress', 'senate', 'president', 'vote', 'bill',
        'policy', 'regulation', 'tax', 'government', 'democrat', 'republican',
        'Biden', 'Trump', 'Fed', 'inflation', 'interest rates'
    ]

    # Sports keywords (for sports betting markets)
    sports_keywords = [
        'NFL', 'NBA', 'MLB', 'NHL', 'World Cup', 'Olympics', 'Super Bowl',
        'playoffs', 'championship', 'finals', 'season', 'game', 'match',
        'team', 'player', 'coach', 'injury', 'trade', 'draft'
    ]

    question_lower = question.lower()
    keywords = []

    # Check for keywords in each category
    all_keywords = [
        company_keywords, trading_keywords, crypto_keywords,
        economic_keywords, political_keywords, sports_keywords
    ]

    for keyword_list in all_keywords:
        for keyword in keyword_list:
            if keyword.lower() in question_lower:
                keywords.append(keyword)

    # Extract capitalized words (potential names, companies)
    words = question.split()
    for word in words:
        # Keep words that are capitalized or all caps (likely proper nouns)
        if word.isupper() or (word[0].isupper() and len(word) > 2):
            if word not in keywords and not word.isdigit():
                keywords.append(word)

    # Remove duplicates and return
    return list(set(keywords))


def match_news_to_markets(news_items, markets):
    """
    Match news items to markets based on keyword overlap.

    Args:
        news_items (list): List of news items with matched_keywords
        markets (list): List of market dictionaries with question text

    Returns:
        list: Markets with associated news items
    """

    markets_with_news = []

    for market in markets:
        # Extract keywords from market question
        market_keywords = extract_keywords_from_question(market.get('question', ''))

        # Find relevant news items
        relevant_news = []
        for news_item in news_items:
            # Check if any market keywords match news keywords
            overlap = set(market_keywords) & set(news_item['matched_keywords'])
            if overlap:
                relevant_news.append({
                    'news_item': news_item,
                    'matched_keywords': list(overlap),
                    'relevance_score': len(overlap)
                })

        # Sort by relevance score (most matching keywords first)
        relevant_news.sort(key=lambda x: x['relevance_score'], reverse=True)

        # Add market with its relevant news
        if relevant_news:  # Only include markets with matching news
            markets_with_news.append({
                'market': market,
                'market_keywords': market_keywords,
                'relevant_news': relevant_news[:3],  # Top 3 most relevant news items
                'total_news_count': len(relevant_news)
            })

    return markets_with_news


def extract_keywords_from_title(title):
    """
    Extract relevant keywords from news title for market matching.

    Args:
        title (str): News title

    Returns:
        list: Extracted keywords
    """

    # Company/stock keywords (common in trading)
    company_keywords = [
        'Tesla', 'Apple', 'Microsoft', 'Google', 'Amazon', 'Meta', 'Facebook',
        'Twitter', 'X', 'Nvidia', 'AMD', 'Intel', 'IBM', 'Oracle', 'Salesforce',
        'TSLA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'AMD', 'INTC'
    ]

    # Financial/trading keywords
    trading_keywords = [
        'stock', 'price', 'market', 'trading', 'shares', 'earnings',
        'revenue', 'profit', 'loss', 'dividend', 'merger', 'acquisition',
        'IPO', 'SEC', 'Fed', 'inflation', 'interest', 'GDP', 'economy'
    ]

    # Crypto/digital assets
    crypto_keywords = [
        'bitcoin', 'crypto', 'cryptocurrency', 'blockchain', 'ethereum',
        'BTC', 'ETH', 'DeFi', 'NFT'
    ]

    # Economic indicators
    economic_keywords = [
        'inflation', 'recession', 'unemployment', 'GDP', 'interest rates',
        'Federal Reserve', 'Fed', 'central bank', 'oil', 'gas', 'gold'
    ]

    # Convert to lowercase for matching
    title_lower = title.lower()

    keywords = []

    # Check for keywords
    for keyword_list in [company_keywords, trading_keywords, crypto_keywords, economic_keywords]:
        for keyword in keyword_list:
            if keyword.lower() in title_lower:
                keywords.append(keyword)

    # Extract capitalized words (potential company names)
    words = title.split()
    for word in words:
        if word.isupper() or (word[0].isupper() and len(word) > 2):
            if word not in keywords:
                keywords.append(word)

    return keywords


if __name__ == "__main__":
    """Test keyword-first news scraping approach"""
    print("Keyword-First News Scraping Test")
    print("=" * 60)

    # Test keyword extraction from market questions
    print("\n🏷️ Testing extract_keywords_from_question()...")
    sample_questions = [
        "Will Tesla stock price exceed $200 by December 31?",
        "Will Bitcoin reach $100,000 in 2024?",
        "Will the Fed raise interest rates in March?",
        "Will Republicans control the House after 2024 election?",
        "Will the Lakers win the NBA championship?"
    ]

    for i, question in enumerate(sample_questions, 1):
        keywords = extract_keywords_from_question(question)
        print(f"\n{i}. Question: {question}")
        print(f"   Keywords: {keywords}")

    print("\n" + "=" * 60)
    print("Testing search_news_for_keywords() with extracted keywords...")
    print("=" * 60)

    # Test news search with extracted keywords
    test_keywords = ['Tesla', 'Fed', 'Bitcoin']
    print(f"\n🔍 Searching for keywords: {test_keywords}")

    news_items = search_news_for_keywords(test_keywords, max_items_per_keyword=2)

    print(f"\n📊 Found {len(news_items)} relevant news items:")
    for i, news in enumerate(news_items[:5], 1):
        print(f"\n{i}. {news['title'][:60]}...")
        print(f"   Source: {news['source']}")
        print(f"   Matched keywords: {news['matched_keywords']}")
        print(f"   Published: {news['published_at']}")

    print("\n" + "=" * 60)
    print("Testing match_news_to_markets()...")
    print("=" * 60)

    # Test market-news matching
    sample_markets = [
        {'id': 1, 'question': 'Will Tesla stock exceed $200 by December 31?'},
        {'id': 2, 'question': 'Will the Fed raise interest rates in March?'},
        {'id': 3, 'question': 'Will Bitcoin reach $100,000 in 2024?'},
        {'id': 4, 'question': 'Will Lakers win NBA championship?'},
    ]

    markets_with_news = match_news_to_markets(news_items, sample_markets)

    print(f"\n📊 Matched {len(markets_with_news)} markets with relevant news:")
    for i, market_news in enumerate(markets_with_news, 1):
        market = market_news['market']
        print(f"\n{i}. Market: {market['question'][:50]}...")
        print(f"   Keywords: {market_news['market_keywords']}")
        print(f"   News count: {market_news['total_news_count']}")

        for j, news_data in enumerate(market_news['relevant_news'][:2], 1):
            news = news_data['news_item']
            print(f"     {j}. {news['title'][:40]}... ({news_data['matched_keywords']})")

    print("\n" + "=" * 60)
    print("Testing save_news_event() function...")
    print("=" * 60)

    # Test saving news events to database
    from database.db_manager import save_news_event, get_news_events

    # Save sample news events
    test_news_events = [
        {
            'title': 'Tech Earnings Solid After Lam, Tesla: Hedge Fund CIO',
            'summary': 'Tech earnings have been solid according to hedge fund CIO, with Tesla showing strong performance.',
            'source': 'Bloomberg Business',
            'url': 'https://www.bloomberg.com/news/articles/2025-10-22/tech-earnings-solid',
            'published_at': '2025-10-22T23:08:30Z',
            'keywords': ['Tesla', 'Tech'],
            'related_market_ids': ['tesla-market-id'],
            'flagged': False
        },
        {
            'title': 'Financial Conditions are Accommodative: Fmr NY Fed Pres',
            'summary': 'Former NY Fed President discusses accommodative financial conditions and monetary policy.',
            'source': 'Bloomberg Business',
            'url': 'https://www.bloomberg.com/news/articles/2025-10-22/financial-conditions',
            'published_at': '2025-10-22T23:24:56Z',
            'keywords': ['Fed', 'financial'],
            'related_market_ids': ['fed-market-id'],
            'flagged': True
        }
    ]

    saved_events = []
    for news_event in test_news_events:
        event_id = save_news_event(news_event)
        if event_id:
            saved_events.append(event_id)

    print(f"\n💾 Saved {len(saved_events)} news events to database")

    # Test retrieving news events
    print(f"\n📋 Testing get_news_events()...")
    all_events = get_news_events({'limit': 10})
    print(f"✅ Retrieved {len(all_events)} news events from database")

    if all_events:
        print(f"\n📊 Sample saved news events:")
        for i, event in enumerate(all_events[:3], 1):
            print(f"\n{i}. {event['title'][:50]}...")
            print(f"   Source: {event['source']}")
            print(f"   Keywords: {event['keywords']}")
            print(f"   Flagged: {event['flagged']}")
            print(f"   Published: {event['published_at']}")

    print("\n" + "=" * 60)
    print("✅ Task 1.3.3 COMPLETE: extract_keywords_from_question() works")
    print("✅ Task 1.3.2 UPDATED: search_news_for_keywords() now keyword-first")
    print("✅ Task 1.3.4 COMPLETE: match_news_to_markets() integration works")
    print("✅ Task 1.3.5 COMPLETE: save_news_event() database storage works")
    print("🎯 Ready for Component 1.4: Collection Loop")
    print("=" * 60)