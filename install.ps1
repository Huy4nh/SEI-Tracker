# SEI Project - PowerShell Auto Installer
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "    SEI Project - Auto Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python installation
Write-Host "[1/4] Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Python found: $pythonVersion" -ForegroundColor Green
    } else {
        throw "Python not found"
    }
} catch {
    Write-Host "ERROR: Python not found! Please install Python 3.8+ first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Create virtual environment
Write-Host ""
Write-Host "[2/4] Creating virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "Virtual environment already exists, skipping..." -ForegroundColor Yellow
} else {
    python -m venv venv
    Write-Host "✓ Virtual environment created" -ForegroundColor Green
}

# Activate virtual environment
Write-Host ""
Write-Host "[3/4] Activating virtual environment..." -ForegroundColor Yellow
& "venv\Scripts\Activate.ps1"

# Install dependencies
Write-Host ""
Write-Host "[4/4] Installing dependencies..." -ForegroundColor Yellow
pip install --upgrade pip
pip install -r requirements.txt

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "    Installation completed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To run the project:" -ForegroundColor White
Write-Host "1. Activate virtual environment: venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "2. Set environment variables (see env.example)" -ForegroundColor White
Write-Host "3. Run: python main.py" -ForegroundColor White
Write-Host ""
Read-Host "Press Enter to exit" 