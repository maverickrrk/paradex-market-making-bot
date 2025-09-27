"""
Custom data feed implementation to replace quantpylib Feed.
"""

import asyncio
import logging
from typing import Dict, Any, Callable, Optional, List
import aiohttp
import json

class CustomLOB:
    """
    Custom Limit Order Book implementation.
    Replaces quantpylib LOB functionality.
    """
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: List[Dict[str, float]] = []
        self.asks: List[Dict[str, float]] = []
        self.last_update = None
        
    def is_empty(self) -> bool:
        """Check if order book is empty."""
        return len(self.bids) == 0 and len(self.asks) == 0
        
    def get_mid(self) -> Optional[float]:
        """Get mid price."""
        if self.bids and self.asks:
            best_bid = self.bids[0]["price"]
            best_ask = self.asks[0]["price"]
            return (best_bid + best_ask) / 2
        return None
        
    def get_vamp(self, notional: float) -> Optional[float]:
        """
        Get Volume-Adjusted Mid-Price (VAMP).
        
        Args:
            notional: Target notional value in USD
            
        Returns:
            VAMP price or None if calculation fails
        """
        try:
            if not self.bids or not self.asks:
                return self.get_mid()
                
            # Simple VAMP calculation based on available liquidity
            total_bid_volume = sum(bid["size"] * bid["price"] for bid in self.bids[:5])
            total_ask_volume = sum(ask["size"] * ask["price"] for ask in self.asks[:5])
            
            if total_bid_volume >= notional and total_ask_volume >= notional:
                # Calculate weighted average price
                bid_weighted_price = sum(bid["size"] * bid["price"] for bid in self.bids[:3]) / sum(bid["size"] for bid in self.bids[:3])
                ask_weighted_price = sum(ask["size"] * ask["price"] for ask in self.asks[:3]) / sum(ask["size"] for ask in self.asks[:3])
                return (bid_weighted_price + ask_weighted_price) / 2
            else:
                # Fallback to mid price
                return self.get_mid()
                
        except Exception as e:
            logging.getLogger("CustomLOB").error(f"Error calculating VAMP: {e}")
            return self.get_mid()
            
    def update(self, orderbook_data: Dict[str, Any]):
        """Update order book with new data."""
        try:
            if "bids" in orderbook_data:
                self.bids = sorted(
                    [{"price": float(bid[0]), "size": float(bid[1])} for bid in orderbook_data["bids"]],
                    key=lambda x: x["price"],
                    reverse=True
                )
                
            if "asks" in orderbook_data:
                self.asks = sorted(
                    [{"price": float(ask[0]), "size": float(ask[1])} for ask in orderbook_data["asks"]],
                    key=lambda x: x["price"]
                )
                
            self.last_update = asyncio.get_event_loop().time()
            
        except Exception as e:
            logging.getLogger("CustomLOB").error(f"Error updating order book: {e}")

class CustomFeed:
    """
    Custom data feed implementation.
    Replaces quantpylib Feed functionality.
    """
    
    def __init__(self, gateway):
        """
        Initialize the custom feed.
        
        Args:
            gateway: CustomGateway instance
        """
        self.gateway = gateway
        self.logger = logging.getLogger("CustomFeed")
        self.lob_handlers: Dict[str, Callable] = {}
        self.lob_data: Dict[str, CustomLOB] = {}
        self.running = False
        
    async def add_l2_book_feed(self, exc: str, ticker: str, handler: Callable, 
                              depth: int = 20) -> bool:
        """
        Add L2 order book feed.
        
        Args:
            exc: Exchange name (ignored)
            ticker: Trading pair symbol
            handler: Callback function for order book updates
            depth: Order book depth (ignored for now)
            
        Returns:
            True if successful
        """
        try:
            self.lob_handlers[ticker] = handler
            self.lob_data[ticker] = CustomLOB(ticker)
            
            # Start order book polling
            asyncio.create_task(self._poll_orderbook(ticker))
            
            self.logger.info(f"Added L2 order book feed for {ticker}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error adding L2 book feed for {ticker}: {e}")
            return False
            
    async def _poll_orderbook(self, ticker: str):
        """Poll order book data for a ticker."""
        while self.running:
            try:
                # Get order book data from exchange
                orderbook_data = await self.gateway.get_orderbook(ticker)
                
                if orderbook_data and "bids" in orderbook_data and "asks" in orderbook_data:
                    # Update LOB data
                    if ticker in self.lob_data:
                        self.lob_data[ticker].update(orderbook_data)
                        
                        # Call handler
                        if ticker in self.lob_handlers:
                            await self.lob_handlers[ticker](self.lob_data[ticker])
                        
                # Wait before next poll
                await asyncio.sleep(1.0)  # Poll every second
                
            except Exception as e:
                self.logger.error(f"Error polling orderbook for {ticker}: {e}")
                await asyncio.sleep(5.0)  # Wait longer on error
                
    def start(self):
        """Start the feed."""
        self.running = True
        self.logger.info("Custom feed started")
        
    def stop(self):
        """Stop the feed."""
        self.running = False
        self.logger.info("Custom feed stopped")
