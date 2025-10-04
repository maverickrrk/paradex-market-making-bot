import asyncio
import logging
import time
from typing import Dict, Any, Optional, Set
from decimal import Decimal

from paradex_py import Paradex
from paradex_py.common.order import Order, OrderSide, OrderType
from paradex_py.api.ws_client import ParadexWebsocketChannel

from src.strategies.base_strategy import BaseStrategy


class Trader:
    """
    Represents an independent trading instance for a single wallet on a single market.
    Uses the official Paradex SDK (paradex_py) for all trading operations.
    """

    def __init__(
        self,
        wallet_name: str,
        market_symbol: str,
        strategy: BaseStrategy,
        gateway: Paradex,
        refresh_frequency_ms: int,
    ):
        self.wallet_name = wallet_name
        self.market_symbol = market_symbol
        self.strategy = strategy
        self.gateway = gateway
        self.refresh_rate_sec = refresh_frequency_ms / 1000.0
        
        self.logger = logging.getLogger(f"Trader.{wallet_name}.{market_symbol}")
        self.logger.setLevel(logging.INFO)

        self._is_running = False
        self._our_order_ids: Set[str] = set()
        self.hedger = None
        self._processed_fills: Set[str] = set()
        
        # Position tracking for delta-neutrality
        self._paradex_position = 0.0
        self._hedge_position = 0.0 # Generic hedge position

    async def _setup_websocket_fills(self) -> None:
        """Setup WebSocket fills using the official Paradex SDK."""
        self.logger.info("🔗 Connecting to Paradex WebSocket for fills...")
        await self.gateway.ws_client.connect()
        self.logger.info("✅ WebSocket connected.")

        async def on_fill_message(ws_channel, message):
            try:
                # Ignore messages that are not fills
                if ws_channel != ParadexWebsocketChannel.FILLS: return

                fill_data = message.get('params', {}).get('data', {})
                order_id = fill_data.get('order_id')
                market = fill_data.get('market')
                
                # Process fills only for our market and our own orders
                if market == self.market_symbol and order_id in self._our_order_ids:
                    fill_id = f"{order_id}-{fill_data.get('trade_id')}"
                    if fill_id in self._processed_fills: return

                    side = fill_data.get('side', '').upper()
                    filled_size = float(fill_data.get('size', 0))
                    price = float(fill_data.get('price', 0))

                    self.logger.info(f"🎯 FILL DETECTED: {side} {filled_size:.4f} @ ${price:.2f}")
                    
                    # Update internal position tracker
                    position_change = filled_size if side == "BUY" else -filled_size
                    self._paradex_position += position_change
                    self.logger.info(f"📊 New Paradex Position: {self._paradex_position:.4f}")
                    
                    # Trigger the hedging logic
                    if self.hedger:
                        await self._hedge_position_delta(position_change, price)
                    
                    self._processed_fills.add(fill_id)

            except Exception as e:
                self.logger.error(f"Error processing WebSocket fill: {e}", exc_info=True)

        await self.gateway.ws_client.subscribe(
            ParadexWebsocketChannel.FILLS,
            callback=on_fill_message,
            params={"market": self.market_symbol}
        )
        self.logger.info(f"✅ Subscribed to WebSocket fills for {self.market_symbol}")

    async def _sdk_fetch_orderbook(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self.gateway.api_client.fetch_orderbook, market=self.market_symbol, params={"depth": 10})

    async def _sdk_fetch_positions(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self.gateway.api_client.fetch_positions)

    async def _sdk_fetch_open_orders(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self.gateway.api_client.fetch_orders, params={"market": self.market_symbol})

    async def _sdk_place_order(self, side: str, size: float, price: float) -> Optional[Dict[str, Any]]:
        try:
            order = Order(
                market=self.market_symbol,
                order_type=OrderType.Limit,
                order_side=OrderSide.Buy if side.upper() == "BUY" else OrderSide.Sell,
                size=Decimal(str(size)),
                limit_price=Decimal(str(price)),
                instruction="POST_ONLY",
            )
            return await asyncio.to_thread(self.gateway.api_client.submit_order, order=order)
        except Exception as e:
            self.logger.error(f"❌ Order placement failed: {side} {size:.4f} @ ${price:.2f} - Error: {e}")
            return None

    async def _sdk_cancel_order(self, order_id: str):
        return await asyncio.to_thread(self.gateway.api_client.cancel_order, order_id)

    async def _sdk_fetch_account_summary(self) -> Any:
        return await asyncio.to_thread(self.gateway.api_client.fetch_account_summary)

    async def _cancel_all_orders(self):
        try:
            orders_data = await self._sdk_fetch_open_orders()
            order_list = orders_data.get("orders", [])
            cancel_tasks = [self._sdk_cancel_order(order['id']) for order in order_list if order.get('id')]
            if cancel_tasks:
                self.logger.info(f"Canceling {len(cancel_tasks)} open order(s)...")
                await asyncio.gather(*cancel_tasks)
            self._our_order_ids.clear()
        except Exception as e:
            self.logger.error(f"Error canceling orders: {e}")

    def _create_lob_from_orderbook(self, orderbook: Dict[str, Any]) -> "SimpleLOB":
        bids = [[float(p), float(q)] for p, q in (orderbook.get("bids") or [])]
        asks = [[float(p), float(q)] for p, q in (orderbook.get("asks") or [])]
        return SimpleLOB(bids, asks)

    async def run(self):
        self._is_running = True
        try:
            self.logger.info(f"🚀 Trader starting for {self.market_symbol}...")
            if self.hedger: await self._setup_websocket_fills()
            while self._is_running:
                await self._process_tick()
                await asyncio.sleep(self.refresh_rate_sec)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def _process_tick(self):
        try:
            orderbook_data, positions_data, summary_data, open_orders_data = await asyncio.gather(
                self._sdk_fetch_orderbook(), self._sdk_fetch_positions(),
                self._sdk_fetch_account_summary(), self._sdk_fetch_open_orders()
            )
            
            self._latest_lob = self._create_lob_from_orderbook(orderbook_data)
            if self._latest_lob.is_empty():
                await self._cancel_all_orders()
                return

            current_position = next((float(p.get("size", 0)) for p in positions_data.get("positions", []) if p.get("market") == self.market_symbol), 0.0)
            account_balance = float(getattr(summary_data, "free_collateral", 0))

            quotes = self.strategy.compute_quotes(
                lob_data=self._latest_lob,
                current_position=current_position,
                account_balance=account_balance,
            )
            
            if quotes: await self._reconcile_orders(quotes)
            else: await self._cancel_all_orders()
        except Exception as e:
            self.logger.error(f"Error in process_tick: {e}", exc_info=True)

    async def _reconcile_orders(self, quotes: Dict[str, Any]):
        await self._cancel_all_orders()
        place_tasks = [self._place_order(o["side"], o["size"], o["price"]) for o in quotes.get("buy_orders", []) + quotes.get("sell_orders", [])]
        results = await asyncio.gather(*place_tasks)
        self._our_order_ids.update(res['id'] for res in results if res and res.get('id'))

    async def _hedge_position_delta(self, position_change: float, price: float):
        """Hedges a change in position to maintain delta neutrality."""
        if not self.hedger: return

        # A positive change means we BOUGHT on Paradex, so we need to SELL on the hedge exchange.
        # A negative change means we SOLD on Paradex, so we need to BUY on the hedge exchange.
        hedge_side = "SELL" if position_change > 0 else "BUY"
        hedge_size = abs(position_change)

        self.logger.info(f"Hedging position change: {hedge_side} {hedge_size:.4f} on hedge exchange.")
        
        result = await self.hedger.on_paradex_fill(
            market=self.market_symbol,
            # Pass the ORIGINAL Paradex side to the orchestrator for its logic
            side="BUY" if position_change > 0 else "SELL",
            size=hedge_size,
            price=price
        )

        # Update internal hedge position tracker if successful
        if result and result.get("status") in ("accepted", "filled"):
            hedge_position_change = -position_change # Opposite direction
            self._hedge_position += hedge_position_change
            self.logger.info(f"📊 New Hedge Position: {self._hedge_position:.4f}")

    async def stop(self):
        if not self._is_running: return
        self.logger.info("Stopping trader...")
        self._is_running = False
        await self._cancel_all_orders()
        if self.gateway.ws_client.is_connected:
            await self.gateway.ws_client.disconnect()
        self.logger.info("Trader stopped.")

class SimpleLOB:
    def __init__(self, bids: list, asks: list):
        self.bids = bids; self.asks = asks
    def is_empty(self) -> bool: return not self.bids and not self.asks
    def get_mid(self) -> Optional[float]: return (self.bids[0][0] + self.asks[0][0]) / 2 if self.bids and self.asks else None
    def get_vamp(self, notional: float) -> Optional[float]: return self.get_mid()