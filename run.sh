#!/bin/bash

echo "========================================"
echo "    SEI Project - Auto Runner"
echo "========================================"
echo

echo "[1/3] Checking virtual environment..."
if [ ! -d "venv" ]; then
    echo "ERROR: Virtual environment not found!"
    echo "Please run install.sh first."
    exit 1
fi

echo "[2/3] Activating virtual environment..."
source venv/bin/activate

echo "[3/3] Starting the application..."
echo
echo "Starting SEI Telegram Bot..."
echo "Press Ctrl+C to stop"
echo

python main.py

echo
echo "Application stopped." 