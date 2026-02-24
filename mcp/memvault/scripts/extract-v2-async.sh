#!/usr/bin/env bash
# extract-v2-async.sh — Async wrapper for memvault V2 extraction
# Triggered by Claude Code SessionEnd hook.
# Captures hook input, backgrounds extract-v2.sh, exits immediately.
#
# Usage in ~/.claude/settings.json:
#   "hooks": { "SessionEnd": [{ "type": "command",
#     "command": "~/workshop/mcp/memvault/scripts/extract-v2-async.sh",
#     "timeout": 5 }] }

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXTRACT_SCRIPT="$SCRIPT_DIR/extract-v2.sh"
LOG_DIR="$HOME/Claude/kas-memory/logs"
mkdir -p "$LOG_DIR"

# Read hook input from stdin
INPUT_JSON="$(cat)"

# Save to temp file for the background process
TMPFILE="$(mktemp /tmp/kas-extract-v2-XXXXXX.json)"
echo "$INPUT_JSON" > "$TMPFILE"

# Launch V2 extraction in background
(
  bash "$EXTRACT_SCRIPT" < "$TMPFILE" >> "$LOG_DIR/extract-v2.log" 2>&1
  rm -f "$TMPFILE"
) &
disown

# Return immediately — SessionEnd hooks must not block
exit 0
