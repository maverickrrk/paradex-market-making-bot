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
    ) -> Optional[Dict[str, Any]]:
        """
        Calculates bid and ask quotes based on the VAMP logic with dynamic sizing.

        Args:
            lob_data: The current limit order book state.
            current_position: The bot's current position in the base asset (e.g., ETH amount).
            account_balance: The account's total equity.

        Returns:
            A dictionary with order details, or None if no quotes should be placed.
        """
        if lob_data is None or lob_data.is_empty():
            self.logger.warning("Order book data is missing or empty. Cannot compute quotes.")
            return None

        # --- 1. Calculate Reference Price (VAMP or Mid) ---
        reference_notional = self.get_param("order_value")
        vamp_price = lob_data.get_vamp(reference_notional)

        if vamp_price is None or np.isnan(vamp_price) or vamp_price <= 0:
            self.logger.warning(f"Could not calculate a valid VAMP. Using mid-price as fallback.")
            vamp_price = lob_data.get_mid()
            if vamp_price is None or np.isnan(vamp_price) or vamp_price <= 0:
                 self.logger.error("Fallback mid-price is also invalid. Skipping quote.")
                 return None
        
        # --- 2. Calculate Order Sizing and Count ---
        max_orders_per_side = self.get_param("max_orders_per_side", 1)
        
        # --- 3. Position-Based Order Logic ---
        can_place_buy = True
        can_place_sell = True
        
        # Simple logic: if long, prioritize selling; if short, prioritize buying.
        # This can be made more sophisticated (e.g., only place one side)
        if current_position > 0.001:  # Long position
            self.logger.info(f"📈 Long position detected ({current_position:.4f}). Prioritizing SELL orders.")
        elif current_position < -0.001:  # Short position
            self.logger.info(f"📉 Short position detected ({current_position:.4f}). Prioritizing BUY orders.")
        else: # Flat position
            self.logger.info(f"⚖️ Flat position. Placing both BUY and SELL orders.")

        # --- 4. Calculate Prices with Spread and Skew ---
        base_spread_bps = self.get_param("base_spread_bps")
        inventory_skew_bps = self.get_param("inventory_skew_bps")
        
        # Skew adjustment based on position value relative to order size
        eth_value = float(current_position) * vamp_price
        inventory_skew_ratio = eth_value / reference_notional if reference_notional > 0 else 0
        skew_adjustment_bps = np.tanh(inventory_skew_ratio) * inventory_skew_bps
        
        base_spread_multiplier = base_spread_bps / 10000.0
        skew_multiplier = skew_adjustment_bps / 10000.0
        
        # Skew the mid-price based on inventory
        adjusted_mid_price = vamp_price * (1 - skew_multiplier)
        half_spread = vamp_price * (base_spread_multiplier / 2.0)
        
        bid_price = round(adjusted_mid_price - half_spread, 2)
        ask_price = round(adjusted_mid_price + half_spread, 2)
        
        # --- 5. Create Order Lists ---
        buy_orders = []
        sell_orders = []
        
        if can_place_buy:
            if bid_price > 0:
                buy_size = round(reference_notional / bid_price, 4)
                for _ in range(max_orders_per_side):
                    buy_orders.append({"side": "BUY", "price": bid_price, "size": buy_size})
            else:
                self.logger.warning("Calculated bid price is zero or negative. Skipping buy order.")

        if can_place_sell:
            if ask_price > 0:
                sell_size = round(reference_notional / ask_price, 4)
                for _ in range(max_orders_per_side):
                    sell_orders.append({"side": "SELL", "price": ask_price, "size": sell_size})
            else:
                self.logger.warning("Calculated ask price is zero or negative. Skipping sell order.")
        
        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
        }
        