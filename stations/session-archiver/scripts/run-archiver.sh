#!/usr/bin/env bash
# Session Archiver — launchd wrapper with dual fallback.
# Route 1: API call to Workshop Gateway
# Route 2: Direct CLI execution (offline mode)
#
# Modeled after stations/system-monitor/scripts/ pattern.

set -euo pipefail

STATION_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$HOME/.claude/data/session-archiver"
LOG_FILE="$DATA_DIR/run.log"
GATEWAY_URL="${WORKSHOP_GATEWAY_URL:-http://localhost:8800}"

mkdir -p "$DATA_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Route 1: Try API
try_api() {
    log "Route 1: Attempting API call..."
    local response
    response=$(curl -sf -X POST "$GATEWAY_URL/api/session-archive/run" \
        -H "Content-Type: application/json" \
        -d '{"mode": "auto"}' \
        --max-time 300 2>&1) && {
        log "Route 1 OK: $response"
        return 0
    }
    log "Route 1 failed, falling back to offline mode"
    return 1
}

# Route 2: Direct CLI (offline)
try_offline() {
    log "Route 2: Offline mode..."
    cd "$STATION_DIR"

    log "Step 1/2: Scanning sessions..."
    /opt/homebrew/bin/uv run python -m session_archiver scan --json 2>&1 | tee -a "$LOG_FILE"

    log "Step 2/2: Archiving (execute mode with summaries + embeddings)..."
    /opt/homebrew/bin/uv run python -m session_archiver archive --execute --summarize --embed --json 2>&1 | tee -a "$LOG_FILE"

    log "Route 2 complete"
}

# Main
log "=== Session Archiver run started ==="

try_api || try_offline

log "=== Session Archiver run finished ==="
