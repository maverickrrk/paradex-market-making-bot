# WSL Quick Start Guide

## The Problem
Your current Windows setup fails with this error:
```
pywintypes.error: (126, 'LoadLibraryEx', 'The specified module could not be found.')
```

This happens because the StarkNet crypto libraries (`crypto_cpp_py`) can't load their C++ dependencies on Windows.

## The Solution
Use WSL (Windows Subsystem for Linux) with the official Paradex SDK.

## Quick Setup (5 minutes)

### Step 1: Install WSL
Open Windows Terminal as Administrator and run:
```cmd
wsl --install -d Ubuntu
```
Restart your computer when prompted.

### Step 2: Run the Setup Script
1. Open WSL Ubuntu
2. Navigate to your project directory
3. Run the setup script:

```bash
# Make the setup script executable
chmod +x setup_wsl.sh

# Run the setup script
./setup_wsl.sh
```

### Step 3: Launch the Bot
From Windows, double-click `launch_wsl_bot.bat` or run:
```cmd
launch_wsl_bot.bat
```

## What This Gives You

✅ **No more C++ library errors** - Linux handles StarkNet crypto properly  
✅ **Official Paradex SDK** - No more custom authentication workarounds  
✅ **Better performance** - Linux is more stable for trading bots  
✅ **Easy development** - Edit files in Windows, run in WSL  
✅ **Future-proof** - Official SDK will be maintained  

## File Structure

```
Your Project/
├── src/
│   ├── wsl_main.py          # WSL version of main.py
│   ├── core/
│   │   ├── wsl_gateway.py   # WSL gateway using official SDK
│   │   └── wsl_gateway_manager.py
│   └── ...
├── setup_wsl.sh            # WSL setup script
├── launch_wsl_bot.bat      # Windows launcher
├── requirements_wsl.txt    # WSL dependencies
└── WSL_SETUP_GUIDE.md     # Detailed setup guide
```

## Manual Setup (if needed)

If the automated setup doesn't work:

```bash
# 1. Install WSL Ubuntu
wsl --install -d Ubuntu

# 2. Update system
sudo apt update && sudo apt upgrade -y

# 3. Install Python
sudo apt install python3.11 python3.11-venv python3-pip build-essential -y

# 4. Create project directory
mkdir -p ~/paradex-bot
cd ~/paradex-bot

# 5. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 6. Install Paradex SDK
pip install paradex-py aiohttp PyYAML python-dotenv

# 7. Copy your project files
cp -r /mnt/d/test-github/paradex-market-making-bot/* .

# 8. Run the bot
python3 src/wsl_main.py
```

## Troubleshooting

### "WSL not found"
- Make sure WSL is installed: `wsl --status`
- Install Ubuntu: `wsl --install -d Ubuntu`

### "Permission denied"
```bash
chmod +x setup_wsl.sh
chmod +x src/wsl_main.py
```

### "Paradex SDK not found"
```bash
source venv/bin/activate
pip install paradex-py
```

### "Configuration not found"
- Make sure your `config/` directory is copied to WSL
- Check that `wallets.csv` and `main_config.yaml` exist

## Benefits Over Custom Implementation

| Feature | Custom Gateway | WSL + Official SDK |
|---------|----------------|-------------------|
| Authentication | Complex custom JWT | Official SDK handles it |
| Onboarding | Manual implementation | Built-in |
| Maintenance | You maintain it | Paradex maintains it |
| Updates | Manual updates | Automatic with pip |
| Reliability | Custom bugs possible | Battle-tested |
| Windows Issues | C++ library problems | No Windows issues |

## Next Steps

1. **Test the setup**: Run `python3 test_paradex.py` in WSL
2. **Configure your wallet**: Update `config/wallets.csv`
3. **Run the bot**: Use `launch_wsl_bot.bat` from Windows
4. **Monitor logs**: Check `logs/ParadexBotWSL.log`

The bot will now use the official Paradex SDK and avoid all Windows C++ library issues!

