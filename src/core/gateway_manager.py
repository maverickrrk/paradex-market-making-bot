import logging
import httpx
import asyncio
from typing import Dict, Any, Optional

# Import official Paradex SDK
try:
    from paradex_py import Paradex
    from paradex_py.environment import TESTNET, PROD
    PARADEX_SDK_AVAILABLE = True
except ImportError:
    PARADEX_SDK_AVAILABLE = False
    Paradex = None
    TESTNET = None
    PROD = None


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

    async def initialize(self):
        """
        Creates and initializes the official Paradex SDK client.
        """
        if self.is_initialized:
            self.logger.warning("Gateway is already initialized.")
            return

        if not self.wallets:
            raise ValueError("No wallets configured")
            
        # Use the first wallet for the gateway configuration
        first_wallet_name = list(self.wallets.keys())[0]
        first_wallet_creds = self.wallets[first_wallet_name]
        
        self.logger.info(f"🚀 Initializing official Paradex SDK for {len(self.wallets)} wallet(s) on '{self.paradex_env}'...")
        
        # Get the private key and address for the Paradex client
        private_key = first_wallet_creds.get("l1_private_key")
        l1_address = first_wallet_creds.get("l1_address")
        
        if not private_key:
            raise ValueError(f"No private key found for wallet {first_wallet_name}")
        if not l1_address:
            raise ValueError(f"No L1 address found for wallet {first_wallet_name}")
        
        # Set the environment
        environment = TESTNET if self.paradex_env == "testnet" else PROD
        
        # Patch SDK httpx client with higher timeouts and env proxy support
        try:
            from paradex_py.api import http_client as paradex_http_client
            timeout = httpx.Timeout(30.0, connect=30.0, read=30.0, write=30.0)
            
            def _patched_httpclient_init(self):
                self.client = httpx.Client(timeout=timeout, trust_env=True)
                self.client.headers.update({"Content-Type": "application/json"})
            
            paradex_http_client.HttpClient.__init__ = _patched_httpclient_init
        except Exception:
            pass
        
        # Retry Paradex initialization to mitigate transient TLS handshake timeouts
        last_error: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                # Create Paradex without keys to avoid implicit onboarding
                GatewayManager._gateway_instance = Paradex(
                    env=environment,
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
        
        if last_error is not None:
            # Shouldn't happen, but guard anyway
            raise last_error
        
        # Manually attach account and authenticate (skip onboarding). If sub-account
        # information is provided, still use L1 for auth but note that trading will
        # occur under sub-account scoping at the API layer when supported.
        from paradex_py.account.account import ParadexAccount
        paradex = GatewayManager._gateway_instance
        account = ParadexAccount(
            config=paradex.config,
            l1_address=l1_address,
            l1_private_key=private_key,  # pass hex string
        )
        paradex.account = account
        paradex.api_client.account = account

        # Optional: attach sub-account metadata if available (SDK-dependent)
        sub_id = first_wallet_creds.get("paradex_sub_account_id")
        sub_key = first_wallet_creds.get("paradex_sub_api_key")
        sub_secret = first_wallet_creds.get("paradex_sub_api_secret")
        if sub_id and sub_key and sub_secret:
            try:
                # Some SDKs support setting headers or params. This is a placeholder
                # to illustrate attaching sub-account context; adapt to SDK specifics.
                setattr(paradex.api_client, "sub_account_id", sub_id)
                setattr(paradex.api_client, "sub_api_key", sub_key)
                setattr(paradex.api_client, "sub_api_secret", sub_secret)
                self.logger.info(f"Using Paradex sub-account context: {sub_id}")
            except Exception:
                self.logger.warning("Paradex SDK does not support sub-account context directly; proceed with L1 auth only.")
        
        # Always attempt onboarding first; ignore if already onboarded
        try:
            paradex.api_client.onboarding()
        except Exception as ob_err:
            if "PARENT_ADDRESS_ALREADY_ONBOARDED" in str(ob_err):
                pass
            else:
                self.logger.critical(f"❌ Onboarding failed: {ob_err}")
                raise
        
        # Then authenticate to get JWT and auth_timestamp
        paradex.api_client.auth()
        
        self.is_initialized = True
        self.logger.info("✅ Official Paradex SDK client initialized and authenticated successfully.")

    def get_gateway(self) -> Paradex:
        """
        Provides access to the shared ParadexClient instance.

        Returns:
            The initialized ParadexClient object.

        Raises:
            RuntimeError: If the gateway has not been initialized yet.
        """
        if not self.is_initialized or GatewayManager._gateway_instance is None:
            raise RuntimeError(
                "Gateway has not been initialized. Call `await manager.initialize()` first."
            )
        return GatewayManager._gateway_instance

    async def cleanup(self):
        """
        Gracefully closes all connections managed by the Paradex client.
        """
        if self.is_initialized and GatewayManager._gateway_instance:
            self.logger.info("Cleaning up Paradex SDK client connections...")
            # The official SDK doesn't have explicit cleanup, but we can set to None
            GatewayManager._gateway_instance = None
            self.is_initialized = False
            self.logger.info("Paradex SDK client cleaned up successfully.")