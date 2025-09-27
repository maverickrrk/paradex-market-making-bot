# FILE: src/strategies/vamp_mm.py

from typing import Dict, Any, Tuple, Optional
import numpy as np

from .base_strategy import BaseStrategy

class VampMM(BaseStrategy):
    """
    Volume-Adjusted Mid-Price (VAMP) Market Making Strategy.

    This strategy calculates a reference price based on the volume-weighted average
    price of the order book. It then sets bid and ask quotes around this price.
    The spread between the bid and ask is dynamically adjusted based on the bot's
    current inventory to manage risk.

    - If inventory is positive (long), it skews quotes downwards to encourage selling.
    - If inventory is negative (short), it skews quotes upwards to encourage buying.
    """

    def __init__(self, strategy_params: Dict[str, Any]):
        """
        Initializes the VAMP MM strategy.

        Required parameters in `strategy_params`:
        - order_value (float): The target notional value (in USD) for each quote.
        - base_spread_bps (float): The default spread in basis points.
        - inventory_skew_bps (float): The amount to adjust the spread by, per unit of inventory.
        """
        super().__init__(strategy_params)
        
        # Validate required parameters
        required_params = ["order_value", "base_spread_bps", "inventory_skew_bps"]
        for param in required_params:
            if param not in self.params:
                raise ValueError(f"Missing required strategy parameter: '{param}'")

    def compute_quotes(
        self, 
        lob_data: Any, # Expects a SimpleLOB object from the Trader 
        current_position: float, 
        account_balance: float
    ) -> Optional[Tuple[float, float, float, float]]:
        """
        Calculates bid and ask quotes based on the VAMP logic.

        Args:
            lob_data: The current limit order book state (SimpleLOB object).
            current_position: The bot's current position in the base asset.
            account_balance: The account's total equity (not used by this strategy).

        Returns:
            A tuple of (bid_price, bid_size, ask_price, ask_size), or None if no
            quote should be placed.
        """
        if lob_data is None or lob_data.is_empty():
            self.logger.warning("Order book data is missing or empty. Cannot compute quotes.")
            return None

        # --- 1. Calculate Reference Price (VAMP) ---
        reference_notional = self.get_param("order_value")
        vamp_price = lob_data.get_vamp(reference_notional)

        if vamp_price is None or np.isnan(vamp_price) or vamp_price <= 0:
            self.logger.warning(f"Could not calculate a valid VAMP price. Mid price will be used as fallback.")
            vamp_price = lob_data.get_mid() # Fallback to mid-price if VAMP fails
            if vamp_price is None or np.isnan(vamp_price) or vamp_price <= 0:
                 self.logger.error("Fallback mid-price is also invalid. Skipping quote.")
                 return None

        # --- 2. Calculate Desired Spread and Inventory Skew ---
        base_spread_bps = self.get_param("base_spread_bps")
        inventory_skew_bps = self.get_param("inventory_skew_bps")
        
        inventory_notional = float(current_position) * vamp_price
        
        # Use tanh for a smooth, bounded skew effect.
        inventory_skew_ratio = inventory_notional / reference_notional if reference_notional > 0 else 0
        skew_adjustment_bps = np.tanh(inventory_skew_ratio) * inventory_skew_bps
        
        # --- 3. Calculate Final Bid and Ask Prices ---
        base_spread_multiplier = base_spread_bps / 10000.0
        skew_multiplier = skew_adjustment_bps / 10000.0

        adjusted_mid_price = vamp_price * (1 - skew_multiplier)
        half_spread = vamp_price * (base_spread_multiplier / 2.0)
        
        bid_price = adjusted_mid_price - half_spread
        ask_price = adjusted_mid_price + half_spread

        # --- 4. Final Sanity Checks ---
        if bid_price <= 0 or ask_price <= 0 or bid_price >= ask_price:
            self.logger.warning(
                f"Invalid quote calculation: bid={bid_price:.2f}, ask={ask_price:.2f}. Skipping."
            )
            return None

        # --- 5. Calculate Order Sizes ---
        bid_size = reference_notional / bid_price
        ask_size = reference_notional / ask_price
        
        # --- 6. Round prices and sizes to match exchange requirements ---
        # Paradex prices are typically to 2 decimal places, sizes to 4.
        # This can be market-specific, but is a safe default.
        bid_price = round(bid_price, 2)
        ask_price = round(ask_price, 2)
        bid_size = round(bid_size, 4)
        ask_size = round(ask_size, 4)
        
        # Final check for minimum size after rounding
        if bid_size <= 0 or ask_size <= 0:
            self.logger.warning("Order size is zero after rounding. Check order_value and prices. Skipping.")
            return None

        self.logger.debug(
            f"Pos: {current_position:.4f} | "
            f"VAMP: {vamp_price:.2f} | "
            f"Skew bps: {skew_adjustment_bps:.2f} | "
            f"Quote: {bid_size:.4f} @ {bid_price:.2f} <-> {ask_size:.4f} @ {ask_price:.2f}"
        )

        return bid_price, bid_size, ask_price, ask_size