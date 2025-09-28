# FILE: src/main.py

import asyncio
import logging
from typing import Dict, List, Type

from src.utils.config_loader import load_main_config, load_wallets, load_env_vars, ConfigError
from src.utils.logger import setup_logger
from src.core.gateway_manager import ParadexClientManager
from src.core.trader import Trader
from src.strategies.base_strategy import BaseStrategy
from src.strategies.vamp_mm import VampMM

# --- Strategy Mapping ---
# Maps 'strategy_name' from config to the actual strategy class.
STRATEGY_CATALOG: Dict[str, Type[BaseStrategy]] = {
    "vamp_mm": VampMM,
}

class Orchestrator:
    """
    The main class that orchestrates the entire bot's lifecycle.
    It loads configs, initializes a client manager for all wallets,
    and launches an independent Trader task for each trading configuration.
    """
    def __init__(self):
        self.traders: List[Trader] = []
        self.client_manager: ParadexClientManager = None
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
            self.logger.info("Configuration loaded and logger initialized.")
            self.logger.info(f"Loaded environment: PARADEX_ENV={self.env_vars['PARADEX_ENV']}")

            # Initialize the ParadexClientManager with all wallets
            self.client_manager = ParadexClientManager(
                wallets=self.wallets,
                paradex_env=self.env_vars["PARADEX_ENV"]
            )

        except ConfigError as e:
            logging.basicConfig(level=logging.INFO, format="[%(levelname)-8s] - %(message)s")
            logging.critical(f"Configuration Error: {e}")
            exit(1)
        except Exception as e:
            logging.basicConfig(level=logging.INFO, format="[%(levelname)-8s] - %(message)s")
            logging.critical(f"A critical error occurred during setup: {e}", exc_info=True)
            exit(1)

    async def run(self):
        """
        The main asynchronous execution method.
        """
        self._setup()

        try:
            # Initialize the shared client manager, which onboards all wallets
            await self.client_manager.initialize()
            
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

                try:
                    # Get the dedicated client for this wallet
                    client_for_trader = self.client_manager.get_client(wallet_name)
                    
                    # Instantiate the strategy
                    strategy_class = STRATEGY_CATALOG[strategy_name]
                    strategy_instance = strategy_class(strategy_params)

                    # Create the Trader instance
                    trader = Trader(
                        wallet_name=wallet_name,
                        market_symbol=market,
                        strategy=strategy_instance,
                        client=client_for_trader, # Pass the specific client
                        refresh_frequency_ms=refresh_ms
                    )
                    self.traders.append(trader)
                except (ValueError, RuntimeError) as e:
                    self.logger.error(f"Could not create trader for '{wallet_name}' on '{market}'. Reason: {e}. Skipping task.")
                    continue


            # --- Launch and Manage Trader Tasks ---
            if self.traders:
                self.logger.info(f"Launching {len(self.traders)} trader task(s)...")
                trader_tasks = [asyncio.create_task(trader.run()) for trader in self.traders]
                await asyncio.gather(*trader_tasks)
            else:
                self.logger.warning("No valid traders were created. The bot will now exit.")

        except asyncio.CancelledError:
            self.logger.info("Main orchestrator task cancelled. Initiating shutdown...")
        except Exception as e:
            self.logger.critical(f"A critical error occurred in the orchestrator run loop: {e}", exc_info=True)
        finally:
            await self.shutdown()
            
    async def shutdown(self):
        """Gracefully shuts down all components."""
        self.logger.info("Shutting down all traders...")
        
        # Concurrently stop all trader tasks
        if self.traders:
            stop_tasks = [trader.stop() for trader in self.traders if trader._is_running]
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        # Close all client connections via the manager
        if self.client_manager:
            await self.client_manager.cleanup()
            
        self.logger.info("Shutdown complete. Exiting.")

async def main_entrypoint():
    """Main function to run the bot and handle graceful shutdown."""
    orchestrator = Orchestrator()
    
    # Create the main task for the orchestrator
    main_task = asyncio.create_task(orchestrator.run())

    try:
        await main_task
    except asyncio.CancelledError:
        # This is expected on Ctrl+C
        pass

if __name__ == "__main__":
    try:
        asyncio.run(main_entrypoint())
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Shutting down gracefully...")