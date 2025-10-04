import asyncio
import logging
import time
from typing import Dict, Any, Optional, Set
from decimal import Decimal

from paradex_py import Paradex
from paradex_py.common.order import Order, OrderSide, OrderType

from src.strategies.base_strategy import BaseStrategy
from src.core.paradex_ws import ParadexWSFills


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
        self._main_task: Optional[asyncio.Task] = None
        self._latest_lob: Optional["SimpleLOB"] = None
        
        # Sequential trading state tracking
        self._trading_state = "IDLE"  # IDLE, WAITING_FOR_BUY, WAITING_FOR_SELL
        self._current_buy_order_id: Optional[str] = None
        self._current_sell_order_id: Optional[str] = None
        self._last_order_side: Optional[str] = None
        # Track last known open orders per side
        self._open_orders_cache: Dict[str, list] = {"BUY": [], "SELL": []}

        # Optional hedger injected by orchestrator (OneClickHedger)
        self.hedger = None
        # Track individual fills for simple hedging (no rebalancing)
        self._processed_fills: Set[str] = set()  # Track which fills we've already hedged
        self._fills_ws: Optional[ParadexWSFills] = None
        self._has_placed_orders = False  # Track if we've successfully placed any orders
        self._our_order_ids: Set[str] = set()  # Track all order IDs we've placed (including filled ones)
        
        # Position-based hedging
        self._paradex_position = 0.0  # Track net Paradex position
        self._hyperliquid_position = 0.0  # Track net Hyperliquid position

    # ---------------------------
    # SDK wrapper helpers (sync -> async)
    # ---------------------------
    async def _fetch_account_info(self) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self.gateway.api_client.fetch_account_info)
        except Exception as e:
            return {}

    async def _setup_websocket_fills(self) -> None:
        """Setup WebSocket fills for real-time fill detection."""
        try:
            # Get WebSocket URL and bearer token from the gateway
            ws_url = 'wss://ws.api.prod.paradex.trade/v1'
            
            def get_bearer() -> Optional[str]:
                try:
                    # Try to get bearer token from the gateway
                    return getattr(self.gateway.api_client, 'bearer_token', None)
                except Exception:
                    return None
            
            async def on_fill(fill_data: Dict[str, Any]) -> None:
                """Handle WebSocket fill events."""
                try:
                    order_id = fill_data.get("order_id")
                    side = fill_data.get("side", "").upper()
                    filled_size = float(fill_data.get("filled", 0))
                    price = float(fill_data.get("price", 0))
                    
                    self.logger.info(f"🔍 WebSocket fill received: order_id={order_id}, side={side}, size={filled_size}, price={price}")
                    self.logger.info(f"🔍 Our order IDs: {list(self._our_order_ids)}")
                    
                    # Only process fills from our orders
                    if order_id and order_id in self._our_order_ids and filled_size > 0:
                        # Skip if already processed
                        if order_id in self._processed_fills:
                            self.logger.info(f"⏭️  Fill already processed: {order_id}")
                            return
                        
                        self.logger.info(f"🎯 FILL: {side} {filled_size:.4f} @ ${price:.2f}")
                        
                        # Update Paradex position
                        if side == "BUY":
                            self._paradex_position += filled_size
                        else:
                            self._paradex_position -= filled_size
                        
                        self.logger.info(f"📊 Paradex position: {self._paradex_position:.4f} ETH")
                        
                        # Check if we need to hedge the net position
                        self.logger.info("🔄 Calling _hedge_net_position...")
                        await self._hedge_net_position()
                        
                        # Mark as processed
                        self._processed_fills.add(order_id)
                    else:
                        self.logger.info(f"⏭️  Skipping fill - not our order or invalid data")
                        
                except Exception as e:
                    self.logger.error(f"Error processing WebSocket fill: {e}")
            
            # Create and start WebSocket fills
            self._fills_ws = ParadexWSFills(ws_url, get_bearer, on_fill)
            await self._fills_ws.start()
            self.logger.info("✅ WebSocket fills active")
            
        except Exception as e:
            self.logger.error(f"WebSocket setup failed: {e}")
            self.logger.info("🔄 Falling back to polling-based fill detection")
            self._fills_ws = None

    async def _sdk_fetch_orderbook(self) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(
                self.gateway.api_client.fetch_orderbook,
                market=self.market_symbol,
                params={"depth": 10},
            )
        except Exception as e:
            return {"bids": [], "asks": []}

    async def _sdk_fetch_positions(self) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self.gateway.api_client.fetch_positions)
        except Exception as e:
            return {"positions": []}

    async def _sdk_fetch_orders(self) -> Dict[str, Any]:
        try:
            result = await asyncio.to_thread(
                self.gateway.api_client.fetch_orders, params={"market": self.market_symbol}
            )
            return result
        except Exception as e:
            self.logger.error(f"❌ Orders API error: {e}")
            return {"orders": []}
    
    async def _sdk_fetch_trades(self) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(
                self.gateway.api_client.fetch_trades, params={"market": self.market_symbol}
            )
        except Exception as e:
            return {"results": []}

    async def _sdk_fetch_balances(self) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self.gateway.api_client.fetch_balances)
        except Exception as e:
            return {"results": []}

    async def _sdk_fetch_account_summary(self) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self.gateway.api_client.fetch_account_summary)
        except Exception as e:
            return {}

    async def _sdk_place_order(self, side: str, size: float, price: float) -> Any:
        try:
            from datetime import datetime
            order_side = OrderSide.Buy if side.upper() == "BUY" else OrderSide.Sell
            client_id = f"bot_{side.lower()}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            order = Order(
                market=self.market_symbol,
                order_type=OrderType.Limit,
                order_side=order_side,
                size=Decimal(str(size)),
                limit_price=Decimal(str(price)),
                client_id=client_id,
                instruction="POST_ONLY",
                reduce_only=False,
            )
            # Use the correct API call with order= parameter
            result = await asyncio.to_thread(self.gateway.api_client.submit_order, order=order)
            return result
        except Exception as e:
            self.logger.error(f"❌ Order placement failed: {side} {size:.4f} @ ${price:.2f} - Error: {e}")
            return None

    async def _sdk_cancel_order(self, order_id: str) -> Any:
        try:
            return await asyncio.to_thread(self.gateway.api_client.cancel_order, order_id)
        except Exception as e:
            return None

    # ---------------------------
    # Higher-level trader helpers
    # ---------------------------
    async def _get_orderbook(self) -> Dict[str, Any]:
        return await self._sdk_fetch_orderbook()

    async def _get_positions(self) -> Dict[str, Any]:
        return await self._sdk_fetch_positions()

    async def _get_orders(self) -> Dict[str, Any]:
        return await self._sdk_fetch_orders()

    async def _place_order(self, side: str, amount: float, price: float) -> Optional[str]:
        result = await self._sdk_place_order(side, amount, price)
        if result:
            self.logger.info(f"✅ {side} {amount:.4f} @ ${price:.2f}")
            self._has_placed_orders = True  # Mark that we've successfully placed orders
            if isinstance(result, dict):
                order_id = result.get("id") or result.get("order_id") or str(result)
                self._our_order_ids.add(order_id)  # Track this order ID for WebSocket fills
                return order_id
            order_id = str(result)
            self._our_order_ids.add(order_id)  # Track this order ID for WebSocket fills
            return order_id
        else:
            self.logger.error(f"❌ {side} order FAILED: {amount} @ {price:.2f}")
        return None

    async def _cancel_order(self, order_id: str) -> bool:
        await self._sdk_cancel_order(order_id)
        return True

    async def _cancel_all_orders(self):
        orders = await self._get_orders()
        order_list = orders.get("orders", []) or orders.get("results", []) or []
        for order in order_list:
            oid = order.get("id") or order.get("order_id") if isinstance(order, dict) else str(order)
            if oid:
                await self._cancel_order(oid)

    def _price_bps_diff(self, price_a: float, price_b: float) -> float:
        try:
            if price_b == 0:
                return 10000.0
            return abs(price_a - price_b) / price_b * 10000.0
        except Exception:
            return 10000.0

    def _parse_order_fields(self, order: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return {
                "id": order.get("id") or order.get("order_id"),
                "side": (order.get("side") or order.get("order_side") or "").upper(),
                "price": float(order.get("price") or order.get("limit_price") or 0),
                "size": float(order.get("size") or order.get("quantity") or 0),
                "status": (order.get("status") or "").upper(),
            }
        except Exception:
            return {"id": None, "side": "", "price": 0.0, "size": 0.0, "status": ""}

    def _create_lob_from_orderbook(self, orderbook: Dict[str, Any]) -> "SimpleLOB":
        bids = orderbook.get("bids", []) or []
        asks = orderbook.get("asks", []) or []

        def normalize_side(side_list):
            normalized = []
            for entry in side_list:
                try:
                    if isinstance(entry, dict):
                        p = float(entry.get("price", entry.get("0", 0)))
                        q = float(entry.get("quantity", entry.get("size", entry.get("1", 0))))
                    else:
                        p = float(entry[0])
                        q = float(entry[1])
                    normalized.append([p, q])
                except Exception:
                    continue
            return normalized

        return SimpleLOB(normalize_side(bids), normalize_side(asks))

    # ---------------------------
    # Main loop
    # ---------------------------
    async def run(self):
        self._is_running = True
        
        try:
            account_info = await self._fetch_account_info()
            self.logger.info(f"🚀 Trader started for {self.market_symbol}")

            # Setup WebSocket fills for real-time fill detection
            if getattr(self, "hedger", None):
                self.logger.info("🔧 Hedger detected - setting up WebSocket fills")
                try:
                    await self._setup_websocket_fills()
                    # Wait a moment to see if WebSocket subscriptions work
                    await asyncio.sleep(2)
                    if not self._fills_ws or not hasattr(self._fills_ws, '_task') or self._fills_ws._task.done():
                        raise Exception("WebSocket connection failed")
                except Exception as e:
                    self.logger.warning(f"WebSocket setup failed, using polling: {e}")
                    self._fills_ws = None
                    # Fall back to polling-based fill detection
            else:
                self.logger.info("⚠️  No hedger detected - WebSocket fills disabled")

            while self._is_running:
                start_time = asyncio.get_event_loop().time()
                await self._process_tick()
                elapsed_time = asyncio.get_event_loop().time() - start_time
                await asyncio.sleep(max(0, self.refresh_rate_sec - elapsed_time))

        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def _process_tick(self):
        orderbook = await self._get_orderbook()
        self._latest_lob = self._create_lob_from_orderbook(orderbook)

        if self._latest_lob.is_empty():
            await self._cancel_all_orders()
            return
        

        positions = await self._get_positions()
        # Parse actual position data instead of hardcoding to 0
        current_position = 0.0
        account_balance = 0.0  

        # Parse positions to get ETH-USD-PERP position size (in ETH)
        position_list = positions.get("results", []) or positions.get("positions", []) or []
        self.logger.info(f"🔍 DEBUG: Found {len(position_list)} positions")
        
        for position in position_list:
            try:
                if isinstance(position, dict):
                    symbol = position.get("market") or position.get("symbol") or ""
                    size_val = position.get("size") or position.get("amount") or 0
                    self.logger.info(f"🔍 DEBUG: Position - Symbol: {symbol}, Size: {size_val}")
                    
                    if symbol == self.market_symbol:
                        current_position = float(size_val)
                        self.logger.info(f"📊 DEBUG: Found {self.market_symbol} position: {current_position:.4f} ETH")
                        break
            except Exception as e:
                self.logger.error(f"Error parsing position: {e}")
                continue

        # Prefer free collateral from Account Summary (authoritative USD collateral)
        try:
            summary = await self._sdk_fetch_account_summary()
            if summary:
                # summary is a dataclass; attributes are strings
                free_collateral_str = getattr(summary, "free_collateral", None)
                if free_collateral_str is not None:
                    account_balance = float(free_collateral_str)
        except Exception:
            pass

        # Fallback: check balances endpoint for USDC token
        if account_balance == 0.0:
            balances = await self._sdk_fetch_balances()
            balance_list = balances.get("results", []) or []
            for bal in balance_list:
                try:
                    if isinstance(bal, dict):
                        asset = bal.get("asset") or bal.get("symbol") or ""
                        if asset.upper() == "USDC":
                            amount_val = (
                                bal.get("available")
                                or bal.get("free")
                                or bal.get("balance")
                                or bal.get("amount")
                                or 0
                            )
                            account_balance = float(amount_val)
                            break
                except Exception:
                    continue

        quotes = self.strategy.compute_quotes(
                lob_data=self._latest_lob,
                current_position=current_position,
            account_balance=account_balance,
            )

        if quotes:
            buy_orders = quotes.get("buy_orders", [])
            sell_orders = quotes.get("sell_orders", [])
            
            if len(buy_orders) > 0 or len(sell_orders) > 0:
                try:
                    await self._update_quotes_dynamic(buy_orders, sell_orders)
                except Exception as e:
                    self.logger.error(f"Failed to update orders: {e}")
        else:
            await self._cancel_all_orders()

        # WebSocket handles all fill detection and hedging
        # No polling needed when WebSocket is active
        
        # Test hedging removed - only hedge on real fills
        
        # FALLBACK: If WebSocket is not working, use polling
        if not self._fills_ws and getattr(self, "hedger", None) and self._has_placed_orders:
            try:
                await self._poll_for_fills()
            except Exception as e:
                self.logger.error(f"Polling for fills failed: {e}")

    async def _update_quotes_dynamic(self, buy_orders: list, sell_orders: list):
        """Update quotes - cancel old orders (>1min) and place fresh ones."""
        import time
        
        # Check existing orders
        existing_orders = await self._get_orders()
        existing_list = existing_orders.get("orders", []) or existing_orders.get("results", []) or []
        
        current_time = time.time()
        orders_to_cancel = []
        
        # Check if any orders are older than 1 minute
        for order in existing_list:
            try:
                # Parse order timestamp (could be in different formats)
                order_time = None
                if 'created_at' in order:
                    # Try parsing timestamp
                    order_time = float(order['created_at']) / 1000  # Convert ms to seconds
                elif 'updated_at' in order:
                    order_time = float(order['updated_at']) / 1000
                
                if order_time and (current_time - order_time) > 60:  # 60 seconds = 1 minute
                    order_id = order.get('id') or order.get('order_id')
                    if order_id:
                        orders_to_cancel.append(order_id)
            except Exception as e:
                continue
        
        # Cancel old orders
        if orders_to_cancel:
            for order_id in orders_to_cancel:
                await self._cancel_order(order_id)
        
        # Check if we still have orders after canceling old ones
        remaining_orders = await self._get_orders()
        remaining_list = remaining_orders.get("orders", []) or remaining_orders.get("results", []) or []
        
        # Check if we already have the right type of orders
        existing_buy_orders = 0
        existing_sell_orders = 0
        
        for order in remaining_list:
            side = (order.get("side") or order.get("order_side") or "").upper()
            if side == "BUY":
                existing_buy_orders += 1
            elif side == "SELL":
                existing_sell_orders += 1
        
        # Only place orders if we don't already have the right type
        if existing_buy_orders > 0 and buy_orders:
            self.logger.info(f"⏭️  Already have {existing_buy_orders} BUY orders, skipping")
            buy_orders = []
        
        if existing_sell_orders > 0 and sell_orders:
            self.logger.info(f"⏭️  Already have {existing_sell_orders} SELL orders, skipping")
            sell_orders = []

        # Place buy orders
        if buy_orders:
            for order in buy_orders:
                await self._place_order(order["side"], order["size"], order["price"])

        # Place sell orders
        if sell_orders:
            for order in sell_orders:
                await self._place_order(order["side"], order["size"], order["price"])



    async def _hedge_net_position(self) -> None:
        """Hedge the net Paradex position on Hyperliquid."""
        self.logger.info("🔍 _hedge_net_position called")
        if not getattr(self, "hedger", None):
            self.logger.warning("⚠️  No hedger available for hedging")
            return
        
        # No rate limiting needed with WebSocket
        
        # Calculate required hedge
        required_hedge = -self._paradex_position  # Opposite direction
        current_hedge = self._hyperliquid_position
        
        hedge_difference = required_hedge - current_hedge
        
        self.logger.info(f"🔍 DEBUG: Paradex position: {self._paradex_position:.4f}, Hyperliquid position: {self._hyperliquid_position:.4f}")
        self.logger.info(f"🔍 DEBUG: Required hedge: {required_hedge:.4f}, Current hedge: {current_hedge:.4f}, Difference: {hedge_difference:.4f}")
        
        # Only hedge if difference is significant (> 0.001 ETH)
        if abs(hedge_difference) < 0.001:
            self.logger.info(f"⏭️  Hedge difference too small: {hedge_difference:.6f} ETH")
            return
        
        # If Paradex position is 0, reset Hyperliquid position to 0 as well
        if abs(self._paradex_position) < 0.001:
            self.logger.info(f"🔄 Resetting positions: Paradex={self._paradex_position:.4f}, Hyperliquid={self._hyperliquid_position:.4f}")
            self._hyperliquid_position = 0.0
            return
        
        # Determine hedge side and size
        if hedge_difference > 0:
            hedge_side = "BUY"
            hedge_size = hedge_difference
        else:
            hedge_side = "SELL"
            hedge_size = abs(hedge_difference)
        
        self.logger.info(f"🔄 Hedging net position: {hedge_side} {hedge_size:.4f} ETH")
        
        try:
            # Place hedge order - pass the side that represents the Paradex position
            # If we need to SELL on Hyperliquid, it means Paradex is LONG (BUY)
            # If we need to BUY on Hyperliquid, it means Paradex is SHORT (SELL)
            paradex_side = "BUY" if hedge_side == "SELL" else "SELL"
            await self.hedger.on_paradex_fill(
                market=self.market_symbol,
                side=paradex_side,  # Pass the side that represents the Paradex position
                size=hedge_size,
                price=None,  # Market order
                client_id=f"hedge_net_{int(time.time())}",
            )
            
            # Update Hyperliquid position
            if hedge_side == "BUY":
                self._hyperliquid_position += hedge_size
            else:
                self._hyperliquid_position -= hedge_size
            
            # No rate limiting needed
            self.logger.info(f"✅ Net hedge placed: {hedge_side} {hedge_size:.4f} ETH")
            self.logger.info(f"📊 Hyperliquid position: {self._hyperliquid_position:.4f} ETH")
            
        except Exception as e:
            self.logger.error(f"Error placing net hedge: {e}")

    async def _poll_for_fills(self) -> None:
        """Poll for fills when WebSocket is not available."""
        if not self._our_order_ids:
            return
        
        try:
            # Get current orders to check for fills
            orders = await self._get_orders()
            order_list = orders.get("orders", []) or orders.get("results", []) or []
            current_order_ids = {str(order.get("id") or order.get("order_id")) for order in order_list}
            
            # Find filled orders (disappeared from API)
            filled_orders = []
            for order_id in list(self._our_order_ids):
                if order_id not in current_order_ids:
                    # Order disappeared, likely filled
                    filled_orders.append(order_id)
                    self._our_order_ids.discard(order_id)
            
            # Update position based on fills
            if filled_orders:
                self.logger.info(f"📊 POLLING: Found {len(filled_orders)} filled orders: {filled_orders}")
                # Note: We can't determine the exact fill size from polling, so we'll use a small amount
                # In a real implementation, you'd need to track order details
                self._paradex_position += 0.01  # Small position change for testing
                self.logger.info(f"📊 Paradex position: {self._paradex_position:.4f} ETH")
                await self._hedge_net_position()
                
        except Exception as e:
            self.logger.error(f"Error polling for fills: {e}")
        
        # No rate limiting needed with WebSocket
        
        # Calculate required hedge
        required_hedge = -self._paradex_position  # Opposite direction
        current_hedge = self._hyperliquid_position
        
        hedge_difference = required_hedge - current_hedge
        
        self.logger.info(f"🔍 DEBUG: Paradex position: {self._paradex_position:.4f}, Hyperliquid position: {self._hyperliquid_position:.4f}")
        self.logger.info(f"🔍 DEBUG: Required hedge: {required_hedge:.4f}, Current hedge: {current_hedge:.4f}, Difference: {hedge_difference:.4f}")
        
        # Only hedge if difference is significant (> 0.001 ETH)
        if abs(hedge_difference) < 0.001:
            self.logger.info(f"⏭️  Hedge difference too small: {hedge_difference:.6f} ETH")
            return
        
        # If Paradex position is 0, reset Hyperliquid position to 0 as well
        if abs(self._paradex_position) < 0.001:
            self.logger.info(f"🔄 Resetting positions: Paradex={self._paradex_position:.4f}, Hyperliquid={self._hyperliquid_position:.4f}")
            self._hyperliquid_position = 0.0
            return
        
        # Determine hedge side and size
        if hedge_difference > 0:
            hedge_side = "BUY"
            hedge_size = hedge_difference
        else:
            hedge_side = "SELL"
            hedge_size = abs(hedge_difference)
        
        self.logger.info(f"🔄 Hedging net position: {hedge_side} {hedge_size:.4f} ETH")
        
        try:
            # Place hedge order - pass the side that represents the Paradex position
            # If we need to SELL on Hyperliquid, it means Paradex is LONG (BUY)
            # If we need to BUY on Hyperliquid, it means Paradex is SHORT (SELL)
            paradex_side = "BUY" if hedge_side == "SELL" else "SELL"
            await self.hedger.on_paradex_fill(
                market=self.market_symbol,
                side=paradex_side,  # Pass the side that represents the Paradex position
                size=hedge_size,
                price=None,  # Market order
                client_id=f"hedge_net_{int(time.time())}",
            )
            
            # Update Hyperliquid position
            if hedge_side == "BUY":
                self._hyperliquid_position += hedge_size
            else:
                self._hyperliquid_position -= hedge_size
            
            # No rate limiting needed
            self.logger.info(f"✅ Net hedge placed: {hedge_side} {hedge_size:.4f} ETH")
            self.logger.info(f"📊 Hyperliquid position: {self._hyperliquid_position:.4f} ETH")
            
        except Exception as e:
            self.logger.error(f"Error placing net hedge: {e}")

    async def _update_quotes(self, bid_price: float, bid_size: float, ask_price: float, ask_size: float):
        """Legacy method for backward compatibility."""
        self.logger.info(f"🔄 Updating quotes: Canceling existing orders...")
        await self._cancel_all_orders()

        if bid_size > 0:
            self.logger.info(f"📝 Placing BUY order: {bid_size:.3f} @ {bid_price:.2f}")
            await self._place_order("BUY", bid_size, bid_price)
        else:
            self.logger.info("❌ No bid size, skipping BUY order")

        if ask_size > 0:
            self.logger.info(f"📝 Placing SELL order: {ask_size:.3f} @ {ask_price:.2f}")
            await self._place_order("SELL", ask_size, ask_price)
        else:
            self.logger.info("❌ No ask size, skipping SELL order")

    async def stop(self):
        if not self._is_running:
            return
        self._is_running = False
        await self._cancel_all_orders()
        if self._fills_ws:
            try:
                await self._fills_ws.stop()
            except Exception as e:
                self.logger.error(f"Error stopping WebSocket fills: {e}")

class SimpleLOB:
    def __init__(self, bids: list, asks: list):
        self.bids = bids
        self.asks = asks

    def is_empty(self) -> bool:
        return len(self.bids) == 0 and len(self.asks) == 0

    def best_bid(self) -> Optional[list]:
        return self.bids[0] if self.bids else None

    def best_ask(self) -> Optional[list]:
        return self.asks[0] if self.asks else None

    def get_mid(self) -> Optional[float]:
        """Get the mid price between best bid and ask."""
        if self.is_empty():
            return None
        best_bid = self.best_bid()
        best_ask = self.best_ask()
        if best_bid and best_ask:
            return (best_bid[0] + best_ask[0]) / 2
        return None

    def get_vamp(self, reference_notional: float) -> Optional[float]:
        """
        Volume-Adjusted Mid-Price (VAMP) calculation.
        This is a simplified implementation that uses the mid price as VAMP.
        """
        if self.is_empty():
            return None
        
        # For now, use mid price as VAMP (simplified implementation)
        # In a real implementation, you'd calculate volume-weighted average price
        return self.get_mid()
