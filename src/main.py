import asyncio
import logging
from typing import Dict, Any, List

# Configure logging for the main script
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    force=True  # Override any existing configuration
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

try:
    # Try absolute imports first (when running as module from project root)
    from src.utils.config_loader import load_main_config, load_wallets, load_env_vars, ConfigError
    from src.utils.logger import setup_logger
    from src.core.gateway_manager import GatewayManager
    from src.core.trader import Trader
    from src.core.hedge.edge import HyperliquidHedge
    from src.core.hedge.orchestrator import OneClickHedger
    from src.strategies.base_strategy import BaseStrategy
    from src.strategies.vamp_mm import VampMM
except ImportError:
    # Fall back to relative imports (when running from src directory)
    from utils.config_loader import load_main_config, load_wallets, load_env_vars, ConfigError
    from utils.logger import setup_logger
    from core.gateway_manager import GatewayManager
    from core.trader import Trader
    from core.hedge.edge import HyperliquidHedge
    from core.hedge.orchestrator import OneClickHedger
    from strategies.base_strategy import BaseStrategy
    from strategies.vamp_mm import VampMM

# --- Strategy Mapping ---
# This dictionary maps the 'strategy_name' from the config file to the actual
# strategy class. This allows for easy extension with new strategies.
STRATEGY_CATALOG: Dict[str, BaseStrategy] = {
    "vamp_mm": VampMM,
}

class Orchestrator:
    """
    The main class that orchestrates the entire bot's lifecycle.
    """
    def __init__(self):
        self.traders: List[Trader] = []
        self.gateway_manager: GatewayManager = None
        self.logger: logging.Logger = None

    def _setup(self):
        """Loads configuration and sets up the initial components."""
        try:
            # Load all configurations first
            self.env_vars = load_env_vars()
            self.main_config = load_main_config()
            self.wallets = load_wallets()

            # Setup the logger using settings from the main config
            log_settings = self.main_config.get("logging", {})
            self.logger = setup_logger(
                name="ParadexBot",
                log_level=log_settings.get("level", "INFO"),
                log_dir=log_settings.get("directory", "logs"),
            )
            self.logger.info("Bot initialized")

            # Initialize the GatewayManager with all wallets
            self.gateway_manager = GatewayManager(
                wallets=self.wallets,
                paradex_env=self.env_vars["PARADEX_ENV"]
            )

        except ConfigError as e:
            # Use a basic logger for setup errors as the main one might not be ready
            logging.basicConfig(level=logging.INFO)
            logging.critical(f"Configuration Error: {e}")
            exit(1) # Exit if configuration is invalid
        except Exception as e:
            logging.basicConfig(level=logging.INFO)
            logging.critical(f"A critical error occurred during setup: {e}")
            exit(1)

    async def run(self):
        """
        The main asynchronous execution method.
        """
        self._setup()

        try:
            # Initialize the shared gateway connection
            await self.gateway_manager.initialize()
            gateway = self.gateway_manager.get_gateway()
            
            # --- Create and Prepare Trader Instances ---
            tasks_config = self.main_config.get("tasks", [])
            if not tasks_config:
                self.logger.warning("No trading tasks found in 'main_config.yaml'. The bot will idle.")
                
            for task_conf in tasks_config:
                wallet_name = task_conf.get("wallet_name")
                market = task_conf.get("market_symbol")
                strategy_name = task_conf.get("strategy_name")
                strategy_params = task_conf.get("strategy_params", {})
                refresh_ms = strategy_params.get("refresh_frequency_ms", 1000)

                # Validate task configuration
                if not all([wallet_name, market, strategy_name]):
                    self.logger.error(f"Skipping invalid task in config: {task_conf}")
                    continue
                if wallet_name not in self.wallets:
                    self.logger.error(f"Wallet '{wallet_name}' from task config not found in 'wallets.csv'. Skipping task.")
                    continue
                if strategy_name not in STRATEGY_CATALOG:
                    self.logger.error(f"Strategy '{strategy_name}' not found in STRATEGY_CATALOG. Skipping task.")
                    continue

                # Instantiate the strategy
                strategy_class = STRATEGY_CATALOG[strategy_name]
                strategy_instance = strategy_class(strategy_params)

                # Optional: construct hedger if hedge config provided
                hedge_conf = task_conf.get("hedge", {})
                hedger = None
                if hedge_conf.get("enabled"):
                    exchange = hedge_conf.get("exchange", "hyperliquid").lower()
                    symbol_map = hedge_conf.get("symbol_map", {})
                    mode = hedge_conf.get("mode", "market")
                    slippage_bps = float(hedge_conf.get("slippage_bps", 10))

                    # Prefer .env creds; fall back to wallets.csv optional fields
                    wallet_creds = self.wallets.get(wallet_name, {})
                    hedge_private_key = self.env_vars.get("HYPERLIQUID_PRIVATE_KEY") or wallet_creds.get("hedge_private_key", "")
                    hedge_public_address = self.env_vars.get("HYPERLIQUID_PUBLIC_ADDRESS") or wallet_creds.get("hedge_public_address", "")
                    hyperliquid_base_url = self.env_vars.get("HYPERLIQUID_REST_URL") or "https://api.hyperliquid.xyz"
                    hyperliquid_order_endpoint = self.env_vars.get("HYPERLIQUID_ORDER_ENDPOINT") or "/exchange"

                    if exchange == "hyperliquid":
                        hedge_client = HyperliquidHedge(
                            private_key=hedge_private_key,
                            public_address=hedge_public_address,
                            base_url=hyperliquid_base_url,
                            order_endpoint=hyperliquid_order_endpoint,
                        )
                    else:
                        self.logger.error(f"Unsupported hedge exchange: {exchange}")
                        hedge_client = None

                    if hedge_client is not None:
                        hedger = OneClickHedger(
                            hedge=hedge_client,
                            symbol_map=symbol_map,
                            mode=mode,
                            slippage_bps=slippage_bps,
                        )
                        await hedger.initialize()

                # Create the Trader instance
                trader = Trader(
                    wallet_name=wallet_name,
                    market_symbol=market,
                    strategy=strategy_instance,
                    gateway=gateway,
                    refresh_frequency_ms=refresh_ms
                )
                # Late binding to avoid constructor signature changes; set attribute if present
                setattr(trader, "hedger", hedger)
                self.traders.append(trader)

            # --- Launch and Manage Trader Tasks ---
            if self.traders:
                trader_tasks = [asyncio.create_task(trader.run()) for trader in self.traders]
                await asyncio.gather(*trader_tasks)
            else:
                # If no valid traders, just wait indefinitely
                await asyncio.Event().wait()


        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.critical(f"Critical error: {e}")
        finally:
            await self.shutdown()
            
    async def shutdown(self):
        """Gracefully shuts down all components."""
        # Concurrently stop all trader tasks
        if self.traders:
            await asyncio.gather(*(trader.stop() for trader in self.traders))
        
        # Close the master gateway connection
        if self.gateway_manager:
            await self.gateway_manager.cleanup()


async def main():
    """Main function to run the bot and handle graceful shutdown."""
    orchestrator = Orchestrator()
    
    # This loop ensures that even if the main task exits, we can catch
    # the shutdown signal (Ctrl+C) and clean up properly.
    main_task = asyncio.create_task(orchestrator.run())

    try:
        await main_task
    except asyncio.CancelledError:
        # This is expected on Ctrl+C
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Shutting down gracefully...")