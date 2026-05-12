# install.ps1 — GPU Server setup for Windows with CUDA 12.1
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== GPU Server Installer ===" -ForegroundColor Cyan

# 1. Create virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "[1/3] Creating virtual environment ..." -ForegroundColor Yellow
    python -m venv .venv
} else {
    Write-Host "[1/3] Virtual environment already exists, skipping." -ForegroundColor Green
}

# Activate
& .\.venv\Scripts\Activate.ps1

# 2. Install PyTorch with CUDA 12.1
Write-Host "[2/3] Installing PyTorch with CUDA 12.1 ..." -ForegroundColor Yellow
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 3. Install remaining dependencies
Write-Host "[3/3] Installing application dependencies ..." -ForegroundColor Yellow
pip install transformers accelerate fastapi "uvicorn[standard]" pillow numpy pyyaml

# Verify
Write-Host ""
Write-Host "=== Verifying installation ===" -ForegroundColor Cyan
python -c "import torch; print(f'PyTorch {torch.__version__}  CUDA available: {torch.cuda.is_available()}')"
python -c "import torch; print(f'GPU: {torch.cuda.get_device_name(0)}')" 2>$null

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Green
Write-Host "Start the server with:" -ForegroundColor White
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  python main.py" -ForegroundColor White
