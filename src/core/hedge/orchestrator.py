from __future__ import annotations

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
        opp_side = "SELL" if side.upper() == "BUY" else "BUY"
        hedge_symbol = self.symbol_map.get(market)
        if not hedge_symbol:
            return {"status": "skipped", "reason": "symbol_map_missing", "market": market}

        hedge_price: Optional[float] = None
        if self.mode == "limit":
            bps = self.slippage_bps / 10_000.0
            hedge_price = price * (1 - bps) if opp_side == "SELL" else price * (1 + bps)

        return await self.hedge.place_hedge(
            side=opp_side,
            size=size,
            symbol=hedge_symbol,
            price=hedge_price,
            tif="IOC",
            client_id=client_id,
        )


