from __future__ import annotations

import asyncio
import logging
from typing import Optional, Dict, Any
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from eth_account import Account

from .base import HedgeExchange


class HyperliquidHedge(HedgeExchange):
    """
    Hyperliquid exchange adapter for delta-neutral hedging.

    Uses the official Hyperliquid Python SDK for order placement and position management.
    """

    def __init__(self, private_key: str, public_address: str, base_url: Optional[str] = None, order_endpoint: str = "/exchange"):
        # Create eth_account wallet from private key for signing
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        self.private_key = private_key
        self.public_address = public_address
        self._initialized = False
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Initialize Hyperliquid SDK clients
        try:
            # Create wallet object from private key for signing
            self.wallet = Account.from_key(self.private_key)
            
            # Initialize Exchange with the wallet object (not string)
            self.exchange = Exchange(
                wallet=self.wallet,  # Pass the Account object, not address string
                base_url=base_url,
                account_address=self.public_address
            )
            self.info = Info(base_url=base_url)
            self.logger.info(f"Hyperliquid SDK initialized for address: {self.public_address}")
        except Exception as e:
            self.logger.error(f"Failed to initialize Hyperliquid SDK: {e}")
            raise

    async def initialize(self) -> None:
        self._initialized = True
        self.logger.info("Hyperliquid adapter ready")

    async def get_position(self, symbol: str) -> float:
        """Get current position for the given symbol."""
        try:
            # Convert symbol to Hyperliquid format
            hyperliquid_symbol = self._convert_symbol(symbol)
            
            # Get user state using SDK
            user_state = await asyncio.to_thread(
                self.info.user_state,
                self.public_address
            )
            
            # Find position for the symbol
            if user_state and "assetPositions" in user_state:
                for asset_pos in user_state["assetPositions"]:
                    position = asset_pos.get("position", {})
                    if position.get("coin") == hyperliquid_symbol:
                        return float(position.get("szi", 0))
            return 0.0
        except Exception as e:
            self.logger.warning(f"Failed to get position for {symbol}: {e}")
            return 0.0

    async def place_hedge(
        self,
        *,
        side: str,
        size: float,
        symbol: str,
        price: Optional[float] = None,
        tif: str = "IOC",
        client_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            # Convert symbol to Hyperliquid format
            hyperliquid_symbol = self._convert_symbol(symbol)
            
            # Determine if this is a buy or sell
            is_buy = side.upper() == "BUY"
            
            self.logger.info(f"🔍 DEBUG: Hyperliquid order - side={side}, is_buy={is_buy}, will create {'LONG' if is_buy else 'SHORT'} position")
            
            # Place order using SDK
            # Market order if no price specified
            if price is None:
                self.logger.info(f"Placing MARKET {side} order: {size} {hyperliquid_symbol}")
                # market_open(coin, is_buy, sz, px=None, slippage=0.05, cloid=None)
                # Note: cloid must be None or a Cloid object, not a string - omitting it
                result = await asyncio.to_thread(
                    self.exchange.market_open,
                    hyperliquid_symbol,  # coin
                    is_buy,              # is_buy
                    size,                # sz
                    None,                # px (None for market)
                    0.05                 # slippage (5% default)
                    # cloid omitted - SDK will handle it
                )
            else:
                # Limit order
                self.logger.info(f"Placing LIMIT {side} order: {size} {hyperliquid_symbol} @ {price}")
                order_type = {"limit": {"tif": tif}}
                # Note: cloid must be None or a Cloid object, not a string - omitting it
                result = await asyncio.to_thread(
                    self.exchange.order,
                    hyperliquid_symbol,
                    is_buy,
                    size,
                    price,
                    order_type,
                    None  # reduce_only
                    # cloid omitted - SDK will handle it
                )
            
            self.logger.info(f"Hyperliquid order result: {result}")
            
            # Parse response
            if result and result.get("status") == "ok":
                # Check if the order was actually filled or just accepted
                response_data = result.get("response", {})
                if response_data.get("type") == "order":
                    order_data = response_data.get("data", {})
                    statuses = order_data.get("statuses", [])
                    if statuses and len(statuses) > 0:
                        status = statuses[0]
                        if "filled" in status:
                            self.logger.info(f"✅ Hyperliquid order FILLED: {side} {size} {symbol}")
                        elif "error" in status:
                            error_msg = status["error"]
                            self.logger.error(f"❌ Hyperliquid order ERROR: {error_msg}")
                            return {
                                "status": "rejected",
                                "error": error_msg,
                                "side": side,
                                "size": size,
                                "symbol": symbol,
                                "price": price,
                                "client_id": client_id,
                                "raw": result
                            }
                        else:
                            self.logger.info(f"✅ Hyperliquid order ACCEPTED: {side} {size} {symbol}")
                    else:
                        self.logger.info(f"✅ Hyperliquid order ACCEPTED: {side} {size} {symbol}")
                else:
                    self.logger.info(f"✅ Hyperliquid order ACCEPTED: {side} {size} {symbol}")
                
                return {
                    "status": "accepted",
                    "side": side,
                    "size": size,
                    "symbol": symbol,
                    "price": price,
                    "client_id": client_id,
                    "raw": result
                }
            else:
                error_msg = result.get("response", "Unknown error") if result else "No response"
                self.logger.error(f"❌ Hyperliquid order REJECTED: {error_msg}")
                return {
                    "status": "rejected",
                    "error": error_msg,
                    "side": side,
                    "size": size,
                    "symbol": symbol,
                    "price": price,
                    "client_id": client_id,
                    "raw": result
                }
        except Exception as e:
            self.logger.error(f"❌ Hyperliquid order failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "side": side,
                "size": size,
                "symbol": symbol,
                "price": price,
                "client_id": client_id
            }

    async def cancel_order(self, order_id: str) -> None:
        """Cancels an order on the hedge exchange."""
        try:
            result = await asyncio.to_thread(
                self.exchange.cancel,
                order_id
            )
            self.logger.info(f"Cancelled order {order_id}: {result}")
        except Exception as e:
            self.logger.error(f"Failed to cancel order {order_id}: {e}")

    async def cleanup(self) -> None:
        """Cleans up resources."""
        self.logger.info("Hyperliquid adapter cleanup complete")

    def _convert_symbol(self, symbol: str) -> str:
        """Convert Paradex symbol format to Hyperliquid format."""
        # Example: ETH-USD-PERP -> ETH
        if "-" in symbol:
            return symbol.split("-")[0]
        return symbol
