@echo off
echo ========================================
echo    SEI Project - Auto Installer
echo ========================================
echo.

echo [1/4] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found! Please install Python 3.8+ first.
    pause
    exit /b 1
)
echo ✓ Python found: 
python --version

echo.
echo [2/4] Creating virtual environment...
if exist "venv" (
    echo Virtual environment already exists, skipping...
) else (
    python -m venv venv
    echo ✓ Virtual environment created
)

echo.
echo [3/4] Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo [4/4] Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ========================================
echo    Installation completed!
echo ========================================
echo.
echo To run the project:
echo 1. Activate virtual environment: venv\Scripts\activate.bat
echo 2. Set environment variables (see .env.example)
echo 3. Run: python main.py
echo.
pause 