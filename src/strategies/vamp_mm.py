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
        """
        super().__init__(strategy_params)
        
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
        Calculates bid and ask quotes based on VAMP logic with safety checks.
        """
        if lob_data is None or lob_data.is_empty():
            self.logger.warning("Order book data is missing or empty. Cannot compute quotes.")
            return None

        # --- 1. Calculate Reference Price ---
        reference_notional = self.get_param("order_value")
        vamp_price = lob_data.get_vamp(reference_notional)

        if vamp_price is None or np.isnan(vamp_price) or vamp_price <= 0:
            self.logger.warning("Could not calculate a valid VAMP. Using mid-price as fallback.")
            vamp_price = lob_data.get_mid()
            if vamp_price is None or np.isnan(vamp_price) or vamp_price <= 0:
                 self.logger.error("Fallback mid-price is also invalid. Skipping quote.")
                 return None
        
        # --- 2. Determine Order Placement Logic ---
        max_orders_per_side = self.get_param("max_orders_per_side", 1)
        
        # --- 3. Calculate Prices with Spread, Skew, and Safety Checks ---
        base_spread_bps = self.get_param("base_spread_bps")
        inventory_skew_bps = self.get_param("inventory_skew_bps")
        
        eth_value = float(current_position) * vamp_price
        inventory_skew_ratio = eth_value / reference_notional if reference_notional > 0 else 0
        skew_adjustment_bps = np.tanh(inventory_skew_ratio) * inventory_skew_bps
        
        base_spread_multiplier = base_spread_bps / 10000.0
        skew_multiplier = skew_adjustment_bps / 10000.0
        
        adjusted_mid_price = vamp_price * (1 - skew_multiplier)
        half_spread = vamp_price * (base_spread_multiplier / 2.0)
        
        # --- Teammate's New Safety Feature 1: Minimum Spread ---
        min_spread_bps = 5  # Enforce a 5 bps minimum spread
        min_half_spread = vamp_price * (min_spread_bps / 10000.0) / 2.0
        half_spread = max(half_spread, min_half_spread)
        
        bid_price = round(adjusted_mid_price - half_spread, 4) # Increased precision
        ask_price = round(adjusted_mid_price + half_spread, 4) # Increased precision
        
        # --- Teammate's New Safety Feature 2: Anti-Crossing Logic ---
        best_bid_data = lob_data.best_bid()
        best_ask_data = lob_data.best_ask()
        
        if best_bid_data and bid_price >= best_bid_data[0]:
            bid_price = round(best_bid_data[0] - 0.0001, 4)
            self.logger.warning(f"⚠️ Bid price would cross. Adjusting to: ${bid_price}")
        
        if best_ask_data and ask_price <= best_ask_data[0]:
            ask_price = round(best_ask_data[0] + 0.0001, 4)
            self.logger.warning(f"⚠️ Ask price would cross. Adjusting to: ${ask_price}")
            
        # --- 4. Create Order Lists ---
        buy_orders = []
        sell_orders = []
        
        if bid_price > 0:
            buy_size = round(reference_notional / bid_price, 4)
            for _ in range(max_orders_per_side):
                buy_orders.append({"side": "BUY", "price": bid_price, "size": buy_size})

        if ask_price > 0:
            sell_size = round(reference_notional / ask_price, 4)
            for _ in range(max_orders_per_side):
                sell_orders.append({"side": "SELL", "price": ask_price, "size": sell_size})
        
        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
        }
        