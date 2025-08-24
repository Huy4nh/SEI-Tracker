#!/bin/bash

echo "========================================"
echo "    SEI Project - Auto Installer"
echo "========================================"
echo

echo "[1/4] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 not found! Please install Python 3.8+ first."
    exit 1
fi
echo "✓ Python found: $(python3 --version)"

echo
echo "[2/4] Creating virtual environment..."
if [ -d "venv" ]; then
    echo "Virtual environment already exists, skipping..."
else
    python3 -m venv venv
    echo "✓ Virtual environment created"
fi

echo
echo "[3/4] Activating virtual environment..."
source venv/bin/activate

echo
echo "[4/4] Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo
echo "========================================"
echo "    Installation completed!"
echo "========================================"
echo
echo "To run the project:"
echo "1. Activate virtual environment: source venv/bin/activate"
echo "2. Set environment variables (see .env.example)"
echo "3. Run: python main.py"
echo 