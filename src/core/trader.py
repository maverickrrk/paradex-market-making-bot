import asyncio
import logging
from typing import Dict, Any, Optional
from decimal import Decimal

from paradex_py import Paradex
from paradex_py.common.order import Order, OrderSide, OrderType

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
        self._main_task: Optional[asyncio.Task] = None
        self._latest_lob: Optional["SimpleLOB"] = None
        
        # Sequential trading state tracking
        self._trading_state = "IDLE"  # IDLE, WAITING_FOR_BUY, WAITING_FOR_SELL
        self._current_buy_order_id: Optional[str] = None
        self._current_sell_order_id: Optional[str] = None
        self._last_order_side: Optional[str] = None
        # Track last known open orders per side
        self._open_orders_cache: Dict[str, list] = {"BUY": [], "SELL": []}

    # ---------------------------
    # SDK wrapper helpers (sync -> async)
    # ---------------------------
    async def _fetch_account_info(self) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self.gateway.api_client.fetch_account_info)
        except Exception as e:
            return {}

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
            return await asyncio.to_thread(
                self.gateway.api_client.fetch_orders, params={"market": self.market_symbol}
            )
        except Exception as e:
            return {"orders": []}

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
            self.logger.error(f"Order placement error: {e}")
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
        # Log order details before placing
        notional_value = amount * price
        self.logger.info(f"💰 Order notional: ${notional_value:.2f} (${amount:.4f} ETH @ ${price:.2f})")
        
        result = await self._sdk_place_order(side, amount, price)
        if result:
            self.logger.info(f"✅ {side} order SUCCESS: {amount} @ {price:.2f}")
            if isinstance(result, dict):
                order_id = result.get("id") or result.get("order_id") or str(result)
                self.logger.info(f"🆔 Order ID: {order_id}")
                return order_id
            return str(result)
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
        self.logger.info("🔄 Processing tick...")
        orderbook = await self._get_orderbook()
        self._latest_lob = self._create_lob_from_orderbook(orderbook)

        if self._latest_lob.is_empty():
            self.logger.warning("📊 Orderbook is empty")
            await self._cancel_all_orders()
            return
        

        positions = await self._get_positions()
        # Parse actual position data instead of hardcoding to 0
        current_position = 0.0
        account_balance = 0.0  

        # Parse positions to get ETH-USD-PERP position size (in ETH)
        position_list = positions.get("results", []) or positions.get("positions", []) or []
        for position in position_list:
            try:
                if isinstance(position, dict):
                    symbol = position.get("market") or position.get("symbol") or ""
                    if symbol == self.market_symbol:
                        size_val = position.get("size") or position.get("amount") or 0
                        current_position = float(size_val)
                        break
            except Exception:
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

        self.logger.info(f"💰 Position: {current_position:.4f} ETH, Balance: ${account_balance:.2f} USDC")

        quotes = self.strategy.compute_quotes(
                lob_data=self._latest_lob,
                current_position=current_position,
            account_balance=account_balance,
            )

        if quotes:
            buy_orders = quotes.get("buy_orders", [])
            sell_orders = quotes.get("sell_orders", [])
            vamp_price = quotes.get("vamp_price", 0)
            
            self.logger.info(f"🎯 Strategy generated {len(buy_orders)} buy orders and {len(sell_orders)} sell orders")
            self.logger.info(f"📈 VAMP Price: ${vamp_price:.2f}")
            
            await self._update_quotes_dynamic(buy_orders, sell_orders)
            self.logger.info("✅ Orders updated successfully")
        else:
            self.logger.info("❌ No quotes generated by strategy")
            await self._cancel_all_orders()

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
                        self.logger.info(f"⏰ Order {order_id} is older than 1min, marking for cancel")
            except Exception as e:
                continue
        
        # Cancel old orders
        if orders_to_cancel:
            self.logger.info(f"🗑️ Canceling {len(orders_to_cancel)} old orders...")
            for order_id in orders_to_cancel:
                await self._cancel_order(order_id)
        
        # Check if we still have orders after canceling old ones
        remaining_orders = await self._get_orders()
        remaining_list = remaining_orders.get("orders", []) or remaining_orders.get("results", []) or []
        
        if remaining_list:
            self.logger.info("📊 Fresh orders still exist, skipping placement")
            return

        # Place buy orders
        if buy_orders:
            self.logger.info(f"📝 Placing {len(buy_orders)} BUY orders...")
            for i, order in enumerate(buy_orders):
                self.logger.info(f"   BUY #{i+1}: {order['size']:.4f} @ ${order['price']:.2f} (${order['notional']:.2f})")
                await self._place_order(order["side"], order["size"], order["price"])
        else:
            self.logger.info("❌ No buy orders to place")

        # Place sell orders
        if sell_orders:
            self.logger.info(f"📝 Placing {len(sell_orders)} SELL orders...")
            for i, order in enumerate(sell_orders):
                self.logger.info(f"   SELL #{i+1}: {order['size']:.4f} @ ${order['price']:.2f} (${order['notional']:.2f})")
                await self._place_order(order["side"], order["size"], order["price"])
        else:
            self.logger.info("❌ No sell orders to place")

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

    # Add this method for VampMM compatibility
    def get_vamp(self, reference_notional: float) -> float:
        """
        Dummy implementation: compute some "vamp" price based on the LOB.
        You should implement the real logic according to your strategy.
        """
        if self.is_empty():
            return 0.0
        mid_price = 0.0
        best_bid = self.best_bid()
        best_ask = self.best_ask()
        if best_bid and best_ask:
            mid_price = (best_bid[0] + best_ask[0]) / 2
        return mid_price  # or apply your actual VampMM formula here
