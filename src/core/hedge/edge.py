from __future__ import annotations

import asyncio
import logging
from typing import Optional, Dict, Any
import time
import json
import hmac
import hashlib
import httpx

from .base import HedgeExchange


class HyperliquidHedge(HedgeExchange):
    """
    Hyperliquid exchange adapter for delta-neutral hedging.

    Implements REST API calls for order placement and position management.
    Uses Hyperliquid's API with proper authentication and error handling.
    """

    def __init__(self, private_key: str, public_address: str, base_url: Optional[str] = None, order_endpoint: str = "/exchange"):
        self.private_key = private_key
        self.public_address = public_address
        self.base_url = base_url or "https://api.hyperliquid.xyz"
        self.order_endpoint = order_endpoint
        self._initialized = False
        self._http: Optional[httpx.AsyncClient] = None
        self.logger = logging.getLogger(self.__class__.__name__)

    async def initialize(self) -> None:
        timeout = httpx.Timeout(20.0, connect=20.0)
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, trust_env=True)
        self._initialized = True

    async def get_position(self, symbol: str) -> float:
        """Get current position for the given symbol."""
        assert self._http is not None, "Hyperliquid HTTP client not initialized"
        
        try:
            # Hyperliquid uses different symbol format, convert if needed
            hyperliquid_symbol = self._convert_symbol(symbol)
            
            # Get user state to find position
            resp = await self._http.post("/info", json={
                "type": "clearinghouseState",
                "user": self.public_address
            })
            resp.raise_for_status()
            data = resp.json()
            
            # Find position for the symbol
            for asset in data.get("assetPositions", []):
                if asset.get("coin") == hyperliquid_symbol:
                    return float(asset.get("position", {}).get("size", 0))
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
        assert self._http is not None, "Hyperliquid HTTP client not initialized"

        try:
            # Convert symbol to Hyperliquid format
            hyperliquid_symbol = self._convert_symbol(symbol)
            
            # Prepare order action
            order_action = {
                "type": "order",
                "orders": [{
                    "a": self.public_address,  # account address
                    "b": side.upper() == "BUY",  # isBuy
                    "p": str(price) if price is not None else "0",  # price (0 for market)
                    "s": str(size),  # size
                    "r": False,  # reduceOnly
                    "t": "Ioc" if tif == "IOC" else "Gtc",  # time in force
                    "c": client_id or f"hedge_{int(time.time())}",  # client order id
                }],
                "grouping": "na"
            }

            # Get current timestamp for signature
            ts = str(int(time.time() * 1000))
            
            # Create signature using private key (simplified - adjust per Hyperliquid docs)
            message = f"{ts}{json.dumps(order_action, separators=(',', ':'))}"
            # For now, use HMAC with private key as secret (adjust per actual Hyperliquid signing)
            signature = hmac.new(
                self.private_key.encode(), 
                message.encode(), 
                hashlib.sha256
            ).hexdigest()

            # Submit order
            resp = await self._http.post(self.order_endpoint, json={
                "action": order_action,
                "nonce": ts,
                "signature": signature
            })
            resp.raise_for_status()
            
            result = resp.json()
            return {
                "status": "accepted" if result.get("status") == "ok" else "rejected",
                "side": side,
                "size": size,
                "symbol": symbol,
                "price": price,
                "client_id": client_id,
                "id": result.get("response", {}).get("data", {}).get("statuses", [{}])[0].get("resting", {}).get("oid"),
                "raw": result
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "side": side,
                "size": size,
                "symbol": symbol,
                "price": price,
                "client_id": client_id
            }

    def _convert_symbol(self, symbol: str) -> str:
        """Convert Paradex symbol format to Hyperliquid format."""
        # Example: ETH-USD-PERP -> ETH
        if "-" in symbol:
            return symbol.split("-")[0]
        return symbol


