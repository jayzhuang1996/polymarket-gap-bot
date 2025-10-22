-- Polymarket Trading Bot Database Schema
-- Task 1.2.1: Define tables for markets, positions, and news events

-- Table 1: Markets
-- Stores market data from Polymarket API
CREATE TABLE IF NOT EXISTS markets (
    -- Identifiers
    market_id TEXT PRIMARY KEY,
    token_id TEXT NOT NULL,

    -- Market details
    question TEXT NOT NULL,
    category TEXT,
    end_date TIMESTAMP,

    -- Pricing
    yes_price REAL NOT NULL,
    no_price REAL,

    -- Liquidity & volume
    volume_24h REAL DEFAULT 0,
    liquidity REAL DEFAULT 0,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Status
    active BOOLEAN DEFAULT 1,
    closed BOOLEAN DEFAULT 0
);

-- Index for faster queries on active markets
CREATE INDEX IF NOT EXISTS idx_markets_active ON markets(active, yes_price);
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category);


-- Table 2: Positions
-- Tracks our trading positions
CREATE TABLE IF NOT EXISTS positions (
    -- Position identifier
    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,

    -- Entry details
    entry_price REAL NOT NULL,
    entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    position_size_usd REAL NOT NULL,
    shares REAL NOT NULL,

    -- Risk management
    stop_loss_price REAL NOT NULL,
    take_profit_price REAL NOT NULL,

    -- Current status
    current_price REAL,
    current_pnl REAL DEFAULT 0,
    status TEXT DEFAULT 'active',  -- active, stopped_out, take_profit, manual_exit

    -- Exit details (if closed)
    exit_price REAL,
    exit_time TIMESTAMP,
    exit_reason TEXT,
    realized_pnl REAL,

    -- Metadata
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (market_id) REFERENCES markets(market_id)
);

-- Index for faster queries on active positions
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_market ON positions(market_id);


-- Table 3: News Events
-- Stores news/events related to markets (for monitoring)
CREATE TABLE IF NOT EXISTS news_events (
    -- Event identifier
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- News details
    title TEXT NOT NULL,
    summary TEXT,
    source TEXT,
    url TEXT,
    published_at TIMESTAMP,

    -- Keywords for matching to markets
    keywords TEXT,  -- Comma-separated

    -- Related positions (if any)
    related_market_ids TEXT,  -- Comma-separated market IDs

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    flagged BOOLEAN DEFAULT 0  -- Mark important news
);

-- Index for faster keyword searches
CREATE INDEX IF NOT EXISTS idx_news_published ON news_events(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_flagged ON news_events(flagged);
