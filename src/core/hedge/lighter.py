from __future__ import annotations

import asyncio
import logging
from typing import Optional, Dict, Any

try:
    import lighter
    from eth_account import Account
    LIGHTER_SDK_AVAILABLE = True
except ImportError:
    LIGHTER_SDK_AVAILABLE = False

from .base import HedgeExchange


class LighterHedge(HedgeExchange):
    """
    Lighter exchange adapter for delta-neutral hedging.
    
    Uses the official Lighter Python SDK for order placement and position management.
    """

    def __init__(
        self, 
        private_key: str, 
        public_address: str,
        base_url: Optional[str] = None,
        is_testnet: bool = False
    ):
        """
        Initialize Lighter hedge client.
        
        Args:
            private_key: Ethereum private key (with or without 0x prefix)
            public_address: Ethereum address
            base_url: API base URL (defaults to mainnet)
            is_testnet: Whether to use testnet
        """
        if not LIGHTER_SDK_AVAILABLE:
            raise ImportError("Lighter SDK is not installed. Please run 'pip install git+https://github.com/elliottech/lighter-python.git'")

        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        self.private_key = private_key
        self.public_address = public_address
        self.base_url = base_url or "https://mainnet.zklighter.elliot.ai"
        self.is_testnet = is_testnet
        self._initialized = False
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.signer_client: Optional[lighter.SignerClient] = None
        self.account_api: Optional[lighter.AccountApi] = None
        self.order_api: Optional[lighter.OrderApi] = None
        self.market_details: Dict[str, Any] = {}
        self.account_index: Optional[int] = None
        # Per Lighter docs, API key index 2 is the first available for users
        self.api_key_index = 2

    async def initialize(self) -> None:
        """Initialize Lighter SDK, fetch account index, and load market data."""
        try:
            # Initialize API clients
            api_client = lighter.ApiClient()
            api_client.configuration.host = self.base_url
            
            self.account_api = lighter.AccountApi(api_client)
            self.order_api = lighter.OrderApi(api_client)

            # Fetch account index
            self.logger.info(f"Fetching Lighter account index for {self.public_address}...")
            account_data = await self.account_api.accounts_by_l1_address(
                lighter.ReqGetAccountByL1Address(l1_address=self.public_address)
            )
            if not hasattr(account_data, 'sub_accounts') or not account_data.sub_accounts:
                raise ValueError("Could not find Lighter account. Please ensure it is created on the exchange.")
            
            # The main account is the first in the sub_accounts list
            self.account_index = account_data.sub_accounts[0].index
            self.logger.info(f"Lighter Account Index found: {self.account_index}")

            # Initialize SignerClient for placing orders
            self.signer_client = lighter.SignerClient(
                url=self.base_url,
                private_key=self.private_key,
                account_index=self.account_index,
                api_key_index=self.api_key_index
            )

            # Load and cache market details
            await self._load_market_details()
            
            self._initialized = True
            self.logger.info(f"✅ Lighter SDK initialized for address: {self.public_address}")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Lighter SDK: {e}", exc_info=True)
            raise

    async def _load_market_details(self):
        """Fetches and caches details for all available markets."""
        self.logger.info("Loading Lighter market details...")
        order_books = await self.order_api.order_books()
        if hasattr(order_books, 'order_books'):
            for ob in order_books.order_books:
                # Use the correct symbol from the user's list (e.g., 'DOGE', not 'DOGE-USDC')
                market_symbol = ob.market_symbol.split('-')[0]
                self.market_details[market_symbol] = {
                    "market_index": ob.market_index,
                    "base_decimals": ob.base_asset_decimal,
                    "quote_decimals": ob.quote_asset_decimal,
                }
        self.logger.info(f"Loaded details for {len(self.market_details)} Lighter markets.")

    async def get_position(self, symbol: str) -> float:
        """Get current position for the given symbol."""
        if not self._initialized:
            raise RuntimeError("LighterHedge not initialized.")
        try:
            lighter_symbol = self._convert_symbol(symbol)
            
            account_data = await self.account_api.accounts_by_l1_address(
                lighter.ReqGetAccountByL1Address(l1_address=self.public_address)
            )
            
            if hasattr(account_data, 'sub_accounts') and account_data.sub_accounts:
                main_account = account_data.sub_accounts[0]
                if hasattr(main_account, 'positions'):
                    for position in main_account.positions:
                        # Match just the base symbol (e.g., 'DOGE')
                        if position.market_symbol.split('-')[0] == lighter_symbol:
                            return float(position.size or 0)
            return 0.0
        except Exception as e:
            self.logger.warning(f"Failed to get Lighter position for {symbol}: {e}")
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
        """Place a hedge order on Lighter."""
        if not self._initialized or not self.signer_client:
            raise RuntimeError("LighterHedge not initialized.")
            
        lighter_symbol = self._convert_symbol(symbol)
        is_buy = side.upper() == "BUY"
        is_ask = not is_buy

        if lighter_symbol not in self.market_details:
            # If the direct symbol isn't found, try reloading markets just in case
            await self._load_market_details()
            if lighter_symbol not in self.market_details:
                self.logger.error(f"❌ Unknown Lighter symbol: {lighter_symbol}. Cannot place hedge.")
                return {"status": "rejected", "error": f"Unknown symbol {lighter_symbol}"}

        market_info = self.market_details[lighter_symbol]
        market_index = market_info["market_index"]
        base_decimals = market_info["base_decimals"]

        try:
            # Convert float size to integer representation required by Lighter SDK
            base_amount = int(size * (10**base_decimals))
            
            self.logger.info(
                f"Placing Lighter {'MARKET' if price is None else 'LIMIT'} {side} order: "
                f"{size} {lighter_symbol} (int amount: {base_amount})"
            )

            # Use the SignerClient's wrapper functions to sign and send the transaction
            if price is None:
                # Use Immediate-or-Cancel for market orders to avoid hanging orders
                time_in_force = lighter.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL
                result = await self.signer_client.create_market_order(
                    market_index=market_index,
                    is_ask=is_ask,
                    base_amount=base_amount,
                    time_in_force=time_in_force
                )
            else:
                # Limit order logic would go here if needed
                self.logger.warning("Lighter limit orders not fully implemented for hedging, using market order.")
                return {"status": "rejected", "error": "Limit orders not supported in this implementation"}

            self.logger.info(f"Lighter order submission result: {result}")
            
            # The SDK's response is typically just a confirmation of submission.
            # We assume it's accepted if no exception was thrown.
            return {
                "status": "accepted",
                "side": side,
                "size": size,
                "symbol": lighter_symbol,
                "price": price,
                "client_id": client_id,
                "raw": str(result)
            }
            
        except Exception as e:
            self.logger.error(f"❌ Lighter order failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "side": side,
                "size": size,
                "symbol": symbol,
                "price": price,
                "client_id": client_id
            }

    async def cleanup(self) -> None:
        """Clean up resources."""
        # The SDK does not have an explicit close method on the client
        self.logger.info("Lighter adapter cleanup complete.")

    def _convert_symbol(self, symbol: str) -> str:
        """
        Convert symbol format (e.g., Paradex 'DOGE-USD-PERP') to Lighter format ('DOGE').
        """
        if "-" in symbol:
            # This correctly extracts the base currency, e.g., "DOGE"
            return symbol.split("-")[0]
        return symbol