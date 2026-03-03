#!/usr/bin/env bash
# Phase 1: Infrastructure — prerequisites that everything else depends on.
#
# This is the ONLY phase that must run as a standalone shell script,
# because Homebrew and Python aren't available yet.
#
# What it installs:
#   - Xcode Command Line Tools (provides git, make, clang)
#   - Rosetta 2 (Apple Silicon only — needed for some x86 binaries)
#   - Homebrew (package manager)
#
# Usage:
#   bash bootstrap/phase1-infra.sh
#
# After this completes, run:
#   python3 bootstrap/bootstrap.py <snapshot.yaml> --from 2

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[phase1]${NC} $*"; }
warn() { echo -e "${YELLOW}[phase1]${NC} $*"; }
err()  { echo -e "${RED}[phase1]${NC} $*" >&2; }

# --- Xcode Command Line Tools ---
log "Checking Xcode Command Line Tools..."
if xcode-select -p &>/dev/null; then
    log "  Already installed at $(xcode-select -p)"
else
    log "  Installing Xcode CLT (this may take a while)..."
    xcode-select --install
    # Wait for user to complete the GUI installer
    until xcode-select -p &>/dev/null; do
        sleep 5
    done
    log "  Installed."
fi

# --- Rosetta 2 (Apple Silicon only) ---
if [[ "$(uname -m)" == "arm64" ]]; then
    log "Checking Rosetta 2..."
    if /usr/bin/pgrep oahd &>/dev/null || arch -x86_64 /usr/bin/true &>/dev/null 2>&1; then
        log "  Already installed."
    else
        log "  Installing Rosetta 2..."
        softwareupdate --install-rosetta --agree-to-license
        log "  Installed."
    fi
else
    log "Rosetta 2: not needed (Intel Mac)"
fi

# --- Homebrew ---
log "Checking Homebrew..."
if command -v brew &>/dev/null; then
    log "  Already installed at $(command -v brew)"
    log "  Updating..."
    brew update
else
    log "  Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add to PATH for the rest of this script
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    log "  Installed."
fi

# Verify
log ""
log "Phase 1 complete. Verification:"
log "  git:  $(git --version 2>/dev/null || echo 'NOT FOUND')"
log "  brew: $(brew --version 2>/dev/null | head -1 || echo 'NOT FOUND')"
log "  arch: $(uname -m)"
log ""
log "Next: python3 bootstrap/bootstrap.py <snapshot.yaml> --from 2"
