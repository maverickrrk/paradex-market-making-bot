from __future__ import annotations

import abc
from typing import Optional, Dict, Any


class HedgeExchange(abc.ABC):
    """
    Abstract interface for hedge exchanges used to neutralize delta.

    Implementations must be asynchronous and idempotent where possible.
    """

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Initialize client connections, authenticate, and load markets if needed."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_position(self, symbol: str) -> float:
        """Return current position size for the given symbol (base asset units)."""
        raise NotImplementedError

    @abc.abstractmethod
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
        """
        Place a hedge order.

        - side: "BUY" or "SELL"
        - size: base units (e.g., ETH)
        - symbol: exchange-specific symbol (e.g., "ETH/USDT:USDT")
        - price: limit price if provided; market order when None
        - tif: time-in-force hint, defaults to IOC
        - client_id: optional idempotency key
        - extra: pass-through for exchange-specific params
        """
        raise NotImplementedError


