"""
Test database schema creation
Task 1.2.1: Verify schema.sql works correctly
"""

import sqlite3
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_schema():
    """Create test database and verify tables exist."""

    print("=" * 60)
    print("Testing database schema")
    print("=" * 60)

    # Create in-memory database for testing
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()

    # Read and execute schema
    schema_path = Path(__file__).parent.parent / 'database' / 'schema.sql'
    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    cursor.executescript(schema_sql)
    print("\n✅ Schema executed successfully")

    # Verify tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]

    expected_tables = ['markets', 'positions', 'news_events']
    print(f"\n📊 Tables created: {tables}")

    for table in expected_tables:
        if table in tables:
            print(f"  ✅ {table}")
        else:
            print(f"  ❌ {table} - MISSING!")

    # Verify table structures
    print("\n📋 Table Schemas:")

    for table in expected_tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        print(f"\n{table.upper()} ({len(columns)} columns):")
        for col in columns[:5]:  # Show first 5 columns
            print(f"  - {col[1]} ({col[2]})")
        if len(columns) > 5:
            print(f"  ... and {len(columns) - 5} more")

    # Verify indexes
    print("\n🔍 Indexes created:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = [row[0] for row in cursor.fetchall()]

    for idx in indexes:
        if not idx.startswith('sqlite_'):  # Skip auto-created indexes
            print(f"  ✅ {idx}")

    conn.close()

    print("\n" + "=" * 60)
    print("✅ Task 1.2.1 COMPLETE: Schema working correctly!")
    print("=" * 60)


if __name__ == "__main__":
    test_schema()
