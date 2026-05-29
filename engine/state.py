"""Shared mutable state — single source of truth for all engine and API modules.

All fields are module-level globals. Modules import this module by reference
(``import engine.state as state``) so mutations are visible everywhere.
"""

import asyncio
from datetime import datetime

# ── Real-time market data ──────────────────────────────────────────────────────
current_quotes: dict[str, dict] = {}           # ticker → live quote dict
token_map: dict[str, dict] = {}                # asset_id → {ticker, side}
market_list: list[dict] = []                   # today's discovered markets
wr_cache: dict[str, tuple[float, float]] = {}  # ticker → (yes_wr, no_wr)

# ── WebSocket broadcast ────────────────────────────────────────────────────────
connected_clients: set = set()                 # set[WebSocket]
broadcast_queue: asyncio.Queue = asyncio.Queue()

# ── Order execution ────────────────────────────────────────────────────────────
# Set to an OrderManager instance in server.py lifespan; None before startup.
order_manager = None

# ── Trading session state (reset each trading day by session.py) ──────────────
_signal_history: dict[str, list[str]] = {}
_session_entered: set[str] = set()
_session_aborted: set[str] = set()
_exit_triggers_fired: dict[str, set[str]] = {}
_gfr_exit_cooldowns: dict[str, datetime] = {}
_remaining_fractions: dict[str, float] = {}
_prev_gfr: dict[str, float] = {}
_gfr_snapshot: dict[str, float] = {}
_pending_orders: dict[str, dict] = {}
_held_contracts: dict[str, float] = {}
_no_token_peak: dict[str, float] = {}
_decision_ids: dict[str, int] = {}
_realized_pnl: dict[str, float] = {}

# Rolling stock_pos history for momentum calculation (15 × 2-min ticks = 30 min).
# Populated by data_feed.stock_price_loop(); reset by session.py daily reset.
_stock_pos_history: dict[str, list[float]] = {}

# VIX snapshot — fetched once at session start, held constant for the day.
# Must be reassigned via ``state._vix_change = x`` (not via local rebinding).
_vix_change: float | None = None
_vix_high: bool = False
