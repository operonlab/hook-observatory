#!/usr/bin/env bash
set -euo pipefail

# Blog auto-translation runner
# Finds zh posts stable for 2+ days without en translation, translates them

BLOG_DIR="/Users/joneshong/blog"
LOG_PREFIX="[blog-translate]"

log() { echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') $*"; }

# Check translate station is running
if ! curl -sf http://127.0.0.1:10205/health > /dev/null 2>&1; then
    log "ERROR: Translate station not running on port 10205"
    # Try to notify
    ~/workshop/scripts/workshop-notify.sh "Blog Translate Failed" "Translate station offline" --category scheduler --severity warning 2>/dev/null || true
    exit 1
fi

cd "$BLOG_DIR"
log "Starting blog translation check..."

# Run the CLI translate --all command
npx tsx cli/blog.ts translate --all 2>&1

log "Translation check complete"
