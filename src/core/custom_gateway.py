"""
Custom Gateway implementation to replace quantpylib Gateway.
This avoids Windows C++ library issues by using direct API calls.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
import aiohttp
import json
from datetime import datetime

class CustomGateway:
    """
    Custom gateway that directly interfaces with Paradex API.
    Replaces quantpylib Gateway functionality.
    """
    
    def __init__(self, config_keys: Dict[str, Dict[str, str]]):
        """
        Initialize the custom gateway.
        
        Args:
            config_keys: Dictionary containing API credentials
        """
        self.config = config_keys
        self.paradex_config = config_keys.get("paradex", {})
        self.api_key = self.paradex_config.get("key")
        self.private_key = self.paradex_config.get("secret")
        
        self.logger = logging.getLogger("CustomGateway")
        self.session: Optional[aiohttp.ClientSession] = None
        
        # API endpoints
        self.base_url = "https://api.testnet.paradex.trade"  # testnet
        # self.base_url = "https://api.paradex.trade"  # mainnet
        
    async def init_clients(self):
        """Initialize HTTP client session."""
        self.session = aiohttp.ClientSession(
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        )
        self.logger.info("Custom gateway HTTP client initialized")
        
    async def cleanup_clients(self):
        """Clean up HTTP client session."""
        if self.session:
            await self.session.close()
            self.logger.info("Custom gateway HTTP client cleaned up")
            
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information."""
        try:
            async with self.session.get(f"{self.base_url}/v1/account") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.logger.error(f"Failed to get account info: {response.status}")
                    return {}
        except Exception as e:
            self.logger.error(f"Error getting account info: {e}")
            return {}
            
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions."""
        try:
            async with self.session.get(f"{self.base_url}/v1/positions") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.logger.error(f"Failed to get positions: {response.status}")
                    return {}
        except Exception as e:
            self.logger.error(f"Error getting positions: {e}")
            return {}
            
    async def get_orders(self) -> Dict[str, Any]:
        """Get current orders."""
        try:
            async with self.session.get(f"{self.base_url}/v1/orders") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.logger.error(f"Failed to get orders: {response.status}")
                    return {}
        except Exception as e:
            self.logger.error(f"Error getting orders: {e}")
            return {}
            
    async def place_order(self, symbol: str, side: str, amount: float, price: float, 
                         order_type: str = "limit") -> Dict[str, Any]:
        """Place an order."""
        try:
            order_data = {
                "symbol": symbol,
                "side": side,
                "amount": str(amount),
                "price": str(price),
                "type": order_type
            }
            
            async with self.session.post(f"{self.base_url}/v1/orders", 
                                       json=order_data) as response:
                if response.status == 200:
                    result = await response.json()
                    self.logger.info(f"Order placed: {result}")
                    return result
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to place order: {response.status} - {error_text}")
                    return {}
        except Exception as e:
            self.logger.error(f"Error placing order: {e}")
            return {}
            
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            async with self.session.delete(f"{self.base_url}/v1/orders/{order_id}") as response:
                if response.status == 200:
                    self.logger.info(f"Order {order_id} cancelled")
                    return True
                else:
                    self.logger.error(f"Failed to cancel order {order_id}: {response.status}")
                    return False
        except Exception as e:
            self.logger.error(f"Error cancelling order {order_id}: {e}")
            return False
            
    async def get_orderbook(self, symbol: str) -> Dict[str, Any]:
        """Get order book for a symbol."""
        try:
            async with self.session.get(f"{self.base_url}/v1/orderbook/{symbol}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.logger.error(f"Failed to get orderbook for {symbol}: {response.status}")
                    return {}
        except Exception as e:
            self.logger.error(f"Error getting orderbook for {symbol}: {e}")
            return {}
