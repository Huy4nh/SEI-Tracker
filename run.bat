@echo off
echo ========================================
echo    SEI Project - Auto Runner
echo ========================================
echo.

echo [1/3] Checking virtual environment...
if not exist "venv" (
    echo ERROR: Virtual environment not found!
    echo Please run install.bat first.
    pause
    exit /b 1
)

echo [2/3] Activating virtual environment...
call venv\Scripts\activate.bat

echo [3/3] Starting the application...
echo.
echo Starting SEI Telegram Bot...
echo Press Ctrl+C to stop
echo.

python main.py

echo.
echo Application stopped.
pause 