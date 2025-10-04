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
    from src.utils.config_loader import load_main_config, load_wallets, load_env_vars, ConfigError
    from src.utils.logger import setup_logger
    from src.core.gateway_manager import GatewayManager
    from src.core.trader import Trader
    from src.core.hedge.edge import HyperliquidHedge
    from src.core.hedge.lighter import LighterHedge
    from src.core.hedge.orchestrator import OneClickHedger
    from src.strategies.base_strategy import BaseStrategy
    from src.strategies.vamp_mm import VampMM
except ImportError:
    from utils.config_loader import load_main_config, load_wallets, load_env_vars, ConfigError
    from utils.logger import setup_logger
    from core.gateway_manager import GatewayManager
    from core.trader import Trader
    from core.hedge.edge import HyperliquidHedge
    from core.hedge.lighter import LighterHedge
    from core.hedge.orchestrator import OneClickHedger
    from strategies.base_strategy import BaseStrategy
    from strategies.vamp_mm import VampMM

STRATEGY_CATALOG: Dict[str, Any] = {
    "vamp_mm": VampMM,
}

class Orchestrator:
    """Orchestrates the bot's lifecycle."""
    def __init__(self):
        self.traders: List[Trader] = []
        self.gateway_manager: GatewayManager = None
        self.logger: logging.Logger = None

    def _setup(self):
        """Loads configuration and sets up components."""
        try:
            self.env_vars = load_env_vars()
            self.main_config = load_main_config()
            self.wallets = load_wallets()

            log_settings = self.main_config.get("logging", {})
            self.logger = setup_logger(
                name="ParadexBot",
                log_level=log_settings.get("level", "INFO"),
                log_dir=log_settings.get("directory", "logs"),
            )
            self.logger.info("Bot initialized")

            self.gateway_manager = GatewayManager(
                wallets=self.wallets,
                paradex_env=self.env_vars["PARADEX_ENV"]
            )
        except (ConfigError, Exception) as e:
            logging.basicConfig(level=logging.INFO)
            logging.critical(f"A critical error occurred during setup: {e}", exc_info=True)
            exit(1)

    async def run(self):
        """Main asynchronous execution method."""
        self._setup()

        try:
            tasks_config = self.main_config.get("tasks", [])
            if not tasks_config:
                self.logger.warning("No trading tasks found in 'main_config.yaml'. The bot will idle.")
                return

            await self.gateway_manager.initialize(tasks=tasks_config)
            gateway = self.gateway_manager.get_gateway()
            
            for task_conf in tasks_config:
                wallet_name = task_conf["wallet_name"]
                market = task_conf["market_symbol"]
                strategy_name = task_conf["strategy_name"]
                strategy_params = task_conf.get("strategy_params", {})
                
                strategy_class = STRATEGY_CATALOG[strategy_name]
                strategy_instance = strategy_class(strategy_params)

                hedger = await self._create_hedger(task_conf, wallet_name)

                trader = Trader(
                    wallet_name=wallet_name,
                    market_symbol=market,
                    strategy=strategy_instance,
                    gateway=gateway,
                    refresh_frequency_ms=strategy_params.get("refresh_frequency_ms", 1000)
                )
                trader.hedger = hedger
                self.traders.append(trader)

            if self.traders:
                trader_tasks = [asyncio.create_task(trader.run()) for trader in self.traders]
                await asyncio.gather(*trader_tasks)
            else:
                await asyncio.Event().wait()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.critical(f"Critical error in orchestrator run loop: {e}", exc_info=True)
        finally:
            await self.shutdown()
            
    async def _create_hedger(self, task_conf: Dict[str, Any], wallet_name: str) -> Optional[OneClickHedger]:
        """Creates and initializes a hedge client based on config."""
        hedge_conf = task_conf.get("hedge", {})
        if not hedge_conf.get("enabled"):
            return None

        exchange_name = hedge_conf.get("exchange", "").lower()
        wallet_creds = self.wallets.get(wallet_name, {})
        hedge_client = None

        if exchange_name == "hyperliquid":
            private_key = self.env_vars.get("HYPERLIQUID_PRIVATE_KEY")
            public_address = self.env_vars.get("HYPERLIQUID_PUBLIC_ADDRESS")
            if private_key and public_address:
                hedge_client = HyperliquidHedge(
                    private_key=private_key,
                    public_address=public_address,
                    base_url=self.env_vars.get("HYPERLIQUID_REST_URL"),
                )
        elif exchange_name == "lighter":
            private_key = self.env_vars.get("LIGHTER_PRIVATE_KEY")
            public_address = self.env_vars.get("LIGHTER_PUBLIC_ADDRESS")
            if private_key and public_address:
                hedge_client = LighterHedge(
                    private_key=private_key,
                    public_address=public_address,
                    base_url=self.env_vars.get("LIGHTER_REST_URL"),
                    is_testnet=self.env_vars.get("LIGHTER_IS_TESTNET", "false").lower() == "true",
                )
        
        if not hedge_client:
            self.logger.error(f"Hedge exchange '{exchange_name}' is not supported or credentials are missing.")
            return None

        hedger = OneClickHedger(
            hedge=hedge_client,
            symbol_map=hedge_conf.get("symbol_map", {}),
            mode=hedge_conf.get("mode", "market"),
            slippage_bps=float(hedge_conf.get("slippage_bps", 10)),
        )
        await hedger.initialize()
        return hedger

    async def shutdown(self):
        """Gracefully shuts down all components."""
        if self.traders:
            self.logger.info("Shutting down traders...")
            await asyncio.gather(*(trader.stop() for trader in self.traders))
        
        if self.gateway_manager:
            await self.gateway_manager.cleanup()
        self.logger.info("Shutdown complete.")

async def main():
    orchestrator = Orchestrator()
    try:
        await orchestrator.run()
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Shutting down gracefully...")