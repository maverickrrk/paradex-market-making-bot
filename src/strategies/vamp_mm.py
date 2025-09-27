from typing import Dict, Any, Tuple, Optional
import numpy as np

from .base_strategy import BaseStrategy, LOB

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
        lob_data: LOB, 
        current_position: float, 
        account_balance: float
    ) -> Optional[Tuple[float, float, float, float]]:
        """
        Calculates bid and ask quotes based on the VAMP logic.

        Args:
            lob_data: The current limit order book state.
            current_position: The bot's current position in the base asset.
            account_balance: The account's total equity.

        Returns:
            A tuple of (bid_price, bid_size, ask_price, ask_size), or None if no
            quote should be placed.
        """
        if lob_data is None or lob_data.is_empty():
            self.logger.warning("Order book data is missing or empty. Cannot compute quotes.")
            return None

        # --- 1. Calculate Reference Price (VAMP) ---
        # We use the notional value of our desired order size to calculate the VAMP.
        # This gives us a reference price that reflects the liquidity we intend to trade with.
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
        
        # Calculate our current inventory notional value
        # Convert current_position to float to handle Decimal types from OMS
        inventory_notional = float(current_position) * vamp_price

        # The skew factor pushes our price to encourage trades that reduce our inventory.
        # It's scaled by the ratio of our current inventory to our standard order size.
        inventory_skew_ratio = inventory_notional / reference_notional
        
        # Use tanh to create a smooth, bounded skew effect.
        # As inventory grows, the skew approaches inventory_skew_bps but never exceeds it.
        skew_adjustment_bps = np.tanh(inventory_skew_ratio) * inventory_skew_bps
        
        # --- 3. Calculate Final Bid and Ask Prices ---
        # Convert basis points to a decimal multiplier
        base_spread_multiplier = base_spread_bps / 10000.0
        skew_multiplier = skew_adjustment_bps / 10000.0

        # The skew is subtracted from the mid-point price.
        # If we are long (positive inventory), skew is positive, pushing both bid and ask down.
        # If we are short (negative inventory), skew is negative, pushing both bid and ask up.
        adjusted_mid_price = vamp_price * (1 - skew_multiplier)
        
        half_spread = vamp_price * (base_spread_multiplier / 2.0)
        
        bid_price = adjusted_mid_price - half_spread
        ask_price = adjusted_mid_price + half_spread

        # --- 4. Final Sanity Checks ---
        # Ensure bid is lower than ask and both are positive.
        if bid_price <= 0 or ask_price <= 0 or bid_price >= ask_price:
            self.logger.warning(
                f"Invalid quote calculation: bid={bid_price}, ask={ask_price}. Skipping."
            )
            return None

        # --- 5. Calculate Order Sizes ---
        # Calculate the size in the base asset based on our target notional value.
        bid_size = reference_notional / bid_price
        ask_size = reference_notional / ask_price
        
        # --- 6. Round prices AND SIZES to match exchange requirements ---
        # Paradex requires prices to be rounded to exactly 2 decimal places
        # and amounts (sizes) to be rounded to exactly 4 decimal places
        bid_price = round(bid_price, 2)
        ask_price = round(ask_price, 2)
        bid_size = round(bid_size, 4)
        ask_size = round(ask_size, 4)
        
        self.logger.debug(
            f"Pos: {current_position:.4f} | "
            f"VAMP: {vamp_price:.2f} | "
            f"Skew bps: {skew_adjustment_bps:.2f} | "
            f"Quote: {bid_price:.2f} @ {bid_size:.4f} <-> {ask_price:.2f} @ {ask_size:.4f}"
        )

        return bid_price, bid_size, ask_price, ask_size