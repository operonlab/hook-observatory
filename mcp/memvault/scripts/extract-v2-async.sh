#!/usr/bin/env bash
# extract-v2-async.sh — Async wrapper for memvault V2 extraction
# Triggered by Claude Code SessionEnd hook.
# Captures hook input, backgrounds extract-v2.sh + extract-triples.sh, exits immediately.
#
# Pipeline:
#   1. extract-v2.sh   — Memory block extraction (Gemini Flash + Haiku refinement → Core API)
#   2. extract-triples.sh — KG triple extraction (Gemini Flash → Core API /kg/triples/batch)
#
# Usage in ~/.claude/settings.json:
#   "hooks": { "SessionEnd": [{ "type": "command",
#     "command": "~/workshop/mcp/memvault/scripts/extract-v2-async.sh",
#     "timeout": 5 }] }

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXTRACT_SCRIPT="$SCRIPT_DIR/extract-v2.sh"
TRIPLES_SCRIPT="$SCRIPT_DIR/extract-triples.sh"
LOG_DIR="$HOME/Claude/memvault/logs"
mkdir -p "$LOG_DIR"

# Read hook input from stdin
INPUT_JSON="$(cat)"

# Save to temp file for the background processes
TMPFILE="$(mktemp /tmp/memvault-extract-XXXXXX.json)"
echo "$INPUT_JSON" > "$TMPFILE"

# Launch both pipelines in background (parallel)
(
  # Unset CLAUDECODE to allow claude -p calls in background
  unset CLAUDECODE 2>/dev/null || true

  # Memory block extraction
  bash "$EXTRACT_SCRIPT" < "$TMPFILE" >> "$LOG_DIR/extract-v2.log" 2>&1 &
  BLOCK_PID=$!

  # KG triple extraction (runs in parallel)
  if [[ -f "$TRIPLES_SCRIPT" ]]; then
    bash "$TRIPLES_SCRIPT" < "$TMPFILE" >> "$LOG_DIR/extract-triples.log" 2>&1 &
    TRIPLE_PID=$!
    wait "$TRIPLE_PID" || true
  fi

  wait "$BLOCK_PID" || true

  # Digest today's corrections into attitude pipeline (non-blocking, best-effort)
  CORRECTIONS_DIR="$HOME/Claude/memvault/corrections"
  TODAY="$(date '+%Y-%m-%d')"
  YEAR_MONTH="$(date '+%Y-%m')"
  TODAY_CORRECTIONS="$CORRECTIONS_DIR/$YEAR_MONTH/$TODAY.jsonl"
  PIPELINES_DIR="$(cd "$SCRIPT_DIR/../pipelines" 2>/dev/null && pwd)" || true
  PYTHON="$HOME/.local/bin/python3"

  if [[ -f "$TODAY_CORRECTIONS" ]] && [[ -f "$PIPELINES_DIR/attitude_pipeline.py" ]]; then
    "$PYTHON" "$PIPELINES_DIR/attitude_pipeline.py" \
      --input "$TODAY_CORRECTIONS" \
      >> "$LOG_DIR/attitude-digest.log" 2>&1 || true
  fi

  rm -f "$TMPFILE"
) &
disown

# Return immediately — SessionEnd hooks must not block
exit 0
