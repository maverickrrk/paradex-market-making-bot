import asyncio
import logging
from typing import Dict, Any

from .custom_gateway import CustomGateway
from .custom_oms import CustomOMS
from .custom_feed import CustomFeed, CustomLOB

from src.strategies.base_strategy import BaseStrategy

class Trader:
    """
    Represents an independent trading instance for a single wallet on a single market.

    Each Trader instance runs its own asynchronous loop, managing its own
    state (orders, positions) and executing a specific trading strategy.
    """
    def __init__(
        self,
        wallet_name: str,
        market_symbol: str,
        strategy: BaseStrategy,
        gateway: CustomGateway,
        refresh_frequency_ms: int
    ):
        """
        Initializes the Trader instance.

        Args:
            wallet_name: The identifier for the wallet this trader will manage.
            market_symbol: The market symbol to trade (e.g., 'BTC-USD-PERP').
            strategy: An instantiated strategy object (e.g., VampMM).
            gateway: The shared, initialized quantpylib Gateway instance.
            refresh_frequency_ms: The time in ms to wait between quote updates.
        """
        self.wallet_name = wallet_name
        self.market_symbol = market_symbol
        self.strategy = strategy
        self.gateway = gateway
        self.refresh_rate_sec = refresh_frequency_ms / 1000.0
        
        self.logger = logging.getLogger(f"Trader.{wallet_name}.{market_symbol}")
        
        # Each trader gets its own independent OMS and Feed
        self.oms = CustomOMS(gateway=self.gateway)
        self.feed = CustomFeed(gateway=self.gateway)

        self._is_running = False
        self._main_task = None
        self._latest_lob = None

    async def _lob_handler(self, lob_data: CustomLOB):
        """Async handler to process incoming L2 order book updates."""
        self._latest_lob = lob_data

    async def run(self):
        """
        The main execution loop for the trader.

        This method initializes the OMS and data feeds, then enters a loop
        to continuously fetch market data, compute quotes via the strategy,
        and update orders on the exchange.
        """
        self.logger.info("Starting trader...")
        self._is_running = True
        
        try:
            # Initialize the Order Management System
            await self.oms.init()
            self.logger.info("OMS initialized successfully.")

            # Start the feed
            self.feed.start()
            
            # Subscribe to the L2 order book feed for the market
            await self.feed.add_l2_book_feed(
                exc='paradex',
                ticker=self.market_symbol,
                handler=self._lob_handler,
                depth=20 # Requesting a reasonable depth for VAMP calculations
            )
            self.logger.info(f"Subscribed to L2 order book for {self.market_symbol}.")
            
            # Allow a moment for the first order book snapshot to arrive
            await asyncio.sleep(3)

            while self._is_running:
                start_time = asyncio.get_event_loop().time()

                if self._latest_lob:
                    await self._process_tick()
                else:
                    self.logger.warning("No order book data received yet. Waiting...")

                # Wait for the next cycle, accounting for processing time
                elapsed_time = asyncio.get_event_loop().time() - start_time
                sleep_duration = max(0, self.refresh_rate_sec - elapsed_time)
                await asyncio.sleep(sleep_duration)

        except asyncio.CancelledError:
            self.logger.info("Trader task was cancelled.")
        except Exception as e:
            self.logger.critical(f"An unhandled error occurred in the main loop: {e}", exc_info=True)
            self._is_running = False
        finally:
            await self.stop()

    async def _process_tick(self):
        """
        The core logic executed on each "tick" or refresh cycle.
        """
        try:
            # 1. Get current state (position and balance) from OMS
            positions = self.oms.positions_peek(exc='paradex')
            current_position = positions.get_ticker_amount(self.market_symbol)
            # Placeholder for balance; adapt if strategy needs it
            account_balance = 0.0 

            # 2. Compute desired quotes using the strategy
            quotes = self.strategy.compute_quotes(
                lob_data=self._latest_lob,
                current_position=current_position,
                account_balance=account_balance
            )

            # 3. Execute the new quotes
            if quotes:
                bid_price, bid_size, ask_price, ask_size = quotes
                await self._update_quotes(bid_price, bid_size, ask_price, ask_size)
            else:
                # If strategy returns None, it means we should not quote.
                # We should cancel existing quotes to be safe.
                self.logger.info("Strategy returned no quotes. Cancelling existing orders.")
                await self._cancel_all_market_orders()

        except Exception as e:
            self.logger.error(f"Error during tick processing: {e}", exc_info=True)


    async def _update_quotes(self, bid_price: float, bid_size: float, ask_price: float, ask_size: float):
        """
        Reconciles current open orders with the desired quotes from the strategy.
        """
        orders_to_cancel = []
        place_new_bid = True
        place_new_ask = True

        # Get current open orders for this market
        live_orders = self.oms.orders_peek(exc='paradex')
        market_orders = live_orders.get_orders(ticker=self.market_symbol)

        for order in market_orders:
            # Check bids (positive amount = buy order)
            if float(order.amount) > 0:
                if abs(float(order.price) - bid_price) < 1e-9: # Compare floats safely
                    place_new_bid = False # Desired bid already exists
                else:
                    orders_to_cancel.append(order)
            # Check asks (negative amount = sell order)
            else:
                if abs(float(order.price) - ask_price) < 1e-9:
                    place_new_ask = False # Desired ask already exists
                else:
                    orders_to_cancel.append(order)

        # --- Concurrently execute changes ---
        tasks = []
        # Cancel stale orders
        for order in orders_to_cancel:
            side = "BUY" if float(order.amount) > 0 else "SELL"
            self.logger.info(f"Cancelling stale order: {side} {order.amount} @ {order.price}")
            tasks.append(self.oms.cancel_order(
                exc='paradex', ticker=self.market_symbol, cloid=order.cloid
            ))

        # Place new orders if needed
        if place_new_bid:
            tasks.append(self.oms.limit_order(
                exc='paradex', ticker=self.market_symbol, amount=bid_size, price=bid_price, post_only=True
            ))
        if place_new_ask:
            tasks.append(self.oms.limit_order(
                exc='paradex', ticker=self.market_symbol, amount=-ask_size, price=ask_price, post_only=True
            ))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    self.logger.error(f"Error during order update operation: {res}")


    async def _cancel_all_market_orders(self):
        """Cancels all open orders for this trader's specific market."""
        try:
            await self.oms.cancel_all_orders(exc='paradex', ticker=self.market_symbol)
            self.logger.info(f"Successfully cancelled all orders for {self.market_symbol}.")
        except Exception as e:
            self.logger.error(f"Failed to cancel all orders for {self.market_symbol}: {e}", exc_info=True)

    async def stop(self):
        """
        Gracefully stops the trader and cleans up resources.
        """
        if not self._is_running:
            return
            
        self.logger.info("Stopping trader...")
        self._is_running = False

        # Cancel the main task if it's running
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
        
        # Clean up by cancelling any remaining open orders
        self.logger.info("Performing final order cancellation...")
        await self._cancel_all_market_orders()
        self.logger.info("Trader stopped.")