"""
Polymarket CLOB order execution layer.

Wraps py-clob-client with a dry-run safety mode and simple buy/sell helpers.
All public methods are synchronous — callers should use asyncio.to_thread() to
avoid blocking the event loop.

Safety:
    Set LIVE_TRADING=true in .env to place real orders.
    Default is dry-run: logs what would happen but never calls the CLOB.

Usage:
    mgr = OrderManager(private_key=os.getenv("POLYMARKET_PRIVATE_KEY"))
    order_id = mgr.place_buy(token_id, price=0.54, size_usd=54.0)
    fill     = mgr.check_fill(order_id)
    mgr.cancel(order_id)
"""

from __future__ import annotations

import os
import time
import logging
from typing import Optional

log = logging.getLogger(__name__)

# Side constants from py-clob-client
try:
    from py_clob_client.order_builder.constants import BUY, SELL
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    _CLIENT_AVAILABLE = True
except ImportError:
    _CLIENT_AVAILABLE = False
    BUY = "BUY"
    SELL = "SELL"

from config import CLOB_API, POLYMARKET_CHAIN_ID

# Minimum contracts — CLOB rejects orders below this
MIN_ORDER_SIZE = 5.0
# Limit order TTL passed to GTD orders (seconds)
ORDER_TTL_SEC = 120


class OrderManager:
    """
    Thin wrapper around ClobClient.

    In dry-run mode (LIVE_TRADING != 'true'), every method logs what it
    would do and returns a fake order-id / fill dict instead of hitting the API.
    """

    def __init__(self, private_key: str) -> None:
        self._live = os.getenv("LIVE_TRADING", "false").lower() == "true"
        self._client: Optional[ClobClient] = None

        if self._live:
            if not _CLIENT_AVAILABLE:
                raise RuntimeError("py-clob-client not installed — cannot run live")
            if not private_key:
                raise RuntimeError("POLYMARKET_PRIVATE_KEY missing — cannot run live")
            self._client = ClobClient(
                host=CLOB_API,
                key=private_key,
                chain_id=POLYMARKET_CHAIN_ID,
            )
            creds = self._client.create_or_derive_api_creds()
            self._client.set_api_creds(creds)
            log.warning("OrderManager LIVE MODE — real orders will be placed")
        else:
            log.info("OrderManager DRY-RUN — no real orders will be placed")

    @property
    def is_live(self) -> bool:
        return self._live

    # ── Buy ───────────────────────────────────────────────────────────────────

    def place_buy(
        self,
        token_id: str,
        price: float,
        size_usd: float,
    ) -> str | None:
        """
        Place a GTC limit buy order.

        Args:
            token_id:  YES or NO token ID from market discovery.
            price:     Limit price (e.g. 0.54 means 54¢ per contract).
            size_usd:  Dollar amount to spend. Converted to contracts internally.

        Returns:
            order_id string if placed, None if skipped (size too small).
        """
        size_contracts = round(size_usd / price, 1)
        if size_contracts < MIN_ORDER_SIZE:
            log.info("place_buy: size %.1f contracts below minimum — skipped", size_contracts)
            return None

        if not self._live:
            fake_id = f"dry-buy-{int(time.time())}"
            log.info(
                "DRY-RUN place_buy  token=…%s  price=%.3f  size=%.1f contracts  (~$%.2f)  id=%s",
                token_id[-8:], price, size_contracts, size_usd, fake_id,
            )
            return fake_id

        try:
            order = self._client.create_order(OrderArgs(
                token_id=token_id,
                price=round(price, 3),
                size=size_contracts,
                side=BUY,
            ))
            resp = self._client.post_order(order, OrderType.GTC)
            order_id = resp.get("orderID") or resp.get("id") or str(resp)
            log.info(
                "LIVE place_buy  token=…%s  price=%.3f  size=%.1f  id=%s",
                token_id[-8:], price, size_contracts, order_id,
            )
            return order_id
        except Exception as exc:
            log.error("place_buy failed: %s", exc)
            return None

    # ── Sell ──────────────────────────────────────────────────────────────────

    def place_sell(
        self,
        token_id: str,
        price: float,
        size_contracts: float,
    ) -> str | None:
        """
        Place a GTC limit sell order.

        Args:
            token_id:       YES or NO token ID.
            price:          Limit price (e.g. 0.71 = 71¢).
            size_contracts: Number of contracts to sell.

        Returns:
            order_id string if placed, None on failure.
        """
        size_contracts = round(size_contracts, 1)
        if size_contracts < MIN_ORDER_SIZE:
            log.info("place_sell: size %.1f below minimum — skipped", size_contracts)
            return None

        if not self._live:
            fake_id = f"dry-sell-{int(time.time())}"
            log.info(
                "DRY-RUN place_sell  token=…%s  price=%.3f  size=%.1f  id=%s",
                token_id[-8:], price, size_contracts, fake_id,
            )
            return fake_id

        try:
            order = self._client.create_order(OrderArgs(
                token_id=token_id,
                price=round(price, 3),
                size=size_contracts,
                side=SELL,
            ))
            resp = self._client.post_order(order, OrderType.GTC)
            order_id = resp.get("orderID") or resp.get("id") or str(resp)
            log.info(
                "LIVE place_sell  token=…%s  price=%.3f  size=%.1f  id=%s",
                token_id[-8:], price, size_contracts, order_id,
            )
            return order_id
        except Exception as exc:
            log.error("place_sell failed: %s", exc)
            return None

    # ── Fill check ────────────────────────────────────────────────────────────

    def check_fill(self, order_id: str) -> dict:
        """
        Return fill status for an order.

        Returns dict with keys:
            status       — "MATCHED" | "LIVE" | "CANCELLED" | "UNKNOWN"
            size_matched — contracts filled (float)
            avg_price    — average fill price (float)
        """
        if not self._live or order_id.startswith("dry-"):
            # Dry-run: simulate an immediate fill at the submitted price
            return {"status": "MATCHED", "size_matched": 999.0, "avg_price": 0.0}

        try:
            resp = self._client.get_order(order_id)
            status       = resp.get("status", "UNKNOWN")
            size_matched = float(resp.get("sizeMatched") or resp.get("size_matched") or 0)
            avg_price    = float(resp.get("avgPrice")    or resp.get("avg_price")    or 0)
            return {"status": status, "size_matched": size_matched, "avg_price": avg_price}
        except Exception as exc:
            log.error("check_fill %s failed: %s", order_id, exc)
            return {"status": "UNKNOWN", "size_matched": 0.0, "avg_price": 0.0}

    # ── Cancel ────────────────────────────────────────────────────────────────

    def cancel(self, order_id: str) -> bool:
        """Cancel an open order. Returns True on success."""
        if not self._live or order_id.startswith("dry-"):
            log.info("DRY-RUN cancel  id=%s", order_id)
            return True

        try:
            self._client.cancel(order_id)
            log.info("LIVE cancel  id=%s", order_id)
            return True
        except Exception as exc:
            log.error("cancel %s failed: %s", order_id, exc)
            return False
