#!/usr/bin/env bash
# ws-session-archive.sh — Daily 5:15AM session scan + archive
#
# Pipeline (sequential):
#   1. scan      — discover all sessions, update DB index
#   2. archive   — compress cold candidates with summaries + embeddings
#
# Logs: ~/.claude/data/session-archiver/run.log

set -u
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

STATION_DIR="$HOME/workshop/stations/session-archiver"
LOG_DIR="$HOME/.claude/data/session-archiver"
LOG_FILE="$LOG_DIR/run.log"

mkdir -p "$LOG_DIR"

log() {
  echo "[session-archive] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

log "========== Daily session archive started =========="

cd "$STATION_DIR"

# Step 1: Scan sessions
log "Step 1/2: Scanning sessions..."
if /opt/homebrew/bin/uv run python -m session_archiver scan --json >> "$LOG_FILE" 2>&1; then
  log "Step 1 OK"
else
  log "Step 1 FAILED (exit $?) — continuing anyway"
fi

# Step 2: Archive (execute mode with summaries + embeddings)
log "Step 2/2: Archiving cold candidates..."
if /opt/homebrew/bin/uv run python -m session_archiver archive --execute --summarize --embed --json >> "$LOG_FILE" 2>&1; then
  log "Step 2 OK"
else
  log "Step 2 FAILED (exit $?) — continuing anyway"
fi

log "========== Daily session archive complete =========="
