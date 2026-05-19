#!/usr/bin/env bash
# win-gpu sparse-checkout setup — WSL2 / Git Bash version
#
# 使用（WSL2）：
#   ssh win-gpu wsl bash -lc 'curl ... | bash'   或
#   ssh win-gpu wsl                              # 進 WSL
#   bash setup-sparse-checkout.sh
#
# 等效於 setup-sparse-checkout.ps1，差別只在 path 用 POSIX。

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/JonesHong/workshop.git}"
WORKSHOP_DIR="${WORKSHOP_DIR:-/mnt/c/Users/User/workshop}"
BRANCH="${BRANCH:-feature/tts-station-integration}"

SPARSE_PATHS=(
    "stations/tts"
    "libs/sdk-client"
    "mcp/tts"
    "scripts"
    ".claude/rules"
)

if [ ! -d "$WORKSHOP_DIR/.git" ]; then
    echo "=== Clone workshop (sparse, treeless) ==="
    git clone --filter=blob:none --no-checkout "$REPO_URL" "$WORKSHOP_DIR"
    cd "$WORKSHOP_DIR"
    git sparse-checkout init --cone
    git sparse-checkout set "${SPARSE_PATHS[@]}"
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
else
    echo "=== Update existing workshop ==="
    cd "$WORKSHOP_DIR"
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull --ff-only origin "$BRANCH"
    git sparse-checkout set "${SPARSE_PATHS[@]}"
fi

echo
echo "=== Sparse-checkout contents ==="
git sparse-checkout list

echo
echo "=== Disk usage ==="
du -sh "$WORKSHOP_DIR" 2>/dev/null || true

echo
echo "✓ Done. workshop is at $WORKSHOP_DIR on branch $BRANCH"
echo "  Next: bash setup-tts-venv.sh"
