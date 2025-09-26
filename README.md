# Paradex Multi-Wallet Market Making Bot

A professional-grade, high-frequency market making bot designed specifically for the Paradex perpetuals exchange. Built with enterprise-level architecture using the `quantpylib` library, this bot is engineered to manage and execute trading strategies across multiple wallets simultaneously, making it ideal for large-scale operations including airdrop farming and institutional market making.

## 🚀 Key Features

### **Multi-Wallet Architecture**
- **Concurrent Trading**: Manage dozens or hundreds of wallets from a single instance
- **Independent Execution**: Each wallet operates independently with its own strategy parameters
- **Scalable Design**: Built with `asyncio` for efficient handling of simultaneous network connections

### **Advanced Strategy Engine**
- **VAMP Algorithm**: Volume-Adjusted Mid-Price market making with intelligent inventory management
- **Modular Design**: Easy to add new strategies without modifying core execution logic
- **Risk Management**: Built-in inventory skewing and position management

### **Professional Infrastructure**
- **Powered by quantpylib**: Enterprise-grade HFT library for robust order management (OMS)
- **Real-time Data Feeds**: Live L2 order book streaming and processing
- **Configuration-Driven**: Zero-code configuration changes for wallets, markets, and strategies
- **Comprehensive Logging**: Structured logging with file rotation and colored console output

## 📋 Prerequisites

- **Python**: 3.10 or higher
- **Git**: For repository cloning
- **Paradex Account**: With funded wallets for trading
- **API Access**: L1 private keys for wallet authentication

## 🏗️ Project Architecture

```
paradex-market-making-bot/
├── .env.example                  # Environment configuration template
├── .gitignore                    # Git ignore rules (includes security exclusions)
├── README.md                     # This documentation
├── requirements.txt              # Python dependencies reference
├── config/
│   ├── main_config.yaml          # Bot operational configuration
│   └── wallets.csv               # Wallet credentials (SECURE - git-ignored)
└── src/
    ├── main.py                   # Application entry point and orchestrator
    ├── core/
    │   ├── gateway_manager.py    # Shared quantpylib Gateway connection manager
    │   └── trader.py             # Individual trading instance per wallet/market
    ├── strategies/
    │   ├── base_strategy.py      # Abstract strategy interface
    │   └── vamp_mm.py            # Volume-Adjusted Mid-Price strategy implementation
    └── utils/
        ├── config_loader.py      # Configuration file parsers and validators
        └── logger.py             # Centralized logging setup with colors
```

## ⚙️ Installation & Setup

### **Critical Dependency Notice**
Due to conflicting dependencies between `quantpylib` and `paradex-py`, packages **must** be installed in the specific order below. Do **NOT** use `pip install -r requirements.txt`.

### **Step 1: Repository Setup**
```bash
# Clone the repository
git clone https://github.com/maverickrrk/paradex-market-making-bot.git
cd paradex-market-making-bot
```

### **Step 2: Virtual Environment**
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### **Step 3: Dependency Installation**
```bash
# Upgrade pip
python -m pip install --upgrade pip

# Install quantpylib with its dependencies
pip install git+https://github.com/sumitabh1710/quantpylib.git

# Install paradex-py WITHOUT its dependencies (critical step)
pip install --no-deps paradex-py

# Install utility packages
pip install python-dotenv PyYAML
```

## 🔧 Configuration

### **1. Environment Configuration**
```bash
# Copy the example environment file
cp .env.example .env
```

Edit `.env` file:
```bash
# Set your trading environment
PARADEX_ENV=testnet  # Use 'testnet' for testing, 'mainnet' for live trading
```

### **2. Wallet Credentials Setup**
Create `config/wallets.csv` with your wallet information:

**⚠️ Security Notice**: This file contains private keys and is automatically git-ignored.

**Format**: `wallet_name,l1_address,l1_private_key`

**Example**:
```csv
wallet_name,l1_address,l1_private_key
FARMER_001,0x742d35Cc6634C0532925a3b8D4C7c4e5d5C4b5A6,0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318
FARMER_002,0x8ba1f109551bD432803012645Hac136c4c5c4b5A6,0x5d1994a79103847e7342582c6ebb7305ff6240728193893bf579e02b4f473429
```

### **3. Bot Configuration**
The `config/main_config.yaml` file controls all bot operations:

```yaml
# Logging configuration
logging:
  level: "INFO"          # DEBUG, INFO, WARNING, ERROR, CRITICAL
  directory: "logs"      # Log file directory

# Trading tasks - each creates an independent trader
tasks:
  - wallet_name: "FARMER_001"
    market_symbol: "BTC-USD-PERP"
    strategy_name: "vamp_mm"
    strategy_params:
      order_value: 200              # USD notional per order
      base_spread_bps: 6            # Base spread (6 bps = 0.06%)
      inventory_skew_bps: 4         # Inventory risk adjustment
      refresh_frequency_ms: 250     # Quote refresh rate

  - wallet_name: "FARMER_002"
    market_symbol: "ETH-USD-PERP"
    strategy_name: "vamp_mm"
    strategy_params:
      order_value: 100
      base_spread_bps: 8
      inventory_skew_bps: 5
      refresh_frequency_ms: 300
```

## 🎯 VAMP Strategy Deep Dive

The **Volume-Adjusted Mid-Price (VAMP)** strategy is an advanced market making algorithm that:

### **Core Algorithm**
1. **Reference Price Calculation**: Uses `lob_data.get_vamp(notional)` to calculate a volume-weighted price based on your intended order size
2. **Inventory Management**: Dynamically adjusts quotes based on current position to manage risk
3. **Spread Optimization**: Combines base spread with inventory-driven skewing

### **Key Parameters**
- **`order_value`**: Target USD notional value for each order
- **`base_spread_bps`**: Minimum spread in basis points (100 bps = 1%)
- **`inventory_skew_bps`**: Additional spread per unit of inventory imbalance
- **`refresh_frequency_ms`**: How often to recalculate and update quotes

### **Risk Management**
- **Inventory Skewing**: Long positions → lower quotes (encourage selling)
- **Position Limits**: Automatic quote adjustment based on position size
- **Market Conditions**: Fallback to mid-price if VAMP calculation fails

## 🚀 Running the Bot

### **Start the Bot**
```bash
# From the project root directory
python src/main.py
```

### **Expected Output**
```
[2025-01-26 14:21:05] [ParadexBot] [INFO    ] - Configuration loaded and logger initialized.
[2025-01-26 14:21:06] [GatewayManager] [INFO    ] - Initializing master gateway for 2 wallet(s) on 'testnet'...
[2025-01-26 14:21:08] [GatewayManager] [INFO    ] - Master gateway initialization successful.
[2025-01-26 14:21:08] [Orchestrator] [INFO    ] - Launching 2 trader task(s)...
[2025-01-26 14:21:09] [Trader.FARMER_001.BTC-USD-PERP] [INFO    ] - Starting trader...
[2025-01-26 14:21:09] [Trader.FARMER_002.ETH-USD-PERP] [INFO    ] - Starting trader...
```

### **Stop the Bot**
Press `Ctrl+C` for graceful shutdown:
```
[2025-01-26 14:25:10] [ParadexBot] [INFO    ] - Shutting down all traders...
[2025-01-26 14:25:11] [ParadexBot] [INFO    ] - Shutdown complete. Exiting.
```

## 📊 Monitoring & Logs

### **Log Files**
- **Location**: `logs/ParadexBot.log`
- **Rotation**: 10MB files, 5 backups retained
- **Format**: Timestamped with component and level information

### **Key Metrics to Monitor**
- Order placement and cancellation rates
- Position sizes and inventory levels
- VAMP price calculations vs mid-price
- Network latency and connection status

## 🔒 Security Best Practices

### **Critical Security Measures**
1. **Private Key Protection**: Never commit `config/wallets.csv` to version control
2. **Environment Isolation**: Always use testnet before mainnet deployment
3. **Access Control**: Restrict file system permissions on configuration files
4. **Network Security**: Use secure networks and consider VPN for production

### **Git Security**
The `.gitignore` file automatically excludes:
- `*.env` files
- `config/wallets.csv`
- Log files and temporary data

## 🛠️ Troubleshooting

### **Common Issues**

**Dependency Conflicts**
```bash
# If you get import errors, reinstall in correct order:
pip uninstall paradex-py quantpylib
pip install git+https://github.com/sumitabh1710/quantpylib.git
pip install --no-deps paradex-py
```

**Configuration Errors**
```bash
# Check configuration file syntax:
python -c "from src.utils.config_loader import load_main_config; print('Config OK')"
```

**Connection Issues**
- Verify `PARADEX_ENV` setting in `.env`
- Check wallet addresses and private keys
- Ensure sufficient balance for trading

### **Debug Mode**
Enable detailed logging by setting `level: "DEBUG"` in `main_config.yaml`.

## 🔄 Adding New Strategies

1. **Create Strategy Class**: Inherit from `BaseStrategy` in `src/strategies/`
2. **Implement `compute_quotes()`**: Return `(bid_price, bid_size, ask_price, ask_size)`
3. **Register Strategy**: Add to `STRATEGY_CATALOG` in `src/main.py`
4. **Configure**: Use `strategy_name` in `main_config.yaml`

## 📈 Performance Optimization

### **Recommended Settings**
- **Testnet**: `refresh_frequency_ms: 500-1000`
- **Mainnet**: `refresh_frequency_ms: 100-250`
- **High Volume**: Lower `base_spread_bps`, higher `refresh_frequency_ms`
- **Risk Averse**: Higher `inventory_skew_bps`

## ⚠️ Risk Disclaimer

**IMPORTANT**: Automated trading involves substantial risk of loss. This software is provided "as-is" without warranty. Users are responsible for:

- Understanding market risks and position limits
- Proper configuration and testing
- Compliance with applicable regulations
- Monitoring and risk management

**Never trade with funds you cannot afford to lose.**

## 📞 Support & Contributing

- **Issues**: Report bugs via GitHub Issues
- **Documentation**: Contribute improvements to this README
- **Features**: Submit pull requests for new strategies or enhancements

---

