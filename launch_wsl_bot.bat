@echo off
echo ========================================
echo   Paradex Market Making Bot - WSL Launcher
echo ========================================
echo.

REM Check if WSL is installed
wsl --status >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: WSL is not installed or not running.
    echo Please install WSL first: wsl --install -d Ubuntu
    pause
    exit /b 1
)

echo [1/4] Checking WSL Ubuntu installation...
wsl -d Ubuntu -- echo "WSL Ubuntu is available" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Ubuntu is not installed in WSL.
    echo Please install Ubuntu: wsl --install -d Ubuntu
    pause
    exit /b 1
)

echo [2/4] Copying project files to WSL...
wsl -d Ubuntu -- mkdir -p ~/paradex-bot
wsl -d Ubuntu -- cp -r /mnt/d/test-github/paradex-market-making-bot/* ~/paradex-bot/ 2>nul

echo [3/4] Setting up Python environment in WSL...
wsl -d Ubuntu -- bash -c "cd ~/paradex-bot && python3.11 -m venv venv 2>/dev/null || python3 -m venv venv"

echo [4/4] Installing dependencies and running bot...
wsl -d Ubuntu -- bash -c "cd ~/paradex-bot && source venv/bin/activate && pip install -q paradex-py aiohttp PyYAML python-dotenv && python3 src/main.py"

echo.
echo Bot execution completed. Press any key to exit.
pause >nul
