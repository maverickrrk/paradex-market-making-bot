#!/bin/bash

# WSL Setup Script for Paradex Market Making Bot
# This script sets up the environment and installs dependencies in WSL

set -e  # Exit on any error

echo "========================================"
echo "  Paradex Market Making Bot - WSL Setup"
echo "========================================"
echo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running in WSL
if ! grep -q Microsoft /proc/version; then
    print_error "This script is designed to run in WSL (Windows Subsystem for Linux)"
    print_error "Please run this script from within WSL Ubuntu"
    exit 1
fi

print_status "Running in WSL environment ✓"

# Update system packages
print_status "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install Python 3.11 and development tools
print_status "Installing Python 3.11 and development tools..."
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip build-essential curl git

# Create project directory
PROJECT_DIR="$HOME/paradex-bot"
print_status "Creating project directory: $PROJECT_DIR"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# Create virtual environment
print_status "Creating Python virtual environment..."
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip
print_status "Upgrading pip..."
pip install --upgrade pip

# Install Paradex SDK and dependencies
print_status "Installing Paradex SDK and dependencies..."
pip install paradex-py aiohttp PyYAML python-dotenv

# Copy project files from Windows (if available)
WINDOWS_PROJECT_PATH="/mnt/d/test-github/paradex-market-making-bot"
if [ -d "$WINDOWS_PROJECT_PATH" ]; then
    print_status "Copying project files from Windows..."
    cp -r "$WINDOWS_PROJECT_PATH"/* .
else
    print_warning "Windows project path not found: $WINDOWS_PROJECT_PATH"
    print_warning "Please copy your project files manually to: $PROJECT_DIR"
fi

# Set proper permissions
print_status "Setting file permissions..."
chmod +x src/wsl_main.py 2>/dev/null || true
chmod -R 755 src/ 2>/dev/null || true

# Test Paradex SDK installation
print_status "Testing Paradex SDK installation..."
python3 -c "
try:
    from paradex_py import ParadexClient, Environment
    print('✅ Paradex SDK imported successfully!')
except ImportError as e:
    print(f'❌ Failed to import Paradex SDK: {e}')
    exit(1)
"

# Create a simple test script
print_status "Creating test script..."
cat > test_paradex.py << 'EOF'
#!/usr/bin/env python3
"""
Simple test script to verify Paradex SDK functionality
"""
import asyncio
from paradex_py import ParadexClient, Environment

async def test_paradex():
    try:
        print("Testing Paradex SDK...")
        
        # Test client creation (without real credentials)
        client = ParadexClient(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            environment=Environment.TESTNET
        )
        
        print("✅ Paradex client created successfully")
        print("✅ WSL setup is working correctly!")
        
    except Exception as e:
        print(f"❌ Error testing Paradex SDK: {e}")
        return False
    
    return True

if __name__ == "__main__":
    asyncio.run(test_paradex())
EOF

chmod +x test_paradex.py

# Run the test
print_status "Running Paradex SDK test..."
python3 test_paradex.py

if [ $? -eq 0 ]; then
    print_status "Setup completed successfully! 🎉"
    echo
    echo "Next steps:"
    echo "1. Copy your wallet configuration to config/wallets.csv"
    echo "2. Update config/main_config.yaml with your settings"
    echo "3. Run the bot with: python3 src/wsl_main.py"
    echo
    echo "Or use the Windows launcher: launch_wsl_bot.bat"
else
    print_error "Setup failed. Please check the error messages above."
    exit 1
fi

