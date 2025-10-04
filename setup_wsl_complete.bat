@echo off
echo ========================================
echo   Complete WSL Setup for Paradex Bot
echo ========================================
echo.

REM Check if WSL is available
wsl --status >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: WSL is not available.
    echo Please install WSL first: wsl --install
    pause
    exit /b 1
)

echo [1/6] Starting Ubuntu WSL...
wsl -d Ubuntu -- bash -c "echo 'Ubuntu is running'"

echo [2/6] Updating packages...
wsl -d Ubuntu -- bash -c "sudo apt update -y"

echo [3/6] Installing Python development tools...
wsl -d Ubuntu -- bash -c "sudo apt install -y python3.12-venv python3-pip build-essential curl git"

echo [4/6] Setting up project environment...
wsl -d Ubuntu -- bash -c "cd /mnt/d/test-github/paradex-market-making-bot && python3 -m venv venv"

echo [5/6] Installing Python dependencies...
wsl -d Ubuntu -- bash -c "cd /mnt/d/test-github/paradex-market-making-bot && source venv/bin/activate && pip install paradex-py aiohttp PyYAML python-dotenv"

echo [6/6] Testing setup and running bot...
wsl -d Ubuntu -- bash -c "cd /mnt/d/test-github/paradex-market-making-bot && source venv/bin/activate && python3 -c 'from paradex_py import ParadexClient, Environment; print(\"✅ Paradex SDK working!\")' && python3 src/wsl_main.py"

echo.
echo Setup completed! Press any key to exit.
pause >nul
