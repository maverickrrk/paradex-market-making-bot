"""
Custom Order Management System (OMS) to replace quantpylib OMS.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

class Order:
    """Simple order representation."""
    
    def __init__(self, order_id: str, symbol: str, side: str, amount: float, 
                 price: float, status: str = "open"):
        self.order_id = order_id
        self.cloid = order_id  # Client order ID (same as order_id for simplicity)
        self.symbol = symbol
        self.side = side
        self.amount = amount
        self.price = price
        self.status = status
        self.created_at = datetime.now()
        
    def is_buy(self) -> bool:
        return self.side.lower() == "buy"
        
    def is_sell(self) -> bool:
        return self.side.lower() == "sell"
        
    def __repr__(self):
        return f"Order({self.symbol}, {self.side}, {self.amount} @ {self.price})"

class Position:
    """Simple position representation."""
    
    def __init__(self, symbol: str, amount: float = 0.0):
        self.symbol = symbol
        self.amount = amount
        
    def get_ticker_amount(self, ticker: str) -> float:
        if ticker == self.symbol:
            return self.amount
        return 0.0

class CustomOMS:
    """
    Custom Order Management System.
    Replaces quantpylib OMS functionality.
    """
    
    def __init__(self, gateway):
        """
        Initialize the custom OMS.
        
        Args:
            gateway: CustomGateway instance
        """
        self.gateway = gateway
        self.logger = logging.getLogger("CustomOMS")
        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
        
    async def init(self):
        """Initialize the OMS."""
        self.logger.info("Custom OMS initialized")
        
        # Load initial positions
        await self._load_positions()
        
    async def _load_positions(self):
        """Load current positions from exchange."""
        try:
            positions_data = await self.gateway.get_positions()
            if positions_data:
                for pos in positions_data.get("positions", []):
                    symbol = pos.get("symbol")
                    amount = float(pos.get("amount", 0))
                    self.positions[symbol] = Position(symbol, amount)
                    self.logger.info(f"Loaded position: {symbol} = {amount}")
        except Exception as e:
            self.logger.error(f"Error loading positions: {e}")
            
    async def limit_order(self, exc: str, ticker: str, amount: float, 
                         price: float, post_only: bool = True) -> Optional[str]:
        """
        Place a limit order.
        
        Args:
            exc: Exchange name (ignored for custom implementation)
            ticker: Trading pair symbol
            amount: Order amount
            price: Order price
            post_only: Whether to use post-only flag
            
        Returns:
            Order ID if successful, None otherwise
        """
        try:
            side = "buy" if amount > 0 else "sell"
            abs_amount = abs(amount)
            
            order_data = await self.gateway.place_order(
                symbol=ticker,
                side=side,
                amount=abs_amount,
                price=price,
                order_type="limit"
            )
            
            if order_data and "id" in order_data:
                order_id = order_data["id"]
                order = Order(
                    order_id=order_id,
                    symbol=ticker,
                    side=side,
                    amount=abs_amount,
                    price=price
                )
                self.orders[order_id] = order
                self.logger.info(f"Order placed: {order}")
                return order_id
            else:
                self.logger.error(f"Failed to place order: {order_data}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error placing limit order: {e}")
            return None
            
    async def cancel_order(self, exc: str, ticker: str, cloid: str) -> bool:
        """
        Cancel an order.
        
        Args:
            exc: Exchange name (ignored)
            ticker: Trading pair symbol (ignored)
            cloid: Order ID to cancel
            
        Returns:
            True if successful, False otherwise
        """
        try:
            success = await self.gateway.cancel_order(cloid)
            if success and cloid in self.orders:
                self.orders[cloid].status = "cancelled"
                self.logger.info(f"Order {cloid} cancelled")
            return success
        except Exception as e:
            self.logger.error(f"Error cancelling order {cloid}: {e}")
            return False
            
    async def cancel_all_orders(self, exc: str, ticker: str) -> bool:
        """
        Cancel all orders for a ticker.
        
        Args:
            exc: Exchange name (ignored)
            ticker: Trading pair symbol
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cancelled_count = 0
            for order_id, order in list(self.orders.items()):
                if order.symbol == ticker and order.status == "open":
                    success = await self.cancel_order(exc, ticker, order_id)
                    if success:
                        cancelled_count += 1
                        
            self.logger.info(f"Cancelled {cancelled_count} orders for {ticker}")
            return cancelled_count > 0
        except Exception as e:
            self.logger.error(f"Error cancelling all orders for {ticker}: {e}")
            return False
            
    def orders_peek(self, exc: str) -> 'OrderManager':
        """Get order manager for peeking at orders."""
        return OrderManager(self.orders)
        
    def positions_peek(self, exc: str) -> 'PositionManager':
        """Get position manager for peeking at positions."""
        return PositionManager(self.positions)

class OrderManager:
    """Helper class for managing orders."""
    
    def __init__(self, orders: Dict[str, Order]):
        self.orders = orders
        
    def get_all_orders(self) -> List[Order]:
        """Get all orders."""
        return list(self.orders.values())
        
    def get_orders(self, ticker: str = None) -> List[Order]:
        """Get orders, optionally filtered by ticker."""
        if ticker:
            return [order for order in self.orders.values() if order.symbol == ticker]
        return list(self.orders.values())
        
    def get_orders_by_symbol(self, symbol: str) -> List[Order]:
        """Get orders for a specific symbol."""
        return [order for order in self.orders.values() if order.symbol == symbol]

class PositionManager:
    """Helper class for managing positions."""
    
    def __init__(self, positions: Dict[str, Position]):
        self.positions = positions
        
    def get_ticker_amount(self, ticker: str) -> float:
        """Get position amount for a ticker."""
        if ticker in self.positions:
            return self.positions[ticker].amount
        return 0.0
