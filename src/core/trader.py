# FILE: src/core/trader.py
import asyncio
import logging
from typing import Dict, Any, List
import numpy as np
from decimal import Decimal

# DEFINITIVE CORRECTED IMPORTS
from paradex_py import Paradex
from paradex_py.api.ws_client import ParadexWebsocketChannel
from paradex_py.message.order import Order
from paradex_py.common.order import OrderSide, OrderType

from src.strategies.base_strategy import BaseStrategy

# A simple, self-contained LOB class to replace the quantpylib one.
# It processes raw websocket data and provides methods for strategy calculations.
class SimpleLOB:
    """A lightweight LOB representation for processing Paradex websocket data."""
    def __init__(self):
        self.bids = np.array([])
        self.asks = np.array([])

    def update_from_snapshot(self, snapshot_data: Dict[str, Any]):
        """Processes a full order book snapshot from the websocket."""
        # Paradex provides prices and sizes as strings, convert them to floats
        self.bids = np.array([[float(p), float(s)] for p, s in snapshot_data.get("bids", []) if p and s])
        self.asks = np.array([[float(p), float(s)] for p, s in snapshot_data.get("asks", []) if p and s])

    def is_empty(self) -> bool:
        """Check if the order book has data."""
        return self.bids.size == 0 or self.asks.size == 0

    def get_mid(self) -> float:
        """Calculates the mid-price."""
        if self.is_empty():
            return None
        best_bid = self.bids[0, 0]
        best_ask = self.asks[0, 0]
        return (best_bid + best_ask) / 2.0

    def get_vamp(self, notional: float) -> float:
        """
        Calculates the Volume-Adjusted Mid-Price (VAMP) for a given notional value.
        This is a re-implementation of the logic required by our VAMP strategy.
        """
        if self.is_empty():
            return None
        
        try:
            # Calculate VWAP for bids
            bid_levels = self.bids
            bid_notionals = bid_levels[:, 0] * bid_levels[:, 1]
            cumulative_bid_notional = np.cumsum(bid_notionals)
            bid_idx = np.searchsorted(cumulative_bid_notional, notional)
            if bid_idx >= len(bid_levels):
                bid_vwap = bid_levels[-1, 0] # Fallback to last level price
            else:
                relevant_bids = bid_levels[:bid_idx + 1]
                total_size = np.sum(relevant_bids[:, 1])
                total_notional = np.sum(relevant_bids[:, 0] * relevant_bids[:, 1])
                bid_vwap = total_notional / total_size

            # Calculate VWAP for asks
            ask_levels = self.asks
            ask_notionals = ask_levels[:, 0] * ask_levels[:, 1]
            cumulative_ask_notional = np.cumsum(ask_notionals)
            ask_idx = np.searchsorted(cumulative_ask_notional, notional)
            if ask_idx >= len(ask_levels):
                ask_vwap = ask_levels[-1, 0] # Fallback to last level price
            else:
                relevant_asks = ask_levels[:ask_idx + 1]
                total_size = np.sum(relevant_asks[:, 1])
                total_notional = np.sum(relevant_asks[:, 0] * relevant_asks[:, 1])
                ask_vwap = total_notional / total_size
                
            return (bid_vwap + ask_vwap) / 2.0
        except (IndexError, ZeroDivisionError):
            return self.get_mid() # Fallback to mid-price on any calculation error

class Trader:
    """
    Represents an independent trading instance for a single wallet on a single market.
    It uses the official paradex-py SDK for all exchange interactions.
    """
    def __init__(
        self,
        wallet_name: str,
        market_symbol: str,
        strategy: BaseStrategy,
        client: Paradex,
        refresh_frequency_ms: int
    ):
        self.wallet_name = wallet_name
        self.market_symbol = market_symbol
        self.strategy = strategy
        self.client = client # The dedicated, initialized Paradex client for this wallet
        self.refresh_rate_sec = refresh_frequency_ms / 1000.0
        
        self.logger = logging.getLogger(f"Trader.{wallet_name}.{market_symbol}")
        
        self._is_running = False
        self._latest_lob = SimpleLOB()

    async def _lob_handler(self, channel: str, lob_data: Dict[str, Any]):
        """Async handler to process incoming L2 order book updates."""
        self._latest_lob.update_from_snapshot(lob_data)

    async def run(self):
        """
        The main execution loop for the trader.
        """
        self.logger.info("Starting trader...")
        self._is_running = True
        
        try:
            # Connect to the WebSocket
            await self.client.ws_client.connect()
            self.logger.info("WebSocket connected.")

            # Subscribe to the L2 order book feed for the market
            await self.client.ws_client.subscribe(
                ParadexWebsocketChannel.ORDER_BOOK,
                callback=self._lob_handler,
                params={
                    "market": self.market_symbol,
                    "depth": "20",
                    "refresh_rate": "100ms",
                    "price_tick": "1"
                }
            )
            self.logger.info(f"Subscribed to L2 order book for {self.market_symbol}.")
            
            # Allow a moment for the first order book snapshot to arrive
            await asyncio.sleep(3)

            while self._is_running:
                start_time = asyncio.get_event_loop().time()

                if not self._latest_lob.is_empty():
                    await self._process_tick()
                else:
                    self.logger.warning("No order book data received yet. Waiting...")

                elapsed_time = asyncio.get_event_loop().time() - start_time
                sleep_duration = max(0, self.refresh_rate_sec - elapsed_time)
                await asyncio.sleep(sleep_duration)

        except asyncio.CancelledError:
            self.logger.info("Trader task was cancelled.")
        except Exception as e:
            self.logger.critical(f"An unhandled error occurred in the main loop: {e}", exc_info=True)
        finally:
            await self.stop()

    async def _process_tick(self):
        """
        The core logic executed on each "tick" or refresh cycle.
        """
        try:
            # 1. Get current position
            positions_response = self.client.api_client.fetch_positions()
            current_position = 0.0
            for pos in positions_response.get("results", []):
                if pos.get("market") == self.market_symbol:
                    current_position = float(pos.get("size", 0.0))
                    break
            
            # Account balance isn't used by VAMP, so we pass a placeholder.
            account_balance = 0.0

            # 2. Compute desired quotes using the strategy
            quotes = self.strategy.compute_quotes(
                lob_data=self._latest_lob,
                current_position=current_position,
                account_balance=account_balance
            )

            # 3. Reconcile orders
            if quotes:
                await self._update_quotes(*quotes)
            else:
                self.logger.info("Strategy returned no quotes. Cancelling all orders for safety.")
                await self._cancel_all_market_orders()

        except Exception as e:
            self.logger.error(f"Error during tick processing: {e}", exc_info=True)

    async def _update_quotes(self, bid_price: float, bid_size: float, ask_price: float, ask_size: float):
        """
        Reconciles current open orders with the desired quotes using batch operations.
        """
        orders_to_cancel_ids = []
        place_new_bid = True
        place_new_ask = True

        # Get current open orders for this market
        open_orders_response = self.client.api_client.fetch_orders()
        
        for order in open_orders_response.get("results", []):
            order_price = float(order['price'])
            # Check bids
            if order['side'] == 'BUY':
                if abs(order_price - bid_price) < 1e-9: # Compare floats safely
                    place_new_bid = False # Desired bid already exists
                else:
                    orders_to_cancel_ids.append(order['id'])
            # Check asks
            else: # SELL
                if abs(order_price - ask_price) < 1e-9:
                    place_new_ask = False # Desired ask already exists
                else:
                    orders_to_cancel_ids.append(order['id'])

        # 1. Cancel stale orders if needed
        if orders_to_cancel_ids:
            self.logger.info(f"Cancelling {len(orders_to_cancel_ids)} stale order(s).")
            try:
                cancel_result = self.client.api_client.cancel_orders_batch(order_ids=orders_to_cancel_ids)
                self.logger.debug(f"Cancel result: {cancel_result}")
            except Exception as e:
                self.logger.error(f"Error cancelling orders: {e}")

        # 2. Place new orders if needed
        new_orders = []
        if place_new_bid:
            new_orders.append(Order(
                market=self.market_symbol, 
                order_type=OrderType.LIMIT, 
                order_side=OrderSide.BUY, 
                size=Decimal(str(bid_size)), 
                limit_price=Decimal(str(bid_price))
            ))
        if place_new_ask:
            new_orders.append(Order(
                market=self.market_symbol, 
                order_type=OrderType.LIMIT, 
                order_side=OrderSide.SELL, 
                size=Decimal(str(ask_size)), 
                limit_price=Decimal(str(ask_price))
            ))

        if new_orders:
            self.logger.info(f"Placing {len(new_orders)} new order(s).")
            try:
                placement_result = self.client.api_client.submit_orders_batch(orders=new_orders)
                self.logger.debug(f"Placement result: {placement_result}")
            except Exception as e:
                self.logger.error(f"Error placing orders: {e}")

    async def _cancel_all_market_orders(self):
        """Cancels all open orders for this trader's specific market."""
        try:
            result = self.client.api_client.cancel_all_orders()
            self.logger.info(f"Successfully cancelled all orders for {self.market_symbol}.")
        except Exception as e:
            self.logger.error(f"Failed to cancel all orders for {self.market_symbol}: {e}", exc_info=True)

    async def stop(self):
        """Gracefully stops the trader and cleans up resources."""
        if not self._is_running:
            return
            
        self.logger.info("Stopping trader...")
        self._is_running = False

        # Perform final order cancellation. The manager will handle client cleanup.
        await self._cancel_all_market_orders()
        self.logger.info("Trader stopped.")