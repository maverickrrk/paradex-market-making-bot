#!/usr/bin/env python3
"""
Demo version of the Paradex market making bot with mock data.
This shows the bot working without requiring real API credentials.
"""

import asyncio
import logging
from src.core.custom_gateway import CustomGateway
from src.core.custom_oms import CustomOMS
from src.core.custom_feed import CustomFeed, CustomLOB
from src.strategies.vamp_mm import VampMM
from src.utils.config_loader import load_main_config

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DemoBot")

class DemoGateway(CustomGateway):
    """Demo gateway that simulates real market data."""
    
    def __init__(self):
        super().__init__({"paradex": {"key": "demo", "secret": "demo"}})
        self.logger = logging.getLogger("DemoGateway")
        self.orderbook_data = {
            "BTC-USD-PERP": {
                "bids": [
                    ["50000.0", "1.5"],
                    ["49999.0", "2.0"],
                    ["49998.0", "1.0"],
                    ["49997.0", "0.5"]
                ],
                "asks": [
                    ["50001.0", "1.5"],
                    ["50002.0", "2.0"],
                    ["50003.0", "1.0"],
                    ["50004.0", "0.5"]
                ]
            },
            "ETH-USD-PERP": {
                "bids": [
                    ["3000.0", "5.0"],
                    ["2999.0", "3.0"],
                    ["2998.0", "2.0"],
                    ["2997.0", "1.0"]
                ],
                "asks": [
                    ["3001.0", "5.0"],
                    ["3002.0", "3.0"],
                    ["3003.0", "2.0"],
                    ["3004.0", "1.0"]
                ]
            }
        }
        
    async def init_clients(self):
        self.logger.info("Demo gateway initialized with mock data")
        
    async def get_positions(self):
        return {"positions": [{"symbol": "BTC-USD-PERP", "amount": "0.0"}]}
        
    async def get_orders(self):
        return {"orders": []}
        
    async def get_orderbook(self, symbol: str):
        return self.orderbook_data.get(symbol, {"bids": [], "asks": []})
        
    async def place_order(self, symbol: str, side: str, amount: float, price: float, order_type: str = "limit"):
        order_id = f"demo_{symbol}_{side}_{int(amount*1000)}_{int(price)}"
        self.logger.info(f"📝 Demo order placed: {side} {amount} {symbol} @ ${price}")
        return {"id": order_id}
        
    async def cancel_order(self, order_id: str):
        self.logger.info(f"❌ Demo order cancelled: {order_id}")
        return True

async def run_demo_bot():
    """Run the demo bot with mock data."""
    
    logger.info("🚀 Paradex Market Making Bot - Demo Mode")
    logger.info("=" * 60)
    logger.info("This demo shows the bot working with mock market data.")
    logger.info("No real trades will be executed.")
    logger.info("=" * 60)
    
    # Load configuration
    config = load_main_config()
    tasks = config.get("tasks", [])
    
    if not tasks:
        logger.error("No trading tasks found in configuration")
        return
        
    # Use the first task
    task = tasks[0]
    wallet_name = task.get("wallet_name")
    market_symbol = task.get("market_symbol")
    strategy_params = task.get("strategy_params", {})
    
    logger.info(f"📊 Trading Task: {wallet_name} - {market_symbol}")
    logger.info(f"⚙️  Strategy Parameters: {strategy_params}")
    
    # Create demo gateway
    gateway = DemoGateway()
    await gateway.init_clients()
    
    # Create OMS and Feed
    oms = CustomOMS(gateway)
    await oms.init()
    
    feed = CustomFeed(gateway)
    feed.start()
    
    # Create strategy
    strategy = VampMM(strategy_params)
    
    # Create LOB and subscribe to feed
    lob = CustomLOB(market_symbol)
    
    async def lob_handler(lob_data):
        """Handle order book updates."""
        # The LOB data is already updated by the feed
        pass
        
    await feed.add_l2_book_feed("paradex", market_symbol, lob_handler)
    
    logger.info(f"📈 Subscribed to {market_symbol} order book")
    logger.info("🔄 Starting market making loop...")
    logger.info("Press Ctrl+C to stop")
    
    try:
        # Run for 30 seconds to demonstrate
        for i in range(30):
            # Get the LOB data from the feed
            if market_symbol in feed.lob_data and not feed.lob_data[market_symbol].is_empty():
                current_lob = feed.lob_data[market_symbol]
                # Get current position
                positions = oms.positions_peek("paradex")
                current_position = positions.get_ticker_amount(market_symbol)
                
                # Generate quotes
                quotes = strategy.compute_quotes(
                    lob_data=current_lob,
                    current_position=current_position,
                    account_balance=10000.0
                )
                
                if quotes:
                    bid_price, bid_size, ask_price, ask_size = quotes
                    spread_bps = ((ask_price - bid_price) / bid_price) * 10000
                    
                    logger.info(f"💰 Quote: Bid ${bid_price:.2f} @ {bid_size:.4f} | Ask ${ask_price:.2f} @ {ask_size:.4f} | Spread: {spread_bps:.2f} bps")
                    
                    # Place demo orders
                    if i % 5 == 0:  # Place orders every 5 seconds
                        await oms.limit_order("paradex", market_symbol, bid_size, bid_price)
                        await oms.limit_order("paradex", market_symbol, -ask_size, ask_price)
                else:
                    logger.warning("⚠️  No quotes generated")
            else:
                logger.info("⏳ Waiting for market data...")
                
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("\n🛑 Demo stopped by user")
    except Exception as e:
        logger.error(f"❌ Error in demo: {e}")
    finally:
        # Cleanup
        feed.stop()
        await gateway.cleanup_clients()
        logger.info("✅ Demo completed")

if __name__ == "__main__":
    asyncio.run(run_demo_bot())
