#!/usr/bin/env bash
# install.sh — GPU Server setup for Linux / WSL with CUDA 12.1
set -euo pipefail

echo "=== GPU Server Installer ==="

# 1. Create virtual environment
if [ ! -d ".venv" ]; then
    echo "[1/3] Creating virtual environment ..."
    python3 -m venv .venv
else
    echo "[1/3] Virtual environment already exists, skipping."
fi

# Activate
source .venv/bin/activate

# 2. Install PyTorch with CUDA 12.1
echo "[2/3] Installing PyTorch with CUDA 12.1 ..."
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 3. Install remaining dependencies
echo "[3/3] Installing application dependencies ..."
pip install transformers accelerate fastapi 'uvicorn[standard]' pillow numpy pyyaml

# Verify
echo ""
echo "=== Verifying installation ==="
python -c "import torch; print(f'PyTorch {torch.__version__}  CUDA available: {torch.cuda.is_available()}')"
python -c "import torch; print(f'GPU: {torch.cuda.get_device_name(0)}')" 2>/dev/null || true

echo ""
echo "=== Installation complete ==="
echo "Start the server with:"
echo "  source .venv/bin/activate"
echo "  python main.py"
