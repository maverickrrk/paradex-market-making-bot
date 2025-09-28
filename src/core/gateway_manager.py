
import asyncio
import logging
from typing import Dict

from paradex_py import Paradex
from paradex_py.environment import TESTNET, PROD

class ParadexClientManager:
    """
    Manages a collection of Paradex client instances, one for each wallet.

    This class ensures that each wallet has a single, initialized Paradex client,
    optimizing resource usage (e.g., connection pooling). It is responsible
    for onboarding all wallets and gracefully shutting them down.
    """
    _clients: Dict[str, Paradex] = {}
    is_initialized: bool = False

    def __init__(self, wallets: Dict[str, Dict[str, str]], paradex_env: str):
        """
        Initializes the ParadexClientManager.

        Args:
            wallets: A dictionary of all wallets loaded from wallets.csv.
            paradex_env: The trading environment ('testnet' or 'mainnet').
        """
        self.wallets_config = wallets
        self.paradex_env = paradex_env
        self.logger = logging.getLogger(self.__class__.__name__)

    async def initialize(self):
        """
        Creates and initializes a Paradex client for each configured wallet.

        This method onboards all wallets concurrently to speed up the startup process.
        """
        if self.is_initialized:
            self.logger.warning("ClientManager is already initialized.")
            return

        self.logger.info(f"Initializing {len(self.wallets_config)} wallet client(s) on '{self.paradex_env}'...")
        env = TESTNET if self.paradex_env == "testnet" else PROD

        # Create tasks to onboard all wallets concurrently
        onboarding_tasks = [
            self._onboard_wallet(wallet_name, creds, env)
            for wallet_name, creds in self.wallets_config.items()
        ]
        
        results = await asyncio.gather(*onboarding_tasks, return_exceptions=True)

        # Process results and check for failures
        successful_clients = 0
        for i, result in enumerate(results):
            wallet_name = list(self.wallets_config.keys())[i]
            if isinstance(result, Exception):
                self.logger.critical(f"❌ Failed to onboard wallet '{wallet_name}': {result}", exc_info=False)
            else:
                self.logger.info(f"✅ Successfully onboarded wallet '{wallet_name}'.")
                self._clients[wallet_name] = result
                successful_clients += 1
        
        if successful_clients == 0 and len(self.wallets_config) > 0:
            raise RuntimeError("All wallets failed to initialize. See logs for details. Exiting.")
        elif successful_clients < len(self.wallets_config):
             self.logger.warning("One or more wallets failed to initialize. The bot will run with the successful ones.")

        self.is_initialized = True
        self.logger.info("ParadexClientManager initialization complete.")

    async def _onboard_wallet(self, wallet_name: str, creds: Dict[str, str], env: str) -> Paradex:
        """Helper coroutine to create and onboard a single Paradex client."""
        self.logger.debug(f"Attempting to onboard wallet: {wallet_name} ({creds['l1_address']})")
        client = Paradex(
            env=env,
            l1_address=creds["l1_address"],
            l1_private_key=creds["l1_private_key"],
        )
        try:
            await client.init_account(
                l1_address=creds["l1_address"],
                l1_private_key=creds["l1_private_key"]
            )
        except Exception as e:
            # Account might already be initialized, which is fine
            if "already initialized" in str(e):
                self.logger.debug(f"Account {wallet_name} already initialized, continuing...")
            else:
                raise e
        return client

    def get_client(self, wallet_name: str) -> Paradex:
        """
        Provides access to an initialized client for a specific wallet.

        Returns:
            The initialized Paradex client object.

        Raises:
            RuntimeError: If the manager has not been initialized yet.
            ValueError: If no client is found for the given wallet name.
        """
        if not self.is_initialized:
            raise RuntimeError(
                "ClientManager has not been initialized. Call `await manager.initialize()` first."
            )
        client = self._clients.get(wallet_name)
        if not client:
            raise ValueError(f"No initialized client found for wallet '{wallet_name}'. This may be due to an onboarding failure.")
        return client

    async def cleanup(self):
        """Gracefully closes all client connections."""
        if self.is_initialized and self._clients:
            self.logger.info("Cleaning up all client connections...")
            cleanup_tasks = [client.close() for client in self._clients.values()]
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            self.is_initialized = False
            self._clients.clear()
            self.logger.info("All clients cleaned up successfully.")