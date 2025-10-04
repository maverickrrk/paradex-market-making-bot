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
            current_position: The bot's current position in the base asset (ETH amount).
            account_balance: The account's total equity.

        Returns:
            A dictionary with order details including multiple buy/sell orders based on inventory,
            or None if no quotes should be placed.
        """
        if lob_data is None or lob_data.is_empty():
            self.logger.warning("Order book data is missing or empty. Cannot compute quotes.")
            return None

        # --- 1. Calculate Reference Price (VAMP) ---
        reference_notional = self.get_param("order_value")  # $10 base unit
        vamp_price = lob_data.get_vamp(reference_notional)

        if vamp_price is None or np.isnan(vamp_price) or vamp_price <= 0:
            self.logger.warning(f"Could not calculate a valid VAMP price. Mid price will be used as fallback.")
            vamp_price = lob_data.get_mid()
            if vamp_price is None or np.isnan(vamp_price) or vamp_price <= 0:
                 self.logger.error("Fallback mid-price is also invalid. Skipping quote.")
                 return None
        
        # --- 2. Calculate Available Inventory ---
        # current_position is in ETH amount (positive = long ETH, negative = short ETH)
        # account_balance is total equity in USD
        
        # Calculate available USDC (for buy orders)
        # If we have positive ETH position, we have less USDC available
        eth_value = float(current_position) * vamp_price
        available_usdc = account_balance - max(0, eth_value)  # Available USDC for buying
        
        # Calculate available ETH (for sell orders) 
        # If we have positive ETH position, we can sell it
        available_eth_value = max(0, current_position * vamp_price)  # Available ETH value for selling
        
        # --- 3. Position-Based Order Management ---
        # Only place orders that help close the current position
        max_buy_orders = 0
        max_sell_orders = 0
        
        # If we have a long position, only place SELL orders to close it
        if current_position > 0.001:  # Long position
            # For long positions, we can always sell the position size
            # The position size (in ETH) should be sufficient for selling
            max_sell_orders = 1
            self.logger.info(f"📈 Long position detected ({current_position:.4f} ETH) - placing SELL orders only")
            self.logger.info(f"🔍 DEBUG: Position size: {current_position:.4f} ETH, Available ETH value: ${available_eth_value:.2f}")
        
        # If we have a short position, only place BUY orders to close it
        elif current_position < -0.001:  # Short position
            if available_usdc >= reference_notional:
                max_buy_orders = 1
                self.logger.info(f"📉 Short position detected ({current_position:.4f} ETH) - placing BUY orders only")
            else:
                self.logger.warning(f"⚠️  Short position but insufficient USDC for buying")
        
        # If we're flat (no position), place both BUY and SELL orders
        else:
            max_buy_orders = 1 if available_usdc >= reference_notional else 0
            max_sell_orders = 1 if available_eth_value >= reference_notional else 0
            self.logger.info(f"⚖️  Flat position - placing both BUY and SELL orders")
        
        # For testing purposes, if we have no balance, create at least one order of each type
        if account_balance == 0.0 and current_position == 0.0:
            self.logger.warning("⚠️  Zero account balance detected. Creating test orders for demonstration.")
            max_buy_orders = 1
            max_sell_orders = 1
        
        
        # --- 4. Calculate Prices with Spread and Skew ---
        base_spread_bps = self.get_param("base_spread_bps")
        inventory_skew_bps = self.get_param("inventory_skew_bps")
        
        # Calculate inventory skew based on current position
        inventory_skew_ratio = eth_value / reference_notional
        skew_adjustment_bps = np.tanh(inventory_skew_ratio) * inventory_skew_bps
        
        # Calculate final prices
        base_spread_multiplier = base_spread_bps / 10000.0
        skew_multiplier = skew_adjustment_bps / 10000.0
        
        adjusted_mid_price = vamp_price * (1 - skew_multiplier)
        half_spread = vamp_price * (base_spread_multiplier / 2.0)
        
        bid_price = round(adjusted_mid_price - half_spread, 2)
        ask_price = round(adjusted_mid_price + half_spread, 2)
        
        # --- 5. Create Order Lists ---
        buy_orders = []
        sell_orders = []
        
        # Create buy orders (if we have USDC)
        if max_buy_orders > 0:
            single_buy_size = round(reference_notional / bid_price, 4)
            for i in range(max_buy_orders):
                buy_orders.append({
                    "side": "BUY",
                    "price": bid_price,
                    "size": single_buy_size,
                    "notional": reference_notional
                })
        
        # Create sell orders (if we have ETH)
        if max_sell_orders > 0:
            single_sell_size = round(reference_notional / ask_price, 4)
            for i in range(max_sell_orders):
                sell_orders.append({
                    "side": "SELL", 
                    "price": ask_price,
                    "size": single_sell_size,
                    "notional": reference_notional
                })
        
        
        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "vamp_price": vamp_price,
            "inventory_analysis": {
                "eth_position": current_position,
                "eth_value": eth_value,
                "available_usdc": available_usdc,
                "available_eth_value": available_eth_value,
                "max_buy_orders": max_buy_orders,
                "max_sell_orders": max_sell_orders
            }
        }