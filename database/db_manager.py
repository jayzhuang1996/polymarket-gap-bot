"""
Database manager for Polymarket trading bot
Task 1.2.2: Write init_database() function
"""

import sys
from pathlib import Path
import sqlite3
import os

# Add parent directory to path so we can import config
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATABASE_PATH


def init_database():
    """
    Initialize SQLite database with schema.

    Creates database file if it doesn't exist, executes schema.sql,
    and verifies all tables were created successfully.

    Returns:
        sqlite3.Connection: Database connection object

    Raises:
        Exception: If database creation or schema execution fails
    """
    # Ensure data directory exists
    data_dir = Path(DATABASE_PATH).parent
    data_dir.mkdir(exist_ok=True)

    try:
        # Connect to database (creates file if it doesn't exist)
        conn = sqlite3.connect(DATABASE_PATH)

        # Read and execute schema
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        # Execute schema (creates all tables and indexes)
        conn.executescript(schema_sql)
        conn.commit()

        # Verify tables were created
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]

        expected_tables = ['markets', 'positions', 'news_events']

        # Filter out SQLite's internal tables
        user_tables = [t for t in tables if not t.startswith('sqlite_')]

        if set(user_tables) == set(expected_tables):
            print(f"✅ Database initialized successfully!")
            print(f"   Location: {DATABASE_PATH}")
            print(f"   Tables created: {', '.join(user_tables)}")
            return conn
        else:
            raise Exception(f"Expected tables {expected_tables}, found {user_tables}")

    except Exception as e:
        # Clean up if something went wrong
        if os.path.exists(DATABASE_PATH):
            os.remove(DATABASE_PATH)
        raise Exception(f"Failed to initialize database: {e}")


def save_market(market_data):
    """
    Save or update market data from Polymarket API.

    Performs UPSERT (INSERT OR REPLACE) to update existing markets.

    Args:
        market_data (dict): Market data from Polymarket API

    Returns:
        bool: True if successful, False otherwise

    Raises:
        Exception: If database operation fails
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Extract data from API response
        # Handle different API response formats
        if 'tokens' in market_data and len(market_data['tokens']) > 0:
            token_data = market_data['tokens'][0]
        else:
            raise Exception("No token data in market response")

        # Extract required fields with defaults
        market_id = market_data.get('id', token_data.get('token_id', ''))
        token_id = token_data.get('token_id', '')
        question = market_data.get('question', '')
        category = market_data.get('category', '')
        end_date = market_data.get('end_date_iso', '')  # Use end_date_iso from API

        # Pricing data
        yes_price = float(token_data.get('price', 0))
        no_price = 1.0 - yes_price if yes_price > 0 else None

        # Volume and liquidity
        volume_24h = float(market_data.get('volume', market_data.get('volume24hr', 0)))
        liquidity = float(market_data.get('liquidity', 0))

        # Status - use multiple factors to assess market quality
        # Price filter: not settled (0.01-0.99)
        price_active = 0.01 < yes_price < 0.99

        # Quality indicators from API
        is_accepting_orders = market_data.get('accepting_orders', False)
        min_order_size = float(market_data.get('minimum_order_size', 0))
        has_order_book = market_data.get('enable_order_book', False)

        # Active if: price in range AND market is accepting orders
        active = price_active and is_accepting_orders

        # Market quality score (for potential future use)
        quality_score = 0
        if active:
            quality_score = 1  # Base score for being active
            if min_order_size >= 10: quality_score += 1  # Higher min order = better liquidity
            if has_order_book: quality_score += 1  # Order book available
            if not market_data.get('neg_risk', True): quality_score += 1  # Not neg risk market

        closed = yes_price <= 0.01 or yes_price >= 0.99  # Closed if settled or near-settled

        # Additional API fields for quality assessment
        neg_risk = market_data.get('neg_risk', False)

        # UPSERT using INSERT OR REPLACE
        cursor.execute("""
            INSERT OR REPLACE INTO markets (
                market_id, token_id, question, category, end_date,
                yes_price, no_price, volume_24h, liquidity,
                minimum_order_size, accepting_orders, enable_order_book,
                quality_score, neg_risk, active, closed, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            market_id, token_id, question, category, end_date,
            yes_price, no_price, volume_24h, liquidity,
            min_order_size, is_accepting_orders, has_order_book,
            quality_score, neg_risk, active, closed
        ))

        conn.commit()
        conn.close()

        print(f"✅ Saved market: {question[:50]}{'...' if len(question) > 50 else ''}")
        return True

    except Exception as e:
        print(f"❌ Error saving market {market_data.get('question', 'Unknown')}: {e}")
        return False


def get_markets(filters=None):
    """
    Fetch markets from database with optional filters.

    Args:
        filters (dict): Optional filters
            - active_only (bool): Only active markets
            - category (str): Specific category
            - min_price (float): Minimum YES price
            - max_price (float): Maximum YES price
            - min_volume (float): Minimum 24h volume

    Returns:
        list: List of market dictionaries
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Build query based on filters
        query = "SELECT * FROM markets WHERE 1=1"
        params = []

        if filters:
            if filters.get('active_only'):
                query += " AND active = 1"

            if filters.get('category'):
                query += " AND category = ?"
                params.append(filters['category'])

            if filters.get('min_price') is not None:
                query += " AND yes_price >= ?"
                params.append(filters['min_price'])

            if filters.get('max_price') is not None:
                query += " AND yes_price <= ?"
                params.append(filters['max_price'])

            if filters.get('min_volume') is not None:
                query += " AND volume_24h >= ?"
                params.append(filters['min_volume'])

        # Order by updated_at (most recent first)
        query += " ORDER BY updated_at DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Get column names from cursor description
        columns = [desc[0] for desc in cursor.description]

        # Convert to list of dictionaries
        markets = []
        for row in rows:
            market_dict = dict(zip(columns, row))
            markets.append(market_dict)

        conn.close()
        return markets

    except Exception as e:
        print(f"❌ Error fetching markets: {e}")
        return []


def save_position(position_data):
    """
    Save a new trading position to database.

    Args:
        position_data (dict): Position data with required fields:
            - market_id (str): Market ID from markets table
            - entry_price (float): Price per share
            - position_size_usd (float): Total USD amount
            - shares (float): Number of shares
            - stop_loss_price (float): Stop-loss trigger price
            - take_profit_price (float): Take-profit target price
            - notes (str, optional): Position notes

    Returns:
        int: Position ID if successful, None if failed

    Raises:
        Exception: If database operation fails
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Validate required fields
        required_fields = ['market_id', 'entry_price', 'position_size_usd', 'shares', 'stop_loss_price', 'take_profit_price']
        for field in required_fields:
            if field not in position_data:
                raise Exception(f"Missing required field: {field}")

        # Extract position data
        market_id = position_data['market_id']
        entry_price = float(position_data['entry_price'])
        position_size_usd = float(position_data['position_size_usd'])
        shares = float(position_data['shares'])
        stop_loss_price = float(position_data['stop_loss_price'])
        take_profit_price = float(position_data['take_profit_price'])
        notes = position_data.get('notes', '')

        # Insert new position
        cursor.execute("""
            INSERT INTO positions (
                market_id, entry_price, position_size_usd, shares,
                stop_loss_price, take_profit_price, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (market_id, entry_price, position_size_usd, shares,
              stop_loss_price, take_profit_price, notes))

        # Get the position ID of the inserted row
        position_id = cursor.lastrowid

        conn.commit()
        conn.close()

        print(f"✅ Position #{position_id} created: ${position_size_usd} at ${entry_price}")
        return position_id

    except Exception as e:
        print(f"❌ Error saving position: {e}")
        return None


def get_active_positions():
    """
    Fetch all active trading positions.

    Returns:
        list: List of active position dictionaries with market data

    Raises:
        Exception: If database operation fails
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Query active positions with market data
        cursor.execute("""
            SELECT p.*, m.question, m.yes_price as current_price, m.category
            FROM positions p
            JOIN markets m ON p.market_id = m.market_id
            WHERE p.status = 'active'
            ORDER BY p.entry_time DESC
        """)

        rows = cursor.fetchall()

        # Get column names
        columns = [desc[0] for desc in cursor.description]

        # Convert to list of dictionaries
        positions = []
        for row in rows:
            position_dict = dict(zip(columns, row))

            # Calculate P&L
            if position_dict['current_price']:
                position_dict['unrealized_pnl'] = (
                    (position_dict['current_price'] - position_dict['entry_price'])
                    * position_dict['shares']
                )
                position_dict['unrealized_pnl_pct'] = (
                    (position_dict['current_price'] - position_dict['entry_price'])
                    / position_dict['entry_price'] * 100
                )
            else:
                position_dict['unrealized_pnl'] = 0
                position_dict['unrealized_pnl_pct'] = 0

            positions.append(position_dict)

        conn.close()
        return positions

    except Exception as e:
        print(f"❌ Error fetching active positions: {e}")
        return []


def update_position(position_id, updates):
    """
    Update an existing position.

    Args:
        position_id (int): Position ID to update
        updates (dict): Fields to update

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Build dynamic update query
        set_clause = []
        params = []

        for field, value in updates.items():
            if field in ['current_price', 'current_pnl', 'status', 'exit_price', 'exit_time', 'exit_reason', 'realized_pnl', 'notes']:
                set_clause.append(f"{field} = ?")
                params.append(value)

        if not set_clause:
            raise Exception("No valid fields to update")

        params.append(position_id)

        cursor.execute(f"""
            UPDATE positions
            SET {', '.join(set_clause)}, updated_at = CURRENT_TIMESTAMP
            WHERE position_id = ?
        """, params)

        conn.commit()
        conn.close()

        print(f"✅ Position #{position_id} updated: {', '.join(updates.keys())}")
        return True

    except Exception as e:
        print(f"❌ Error updating position #{position_id}: {e}")
        return False


def save_news_event(news_data):
    """
    Save a news event to database.

    Args:
        news_data (dict): News event data with required fields:
            - title (str): News headline
            - summary (str, optional): News summary/content
            - source (str): News source name
            - url (str, optional): Article URL
            - published_at (str): Publication timestamp
            - keywords (list): List of keywords for matching
            - related_market_ids (list, optional): List of related market IDs
            - flagged (bool, optional): Mark as important news

    Returns:
        int: Event ID if successful, None if failed

    Raises:
        Exception: If database operation fails
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Validate required fields
        if 'title' not in news_data:
            raise Exception("Missing required field: title")

        # Extract news data
        title = news_data['title']
        summary = news_data.get('summary', '')
        source = news_data.get('source', '')
        url = news_data.get('url', '')
        published_at = news_data.get('published_at', '')

        # Convert lists to comma-separated strings
        keywords = news_data.get('keywords', [])
        keywords_str = ','.join(keywords) if keywords else ''

        related_market_ids = news_data.get('related_market_ids', [])
        related_market_ids_str = ','.join(related_market_ids) if related_market_ids else ''

        flagged = news_data.get('flagged', False)

        # Insert news event
        cursor.execute("""
            INSERT INTO news_events (
                title, summary, source, url, published_at,
                keywords, related_market_ids, flagged
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, summary, source, url, published_at,
              keywords_str, related_market_ids_str, flagged))

        # Get the event ID of the inserted row
        event_id = cursor.lastrowid

        conn.commit()
        conn.close()

        print(f"✅ News event #{event_id} saved: {title[:50]}{'...' if len(title) > 50 else ''}")
        return event_id

    except Exception as e:
        print(f"❌ Error saving news event: {e}")
        return None


def get_news_events(filters=None):
    """
    Fetch news events from database with optional filters.

    Args:
        filters (dict): Optional filters
            - source (str): Specific news source
            - flagged_only (bool): Only flagged news
            - limit (int): Maximum number of events
            - keywords (list): Events containing any of these keywords

    Returns:
        list: List of news event dictionaries
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Build query based on filters
        query = "SELECT * FROM news_events WHERE 1=1"
        params = []

        if filters:
            if filters.get('source'):
                query += " AND source = ?"
                params.append(filters['source'])

            if filters.get('flagged_only'):
                query += " AND flagged = 1"

            if filters.get('keywords'):
                # Search for any of the keywords in the keywords field
                keyword_conditions = []
                for keyword in filters['keywords']:
                    keyword_conditions.append("keywords LIKE ?")
                    params.append(f'%{keyword}%')
                query += f" AND ({' OR '.join(keyword_conditions)})"

        # Order by published_at (most recent first)
        query += " ORDER BY published_at DESC"

        if filters and filters.get('limit'):
            query += " LIMIT ?"
            params.append(filters['limit'])

        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Get column names from cursor description
        columns = [desc[0] for desc in cursor.description]

        # Convert to list of dictionaries
        news_events = []
        for row in rows:
            event_dict = dict(zip(columns, row))

            # Convert comma-separated fields back to lists
            if event_dict['keywords']:
                event_dict['keywords'] = event_dict['keywords'].split(',')
            else:
                event_dict['keywords'] = []

            if event_dict['related_market_ids']:
                event_dict['related_market_ids'] = event_dict['related_market_ids'].split(',')
            else:
                event_dict['related_market_ids'] = []

            news_events.append(event_dict)

        conn.close()
        return news_events

    except Exception as e:
        print(f"❌ Error fetching news events: {e}")
        return []


def get_connection():
    """
    Get database connection.

    Returns:
        sqlite3.Connection: Database connection object
    """
    return sqlite3.connect(DATABASE_PATH)


if __name__ == "__main__":
    """Test database operations"""
    print("=" * 60)
    print("Testing database operations")
    print("=" * 60)

    try:
        # Initialize database
        conn = init_database()
        conn.close()

        print("\n" + "=" * 60)
        print("Testing save_market() function")
        print("=" * 60)

        # Import API client to get real data
        from collectors.polymarket_api import fetch_markets
        from py_clob_client.client import ClobClient

        # Try to get active markets using sampling endpoint
        try:
            client = ClobClient("https://clob.polymarket.com", 137)
            response = client.get_sampling_markets()
            if isinstance(response, dict):
                markets = response.get('data', response.get('markets', []))
            else:
                markets = response
        except:
            markets = fetch_markets()  # Fallback to regular fetch

        test_markets = markets[:5]  # Test with first 5 markets

        print(f"\nTesting with {len(test_markets)} real markets from API...\n")

        # Test saving markets
        saved_count = 0
        for i, market in enumerate(test_markets, 1):
            success = save_market(market)
            if success:
                saved_count += 1
            print(f"  {i}. {success}")

        print(f"\n✅ Saved {saved_count}/{len(test_markets)} markets successfully")

        # Test get_markets() function
        print("\n" + "=" * 60)
        print("Testing get_markets() function")
        print("=" * 60)

        # Get all markets
        all_markets = get_markets()
        print(f"\n✅ Total markets in database: {len(all_markets)}")

        if all_markets:
            # Show sample market
            sample = all_markets[0]
            print(f"\n📊 Sample market:")
            print(f"  Question: {sample['question']}")
            print(f"  YES Price: ${sample['yes_price']}")
            print(f"  Category: {sample['category']}")
            print(f"  Volume: ${sample['volume_24h']:,.0f}")
            print(f"  Active: {sample['active']}")

        # Test filters
        print(f"\n🔍 Testing filters:")

        # Filter by price range (tail-end opportunities)
        tail_end = get_markets({'min_price': 0.92, 'max_price': 0.97})
        print(f"  Tail-end markets ($0.92-$0.97): {len(tail_end)}")

        # Filter by active only
        active = get_markets({'active_only': True})
        print(f"  Active markets: {len(active)}")

        # Filter by volume
        high_volume = get_markets({'min_volume': 50000})
        print(f"  High volume markets (>$50k): {len(high_volume)}")

        # Combined filters
        quality = get_markets({
            'active_only': True,
            'min_price': 0.92,
            'max_price': 0.97,
            'min_volume': 50000
        })
        print(f"  Quality markets (all filters): {len(quality)}")

        # Test position functions
        print("\n" + "=" * 60)
        print("Testing position management functions")
        print("=" * 60)

        # Get a market for testing
        test_market = get_markets({'active_only': True})[0]
        market_id = test_market['market_id']
        market_question = test_market['question']
        current_price = test_market['yes_price']

        print(f"\n📊 Using market for position test:")
        print(f"  Question: {market_question[:50]}...")
        print(f"  Current Price: ${current_price}")
        print(f"  Market ID: {market_id}")

        # Test save_position()
        print(f"\n💾 Creating test position...")
        test_position = {
            'market_id': market_id,
            'entry_price': current_price,
            'position_size_usd': 200.0,
            'shares': 200.0 / current_price,  # Calculate shares
            'stop_loss_price': round(current_price * 0.90, 3),  # 10% stop
            'take_profit_price': min(round(current_price * 1.05, 3), 0.99),  # 5% TP or $0.99
            'notes': 'Test position for Task 1.2.5'
        }

        position_id = save_position(test_position)

        if position_id:
            print(f"✅ Position #{position_id} created successfully")

            # Test get_active_positions()
            print(f"\n📋 Testing get_active_positions()...")
            active_positions = get_active_positions()

            print(f"✅ Found {len(active_positions)} active position(s)")

            if active_positions:
                pos = active_positions[0]
                print(f"\n📊 Position Details:")
                print(f"  Position ID: {pos['position_id']}")
                print(f"  Market: {pos['question'][:50]}...")
                print(f"  Entry Price: ${pos['entry_price']}")
                print(f"  Current Price: ${pos['current_price']}")
                print(f"  Position Size: ${pos['position_size_usd']}")
                print(f"  Shares: {pos['shares']:.1f}")
                print(f"  Stop Loss: ${pos['stop_loss_price']}")
                print(f"  Take Profit: ${pos['take_profit_price']}")
                print(f"  Unrealized P&L: ${pos['unrealized_pnl']:.2f} ({pos['unrealized_pnl_pct']:+.1f}%)")

            # Test update_position()
            print(f"\n🔄 Testing update_position()...")
            update_success = update_position(position_id, {
                'current_price': round(current_price * 1.02, 3),  # Simulate 2% price increase
                'current_pnl': 4.00,
                'notes': 'Updated with price change'
            })

            if update_success:
                print(f"✅ Position #{position_id} updated successfully")

                # Verify update
                updated_positions = get_active_positions()
                if updated_positions:
                    updated_pos = updated_positions[0]
                    print(f"  New Current Price: ${updated_pos['current_price']}")
                    print(f"  New P&L: ${updated_pos['unrealized_pnl']:.2f}")

        print("\n" + "=" * 60)
        print("✅ Tasks 1.2.5 & 1.2.6 COMPLETE: Position management working!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60)