#!/usr/bin/env python3
"""
Working Paradex Market Making Bot Demo
Uses public API endpoints for market data and simulates trading.
"""

import asyncio
import logging
import aiohttp
from src.strategies.vamp_mm import VampMM
from src.utils.config_loader import load_main_config

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("WorkingDemo")

class WorkingParadexBot:
    """Working Paradex bot using public API and simulated trading."""
    
    def __init__(self):
        self.base_url = "https://api.testnet.paradex.trade"
        self.session = None
        self.strategy = None
        self.positions = {}  # Simulated positions
        
    async def init(self):
        """Initialize the bot."""
        self.session = aiohttp.ClientSession()
        
        # Load configuration
        config = load_main_config()
        tasks = config.get("tasks", [])
        
        if not tasks:
            logger.error("No trading tasks found in configuration")
            return False
            
        # Use the first task
        task = tasks[0]
        strategy_params = task.get("strategy_params", {})
        
        # Initialize strategy
        self.strategy = VampMM(strategy_params)
        logger.info(f"Strategy initialized: {strategy_params}")
        
        return True
        
    async def cleanup(self):
        """Clean up resources."""
        if self.session:
            await self.session.close()
            
    async def get_orderbook(self, symbol: str):
        """Get order book data from Paradex."""
        try:
            async with self.session.get(f"{self.base_url}/v1/orderbook/{symbol}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get orderbook: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error getting orderbook: {e}")
            return None
            
    async def get_markets(self):
        """Get available markets."""
        try:
            async with self.session.get(f"{self.base_url}/v1/markets") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get markets: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error getting markets: {e}")
            return []
            
    def simulate_order_placement(self, symbol: str, side: str, amount: float, price: float):
        """Simulate order placement."""
        order_id = f"sim_{symbol}_{side}_{int(amount*1000)}_{int(price)}"
        logger.info(f"📝 Simulated order: {side} {amount} {symbol} @ ${price} (ID: {order_id})")
        
        # Update simulated position
        if symbol not in self.positions:
            self.positions[symbol] = 0.0
            
        if side == "buy":
            self.positions[symbol] += amount
        else:
            self.positions[symbol] -= amount
            
        return order_id
        
    async def run_market_making(self, symbol: str):
        """Run market making for a symbol."""
        logger.info(f"🚀 Starting market making for {symbol}")
        
        # Get initial order book
        orderbook = await self.get_orderbook(symbol)
        if not orderbook:
            logger.error(f"Failed to get initial order book for {symbol}")
            return
            
        logger.info(f"📊 Initial order book: {len(orderbook.get('bids', []))} bids, {len(orderbook.get('asks', []))} asks")
        
        # Convert to LOB format for strategy
        from src.core.custom_feed import CustomLOB
        lob = CustomLOB()
        lob.update(orderbook)
        
        # Run market making loop
        for i in range(10):  # Run for 10 iterations
            try:
                # Get fresh order book data
                orderbook = await self.get_orderbook(symbol)
                if orderbook:
                    lob.update(orderbook)
                
                # Get current position
                current_position = self.positions.get(symbol, 0.0)
                
                # Generate quotes using strategy
                quotes = self.strategy.compute_quotes(
                    lob_data=lob,
                    current_position=current_position,
                    account_balance=10000.0
                )
                
                if quotes:
                    bid_price, bid_size, ask_price, ask_size = quotes
                    spread_bps = ((ask_price - bid_price) / bid_price) * 10000
                    
                    logger.info(f"💰 Quote {i+1}: Bid ${bid_price:.2f} @ {bid_size:.4f} | Ask ${ask_price:.2f} @ {ask_size:.4f} | Spread: {spread_bps:.2f} bps | Position: {current_position:.4f}")
                    
                    # Simulate order placement
                    if i % 3 == 0:  # Place orders every 3 iterations
                        self.simulate_order_placement(symbol, "buy", bid_size, bid_price)
                        self.simulate_order_placement(symbol, "sell", ask_size, ask_price)
                else:
                    logger.warning("⚠️  No quotes generated")
                    
                # Wait before next iteration
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error in market making loop: {e}")
                await asyncio.sleep(1)
                
        logger.info(f"✅ Market making completed for {symbol}")
        logger.info(f"📈 Final position: {self.positions.get(symbol, 0.0):.4f} {symbol}")

async def main():
    """Main function."""
    logger.info("🎯 Paradex Market Making Bot - Working Demo")
    logger.info("=" * 60)
    logger.info("Using public API endpoints for market data")
    logger.info("Simulating order placement (no real trades)")
    logger.info("=" * 60)
    
    bot = WorkingParadexBot()
    
    try:
        # Initialize bot
        if not await bot.init():
            logger.error("Failed to initialize bot")
            return
            
        # Get available markets
        markets = await bot.get_markets()
        logger.info(f"📊 Available markets: {len(markets)}")
        
        # Run market making for BTC-USD-PERP
        symbol = "BTC-USD-PERP"
        await bot.run_market_making(symbol)
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
    finally:
        await bot.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
