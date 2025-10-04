from __future__ import annotations

import logging
import time
from typing import Dict, Any, Optional

from .base import HedgeExchange


class OneClickHedger:
    """
    Handles reactive hedging when fills occur on Paradex. Converts
    Paradex fill events into hedge orders on the configured hedge exchange.
    """

    def __init__(
        self,
        hedge: HedgeExchange,
        symbol_map: Dict[str, str],
        *,
        mode: str = "market",
        slippage_bps: float = 10.0,
    ):
        self.hedge = hedge
        self.symbol_map = symbol_map
        self.mode = mode
        self.slippage_bps = slippage_bps
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Rate limiting to prevent excessive orders
        self._last_hedge_time = 0.0
        self._min_hedge_interval = 1.0  # Minimum 1 second between hedge orders

    async def initialize(self) -> None:
        await self.hedge.initialize()

    async def on_paradex_fill(
        self,
        *,
        market: str,
        side: str,
        size: float,
        price: float,
        client_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Rate limiting check
        current_time = time.time()
        if current_time - self._last_hedge_time < self._min_hedge_interval:
            self.logger.warning(f"⏰ Rate limiting: Skipping hedge (last hedge was {current_time - self._last_hedge_time:.1f}s ago)")
            return {"status": "skipped", "reason": "rate_limited"}
        
        # For delta-neutral hedging, we want OPPOSITE sides on both exchanges
        # Paradex BUY → Hyperliquid SELL (long vs short)
        # Paradex SELL → Hyperliquid BUY (short vs long)
        opp_side = "SELL" if side.upper() == "BUY" else "BUY"
        hedge_symbol = self.symbol_map.get(market)
        if not hedge_symbol:
            self.logger.error(f"❌ No symbol mapping for {market}")
            return {"status": "skipped", "reason": "symbol_map_missing", "market": market}
        
        # Debug logging
        self.logger.info(f"🔍 DEBUG: Paradex {side} fill → Hedge {opp_side} order on Hyperliquid")

        hedge_price: Optional[float] = None
        if self.mode == "limit":
            bps = self.slippage_bps / 10_000.0
            hedge_price = price * (1 - bps) if opp_side == "SELL" else price * (1 + bps)

        self.logger.info(f"🔄 Hedging {side} {size} on Paradex → {opp_side} {size} {hedge_symbol} on Hyperliquid @ {'MARKET' if not hedge_price else f'${hedge_price:.2f}'}")
        
        # Update rate limiting timestamp
        self._last_hedge_time = current_time
        
        result = await self.hedge.place_hedge(
            side=opp_side,
            size=size,
            symbol=hedge_symbol,
            price=hedge_price,
            tif="IOC",
            client_id=client_id,
        )
        
        if result.get("status") == "error":
            self.logger.error(f"❌ Hedge failed: {result.get('error')}")
        else:
            self.logger.info(f"✅ Hedge successful: {result}")
        
        return result


