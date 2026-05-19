#!/usr/bin/env bash
# bootstrap-repos.sh — clone + checkout + patch 對齊 lockfile.
# Reproducibility entry-point: 新機器跑這個一條命令就拿到跟 win-gpu 同步的 4 個 repo.
#
# 使用：
#   wsl -d Ubuntu bash stations/tts/deploy/win-gpu/bootstrap-repos.sh
#
# 對應 stations/tts/deploy/locked-versions.yaml.

set -uo pipefail

WORKSHOP_ROOT="${WORKSHOP_ROOT:-/mnt/c/Users/User/workshop}"
PATCH_DIR="${WORKSHOP_ROOT}/stations/tts/deploy/patches"

# ANSI colors
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'

clone_or_update() {
    local name=$1 url=$2 target=$3 commit=$4
    echo -e "${Y}=== ${name} ===${N}"
    if [ ! -d "$target/.git" ]; then
        echo "Cloning $url -> $target"
        git clone "$url" "$target" || return 1
    fi
    cd "$target"
    git fetch origin
    git checkout -q "$commit" || { echo -e "${R}checkout $commit failed${N}"; return 1; }
    echo -e "${G}✓ ${name} pinned to $commit${N}"
}

apply_patches_if_clean() {
    local name=$1 target=$2; shift 2
    cd "$target"
    # Skip if dirty (assume already patched or user mods)
    if [ -n "$(git status --porcelain | grep -v '??')" ]; then
        echo -e "${Y}⚠ $name has uncommitted changes — skipping patch apply${N}"
        return 0
    fi
    for patch in "$@"; do
        local p="$PATCH_DIR/$patch"
        if [ ! -f "$p" ]; then
            echo -e "${R}patch $p not found${N}"; continue
        fi
        echo "Applying $patch"
        git apply --3way "$p" || echo -e "${Y}⚠ patch $patch may have already been applied${N}"
    done
}

# ---- 1. CosyVoice (FunAudioLLM upstream + length_regulator patch) ----
clone_or_update cosyvoice \
    https://github.com/FunAudioLLM/CosyVoice.git \
    "$WORKSHOP_ROOT/lab/cosyvoice" \
    ace7c47f41bbd303aa6bf1ea80e6f9fbd595cd40
apply_patches_if_clean cosyvoice "$WORKSHOP_ROOT/lab/cosyvoice" \
    cosyvoice-length-regulator.patch

# ---- 2. IndexTTS-2 (index-tts upstream) ----
clone_or_update indextts \
    https://github.com/index-tts/index-tts.git \
    "$WORKSHOP_ROOT/lab/indextts" \
    bde7d0bdf0bd36a7d6df9783e49c696c6bcc014d

# ---- 3. VibeVoice (JonesHong fork; defends against community-fork disappearance) ----
clone_or_update vibevoice \
    https://github.com/JonesHong/VibeVoice.git \
    "$HOME/VibeVoice" \
    493b186f5b973477cadab0f93f4a5dd290cc9125

# ---- Qwen3TTS — model only, no source repo. See bootstrap-models.sh ----

echo
echo -e "${G}=== Repos aligned to locked-versions.yaml ===${N}"
echo "Next: bash bootstrap-venvs.sh"
