import logging
import httpx
import asyncio
from typing import Dict, Any, Optional, List

# Import official Paradex SDK
try:
    from paradex_py import Paradex
    from paradex_py.environment import TESTNET, PROD
    from starknet_py.common import int_from_hex
    PARADEX_SDK_AVAILABLE = True
except ImportError:
    PARADEX_SDK_AVAILABLE = False
    Paradex = None
    TESTNET = None
    PROD = None
    int_from_hex = None


class GatewayManager:
    """
    Manages a single, shared instance of the official Paradex SDK client.
    """
    _gateway_instance: Optional[Paradex] = None

    def __init__(self, wallets: Dict[str, Dict[str, str]], paradex_env: str):
        """
        Initializes the GatewayManager.
        Args:
            wallets: A dictionary of all wallets loaded from wallets.csv.
            paradex_env: The trading environment ('testnet' or 'mainnet').
        """
        self.wallets = wallets
        self.paradex_env = paradex_env
        self.is_initialized = False
        self.logger = logging.getLogger(self.__class__.__name__)

    async def initialize(self, tasks: List[Dict[str, Any]]):
        """
        Creates and initializes the official Paradex SDK client and sets leverage.
        Args:
            tasks: The list of trading tasks from the config to extract leverage settings.
        """
        if self.is_initialized:
            self.logger.warning("Gateway is already initialized.")
            return

        if not self.wallets:
            raise ValueError("No wallets configured")
            
        first_wallet_name = list(self.wallets.keys())[0]
        first_wallet_creds = self.wallets[first_wallet_name]
        
        self.logger.info(f"🚀 Initializing official Paradex SDK for {len(self.wallets)} wallet(s) on '{self.paradex_env}'...")
        
        private_key_hex = first_wallet_creds.get("l1_private_key")
        l1_address = first_wallet_creds.get("l1_address")
        
        if not private_key_hex or not l1_address:
            raise ValueError(f"Missing credentials for wallet {first_wallet_name}")

        # Convert private key from hex string to integer
        private_key = int_from_hex(private_key_hex)
        environment = TESTNET if self.paradex_env == "testnet" else PROD
        
        # Patch SDK httpx client for higher timeouts
        try:
            from paradex_py.api import http_client as paradex_http_client
            timeout = httpx.Timeout(30.0, connect=30.0, read=30.0, write=30.0)
            
            def _patched_httpclient_init(self):
                self.client = httpx.Client(timeout=timeout, trust_env=True)
                self.client.headers.update({"Content-Type": "application/json"})
            
            paradex_http_client.HttpClient.__init__ = _patched_httpclient_init
        except Exception:
            pass
        
        last_error: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                # Create Paradex with L1 credentials directly
                GatewayManager._gateway_instance = Paradex(
                    env=environment,
                    l1_address=l1_address,
                    l1_private_key=private_key,
                    logger=self.logger
                )
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt < 3:
                    self.logger.warning(f"Paradex init attempt {attempt} failed: {e}. Retrying...")
                    await asyncio.sleep(2 * attempt)
                else:
                    self.logger.critical(f"❌ Failed to initialize Paradex SDK client: {e}", exc_info=True)
                    raise
        
        if last_error:
            raise last_error

        # Onboarding and Authentication
        try:
            self.get_gateway().api_client.onboarding()
        except Exception as ob_err:
            if "PARENT_ADDRESS_ALREADY_ONBOARDED" in str(ob_err):
                pass
            else:
                self.logger.critical(f"❌ Onboarding failed: {ob_err}")
                raise
        
        self.get_gateway().api_client.auth()
        
        # Set leverage for all configured markets
        leverage_tasks = []
        for task in tasks:
            market = task.get("market_symbol")
            leverage = task.get("strategy_params", {}).get("leverage")
            if market and leverage:
                leverage_tasks.append(self._set_leverage_for_market(market, int(leverage)))
        
        if leverage_tasks:
            await asyncio.gather(*leverage_tasks)

        self.is_initialized = True
        self.logger.info("✅ Official Paradex SDK client initialized and authenticated successfully.")

    def get_gateway(self) -> Paradex:
        if not GatewayManager._gateway_instance:
            raise RuntimeError("Gateway has not been initialized. Call `await manager.initialize()` first.")
        return GatewayManager._gateway_instance

    async def _set_leverage_for_market(self, market: str, leverage: int):
        """Set leverage for a specific market using Paradex API."""
        self.logger.info(f"Setting leverage for {market} to {leverage}x...")
        try:
            api_client = self.get_gateway().api_client
            data = {"leverage": leverage, "margin_type": "CROSS"}
            
            # Use a thread to avoid blocking the event loop
            await asyncio.to_thread(
                api_client._make_request,
                "POST",
                f"/v1/account/margin/{market}",
                data=data
            )
            self.logger.info(f"✅ Successfully set leverage to {leverage}x for {market}")
        except Exception as e:
            self.logger.error(f"❌ Failed to set leverage for {market}: {e}. Using default.")

    async def cleanup(self):
        if self.is_initialized and GatewayManager._gateway_instance:
            self.logger.info("Cleaning up Paradex SDK client connections...")
            GatewayManager._gateway_instance = None
            self.is_initialized = False
            self.logger.info("Paradex SDK client cleaned up successfully.")