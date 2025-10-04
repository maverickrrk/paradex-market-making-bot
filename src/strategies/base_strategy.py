from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional
import logging

# Use a simple LOB type hint - the actual implementation is in trader.py
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.core.trader import SimpleLOB as LOB
else:
    LOB = Any


class BaseStrategy(ABC):
    """
    Abstract Base Class for all trading strategies.

    This class defines the standard interface that every strategy must implement.
    The `Trader` class will interact with strategies through these methods,
    allowing for a modular and plug-and-play architecture.

    A strategy's role is purely computational: it receives market and account
    state information and returns trading decisions (e.g., bid/ask prices).
    It does NOT interact with the exchange API directly.
    """

    def __init__(self, strategy_params: Dict[str, Any]):
        """
        Initializes the strategy with its specific parameters.

        Args:
            strategy_params: A dictionary of parameters loaded from the
                             main_config.yaml file for this specific strategy instance.
        """
        self.params = strategy_params
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"Strategy initialized with parameters: {self.params}")

    @abstractmethod
    def compute_quotes(
        self, 
        lob_data: LOB, 
        current_position: float, 
        account_balance: float
    ) -> Optional[Tuple[float, float, float, float]]:
        """
        The core logic of the strategy.

        Based on the provided market and account state, this method calculates
        the desired bid and ask quotes.

        Args:
            lob_data: A quantpylib LOB object representing the current state of
                      the limit order book.
            current_position: The current size of the position in the base asset
                              (e.g., 1.5 for long 1.5 BTC, -0.5 for short 0.5 BTC).
            account_balance: The total equity or relevant balance of the account.

        Returns:
            A tuple containing (bid_price, bid_size, ask_price, ask_size).
            The sizes should be in the base asset (e.g., BTC for BTC-USD-PERP).
            Returns None if the strategy decides not to place quotes at this time
            (e.g., due to wide spread, low liquidity, or other conditions).
        """
        pass

    def get_param(self, key: str, default: Any = None) -> Any:
        """
        Safely retrieves a parameter from the strategy's configuration.

        Args:
            key: The name of the parameter to retrieve.
            default: The value to return if the key is not found.

        Returns:
            The value of the parameter or the default if not found.
        """
        return self.params.get(key, default)