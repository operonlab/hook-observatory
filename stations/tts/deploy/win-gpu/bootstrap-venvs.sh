#!/usr/bin/env bash
# bootstrap-venvs.sh — 建/重建 tts-trio + tts-qwen3 venv 對齊 lockfile.
#
# 使用：wsl -d Ubuntu bash stations/tts/deploy/win-gpu/bootstrap-venvs.sh

set -uo pipefail

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'

TRIO=/home/joneshong/.venvs/cosyvoice_vllm    # tts-trio (legacy name kept for 既有 deploy)
QWEN=/home/joneshong/.venvs/tts-qwen3

ensure_venv() {
    local path=$1 py=$2
    if [ ! -d "$path" ]; then
        echo "Creating venv $path (python $py)"
        if command -v uv >/dev/null 2>&1; then
            uv venv "$path" --python "$py"
        else
            python$py -m venv "$path"
        fi
    fi
    "$path/bin/python3" -m ensurepip --upgrade >/dev/null 2>&1
    "$path/bin/python3" -m pip install --upgrade pip >/dev/null 2>&1
}

# ---- tts-trio: cosyvoice + indextts(WSL test) + vibevoice ----
echo -e "${Y}=== tts-trio venv ===${N}"
ensure_venv "$TRIO" 3.10
"$TRIO/bin/python3" -m pip install \
    'transformers==4.51.3' \
    'vllm==0.9.0' \
    'accelerate==1.6.0' \
    'torch>=2.4,<2.8' \
    'opencc-python-reimplemented' \
    'pykakasi' \
    'soundfile' \
    'numpy' \
    'safetensors' 2>&1 | tail -3
"$TRIO/bin/python3" -c "
import transformers, vllm, torch
print('  transformers:', transformers.__version__)
print('  vllm        :', vllm.__version__)
print('  torch       :', torch.__version__, 'cuda?', torch.cuda.is_available())
"
echo -e "${G}✓ tts-trio ready${N}"

# ---- tts-qwen3: qwen3tts isolated (transformers main branch for qwen3_tts) ----
echo
echo -e "${Y}=== tts-qwen3 venv ===${N}"
ensure_venv "$QWEN" 3.10
"$QWEN/bin/python3" -m pip install \
    'git+https://github.com/huggingface/transformers.git' \
    'torch>=2.4,<2.8' \
    'accelerate' \
    'soundfile' \
    'opencc-python-reimplemented' \
    'safetensors' \
    'huggingface_hub' 2>&1 | tail -3
"$QWEN/bin/python3" -c "
import transformers, torch
from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES
print('  transformers:', transformers.__version__)
print('  qwen3_tts ok:', 'qwen3_tts' in CONFIG_MAPPING_NAMES)
print('  torch       :', torch.__version__, 'cuda?', torch.cuda.is_available())
"
echo -e "${G}✓ tts-qwen3 ready${N}"

echo
echo -e "${G}=== Both venvs aligned to locked-versions.yaml ===${N}"
echo "Next: restart TTS service to pick up new engine PYTHON paths"
