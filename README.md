# Paradex Multi-Wallet Market Making Bot

This is a high-frequency market making bot designed specifically for the Paradex perpetuals exchange. It is built using the `quantpylib` library and is architected to manage and run trading strategies across multiple wallets simultaneously, making it ideal for large-scale operations like airdrop farming.

The primary strategy implemented is the Volume-Adjusted Mid-Price (VAMP) market maker, which aims to provide liquidity while managing inventory risk.

## Key Features

-   **Multi-Wallet Management**: Designed from the ground up to run concurrently on dozens or hundreds of wallets from a single instance.
-   **Configuration-Driven**: Easily add/remove wallets, change markets, and tune strategy parameters without modifying any code.
-   **Powered by `quantpylib`**: Leverages a professional-grade HFT library for robust order management (OMS), real-time data feeds, and exchange connectivity.
-   **Modular Strategy Design**: Strategies are separated from the core execution logic, allowing for easy testing and addition of new algorithms.
-   **Robust & Scalable**: Built with `asyncio` for efficient handling of many simultaneous network connections and trading tasks.

## Architecture Overview

The bot operates on an **Orchestrator-Trader** model:

-   **`main.py` (Orchestrator)**: The main entry point that reads all configurations, initializes a shared connection to Paradex, and launches individual `Trader` tasks.
-   **`Trader` Class**: Each `Trader` is an independent, asynchronous task responsible for one wallet trading on one market. It contains its own Order Management System (OMS) and is linked to a specific strategy instance.
-   **`Strategy` Classes**: These classes contain the pure market-making logic (e.g., calculating quotes). They receive market data from a `Trader` and return trading decisions, but do not interact with the exchange directly.

## Prerequisites

-   Python 3.10+
-   Git

## Setup and Installation

1.  **Clone the Repository:**
bash
    git clone https://github.com/maverickrrk/paradex-market-making-bot.git
    cd paradex-market-making-bot
    
text
Copy
2.  **Create and Activate a Virtual Environment:**
bash
    # Create the virtual environment
    python3 -m venv venv

    # Activate it
    # On macOS/Linux:
    source venv/bin/activate
    # On Windows:
    # .\venv\Scripts\activate
    
text
Copy
3.  **Install Dependencies:**
bash
    pip install -r requirements.txt
    
text
Copy
## Configuration

Configuration is handled through three key files. **NEVER commit sensitive files (`.env`, `wallets.csv`) to Git.**

### 1. Environment File (`.env`)

This file is used for environment-specific settings. Copy the example file to create your own:
bash
cp .env.example .env
text
Copy
Now, edit the `.env` file. For this bot, the environment is mainly used to specify the Paradex network.
ini
# .env
# The Paradex environment to connect to.
# Use 'testnet' for development/testing and 'mainnet' for live trading.
PARADEX_ENV=testnet
text
Copy
### 2. Wallet Credentials (`config/wallets.csv`)

This file stores your sensitive wallet credentials. It is **CRITICAL** that you do not commit this file to version control. The `.gitignore` file is already configured to prevent this.

Create a file named `wallets.csv` inside the `config/` directory.

**Format:** `wallet_name,l1_address,l1_private_key`

**Example `config/wallets.csv`:**
csv
FARMER_001,0xYourFirstWalletAddressHere,0xYourFirstWalletPrivateKeyHere
FARMER_002,0xYourSecondWalletAddressHere,0xYourSecondWalletPrivateKeyHere
FARMER_003,0xYourThirdWalletAddressHere,0xYourThirdWalletPrivateKeyHere
text
Copy
> **Security Warning:** Your L1 private keys grant full control over your funds. Protect this file carefully.

### 3. Main Configuration (`config/main_config.yaml`)

This file defines which wallets will trade on which markets and with which strategy. This is the main control panel for the bot.

Create a file named `main_config.yaml` inside the `config/` directory.

**Example `config/main_config.yaml`:**
yaml
# --- General Bot Settings ---
logging:
  level: "INFO"  # Log level (DEBUG, INFO, WARNING, ERROR)
  directory: "logs"

# --- Trading Tasks ---
# Define a list of tasks the bot should run.
# Each task links a wallet, a market, and a strategy.
tasks:
  - wallet_name: "FARMER_001"
    market_symbol: "BTC-USD-PERP"
    strategy_name: "vamp_mm"
    strategy_params:
      order_value: 200        # Desired notional value (in USD) for each order
      base_spread_bps: 6      # Base bid-ask spread in basis points (1 bps = 0.01%)
      inventory_skew_bps: 4   # How much to adjust spread based on inventory
      refresh_frequency_ms: 100 # How often to update quotes in milliseconds

  - wallet_name: "FARMER_002"
    market_symbol: "ETH-USD-PERP"
    strategy_name: "vamp_mm"
    strategy_params:
      order_value: 100
      base_spread_bps: 8
      inventory_skew_bps: 5
      refresh_frequency_ms: 150
text
Copy
## Running the Bot

Once your configuration is complete, you can start the bot from the root directory:
bash
python src/main.py
text
Copy
The application will start, load all configurations, and begin running a concurrent trading task for each entry defined in `main_config.yaml`.

## Disclaimer

Automated trading is risky. Use this bot at your own risk. The authors are not responsible for any financial losses. Al