import logging
from typing import Dict, Any

from .custom_gateway import CustomGateway

class GatewayManager:
    """
    Manages a single, shared instance of the quantpylib Gateway.

    This class ensures that the entire application uses one Gateway object,
    optimizing resource usage (e.g., connection pooling, rate limiting).
    It is responsible for initializing the connection to Paradex with all
    the wallet credentials provided and for gracefully shutting it down.
    """
    _gateway_instance: CustomGateway = None

    def __init__(self, wallets: Dict[str, Dict[str, str]], paradex_env: str):
        """
        Initializes the GatewayManager.

        Note: This does not establish the connection. The `initialize` async
        method must be called to do that.

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
        Creates and initializes the master Gateway instance.

        This method configures the Gateway with all provided wallet keys and
        establishes the necessary connections to the exchange.
        """
        if self.is_initialized:
            self.logger.warning("Gateway is already initialized.")
            return

        self.logger.info(f"Initializing master gateway for {len(self.wallets)} wallet(s) on '{self.paradex_env}'...")

        # quantpylib's Gateway needs a specific dictionary format.
        # For Paradex, we need to pass the configuration in the format expected by the Paradex wrapper.
        # Since we have multiple wallets, we'll use the first wallet for now and handle multi-wallet later.
        # TODO: Implement proper multi-wallet support in quantpylib Gateway
        
        if not self.wallets:
            raise ValueError("No wallets configured")
            
        # Use the first wallet for the gateway configuration
        first_wallet_name = list(self.wallets.keys())[0]
        first_wallet_creds = self.wallets[first_wallet_name]
        
        config_keys = {
            "paradex": {
                "key": first_wallet_creds["l1_address"],
                "secret": first_wallet_creds["l1_private_key"],
            }
        }
        
        try:
            GatewayManager._gateway_instance = CustomGateway(config_keys=config_keys)
            await GatewayManager._gateway_instance.init_clients()
            self.is_initialized = True
            self.logger.info("Master gateway initialization successful.")
        except Exception as e:
            self.logger.critical(f"Failed to initialize master gateway: {e}", exc_info=True)
            raise

    def get_gateway(self) -> CustomGateway:
        """
        Provides access to the shared Gateway instance.

        Returns:
            The initialized CustomGateway object.

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
        Gracefully closes all connections managed by the Gateway.
        """
        if self.is_initialized and GatewayManager._gateway_instance:
            self.logger.info("Cleaning up master gateway connections...")
            await GatewayManager._gateway_instance.cleanup_clients()
            self.is_initialized = False
            GatewayManager._gateway_instance = None
            self.logger.info("Master gateway cleaned up successfully.")