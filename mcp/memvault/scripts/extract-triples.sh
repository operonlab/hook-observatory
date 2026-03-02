#!/usr/bin/env bash
# Memvault V2 — triple extraction pipeline
# Extracts (Subject, Predicate, Object) triples from session transcripts via Gemini Flash.
# Writes validated triples to Core API (primary) and JSONL fallback.
# Usage: stdin JSON {"session_id","transcript_path","cwd"} OR args: <session_id> <transcript_path>

set -u
export PATH="/opt/homebrew/bin:/Users/joneshong/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export MEMVAULT_SKIP_RECALL=1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/Claude/memvault/logs"
LOG_FILE="$LOG_DIR/extract-triples.log"
# JSONL fallback (used when Core API is unavailable)
TRIPLES_BASE="$HOME/Claude/memvault/triples"
CORRECTIONS_BASE="$HOME/Claude/memvault/corrections"
PROMPT_TEMPLATE="$SCRIPT_DIR/prompts/triple-extraction.txt"
VALIDATOR="$SCRIPT_DIR/validate-triples.py"
JQ="$(command -v jq)"
PYTHON="$HOME/.local/bin/python3"

# Core API settings
CORE_API="${CORE_API_URL:-http://localhost:8801}"
SPACE_ID="${MEMVAULT_SPACE_ID:-default}"
KG_BATCH_URL="$CORE_API/api/memvault/kg/triples/batch"

TEMP_FILE=""
VALIDATE_ERR=""
BATCH_FILE=""
cleanup() {
    [[ -n "$TEMP_FILE"    && -f "$TEMP_FILE"    ]] && rm -f "$TEMP_FILE"    || true
    [[ -n "$VALIDATE_ERR" && -f "$VALIDATE_ERR" ]] && rm -f "$VALIDATE_ERR" || true
    [[ -n "$BATCH_FILE"   && -f "$BATCH_FILE"   ]] && rm -f "$BATCH_FILE"   || true
}
trap 'cleanup; exit 0' EXIT

mkdir -p "$LOG_DIR"
log() { echo "[triples] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE" >&2; }

# ---------------------------------------------------------------------------
# 1. Parse input
# ---------------------------------------------------------------------------
SESSION_ID=""
TRANSCRIPT_PATH=""

if [[ -t 0 ]] && [[ $# -ge 2 ]]; then
  SESSION_ID="$1"
  TRANSCRIPT_PATH="$2"
else
  INPUT_JSON="$(cat)"
  SESSION_ID="$(echo "$INPUT_JSON" | "$JQ" -r '.session_id // empty')"
  TRANSCRIPT_PATH="$(echo "$INPUT_JSON" | "$JQ" -r '.transcript_path // empty')"
fi

if [[ -z "$SESSION_ID" || -z "$TRANSCRIPT_PATH" ]]; then
  log "Missing session_id or transcript_path, skipping."
  exit 0
fi

if [[ ! -f "$TRANSCRIPT_PATH" ]]; then
  log "Transcript not found: $TRANSCRIPT_PATH"
  exit 0
fi

log "Processing session $SESSION_ID ..."

# ---------------------------------------------------------------------------
# 2 & 3. Extract conversation + count exchanges
# ---------------------------------------------------------------------------
CONVERSATION="$("$JQ" -r '
  select(.type == "user" or .type == "assistant") |
  .type as $role |
  (
    if (.message.content | type) == "string" then
      .message.content
    elif (.message.content | type) == "array" then
      [.message.content[] | select(.type == "text") | .text] | join("\n")
    else
      ""
    end
  ) as $text |
  if ($text | length) > 0 then
    (if $role == "user" then "USER" else "ASSISTANT" end) + ": " + $text
  else
    empty
  end
' "$TRANSCRIPT_PATH" 2>/dev/null)" || true

if [[ -z "$CONVERSATION" ]]; then
  log "No conversation content found, skipping."
  exit 0
fi

USER_COUNT="$(echo "$CONVERSATION" | grep -c '^USER: ' || true)"
ASSISTANT_COUNT="$(echo "$CONVERSATION" | grep -c '^ASSISTANT: ' || true)"

if [[ "$USER_COUNT" -lt 3 ]] || [[ "$ASSISTANT_COUNT" -lt 3 ]]; then
  PAIR_COUNT=$(( USER_COUNT < ASSISTANT_COUNT ? USER_COUNT : ASSISTANT_COUNT ))
  log "Only $PAIR_COUNT exchange(s), skipping (need >= 3)."
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. Truncate to 30000 chars
# ---------------------------------------------------------------------------
CONV_LEN="${#CONVERSATION}"
if [[ "$CONV_LEN" -gt 30000 ]]; then
  CONVERSATION="${CONVERSATION: -30000}"
  CONVERSATION="$(echo "$CONVERSATION" | tail -n +2)"
  log "Truncated conversation from $CONV_LEN to ~30000 chars."
fi

# ---------------------------------------------------------------------------
# 5. Build prompt and call Gemini Flash
# ---------------------------------------------------------------------------
TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"

if [[ ! -f "$PROMPT_TEMPLATE" ]]; then
  log "Prompt template not found: $PROMPT_TEMPLATE"
  exit 0
fi

TEMP_FILE="$(mktemp)"

{
  sed "s/\${SESSION_ID}/$SESSION_ID/g; s/\${TIMESTAMP}/$TIMESTAMP/g" "$PROMPT_TEMPLATE"
  echo ""
  echo "$CONVERSATION"
} > "$TEMP_FILE"

TRIPLE_MODEL="${TRIPLE_MODEL:-gemini-2.5-pro}"
log "Calling $TRIPLE_MODEL for triple extraction ..."
RAW_OUTPUT="$(cat "$TEMP_FILE" | gemini -m "$TRIPLE_MODEL" -p "Extract knowledge triples from the conversation below. Output ONLY valid JSON per the instruction." 2>/dev/null)" || {
  log "Gemini call failed (exit $?), skipping."
  exit 0
}

# ---------------------------------------------------------------------------
# 6. Clean output
# ---------------------------------------------------------------------------
CLEAN_OUTPUT="$(echo "$RAW_OUTPUT" \
  | sed '/^```/d' \
  | grep -v '^Created execution plan for ' \
  | grep -v '^Expanding hook command:' \
  | grep -v '^Hook execution for ')"

CLEAN_OUTPUT="$(echo "$CLEAN_OUTPUT" | sed '/^[[:space:]]*$/d' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

if [[ -z "$CLEAN_OUTPUT" ]]; then
  log "Empty response from Gemini, skipping."
  exit 0
fi

# ---------------------------------------------------------------------------
# 7. Validate with validate-triples.py
# ---------------------------------------------------------------------------
VALIDATE_ERR="$(mktemp)"
VALIDATED_JSON="$(echo "$CLEAN_OUTPUT" | "$PYTHON" "$VALIDATOR" 2>"$VALIDATE_ERR")" || {
  VERR="$(cat "$VALIDATE_ERR" 2>/dev/null | head -3)"
  log "Validation failed — error: $VERR"
  log "Validation failed — raw output: $(echo "$CLEAN_OUTPUT" | head -3)"
  rm -f "$VALIDATE_ERR"
  exit 0
}
rm -f "$VALIDATE_ERR"

# ---------------------------------------------------------------------------
# 8. Check for skip
# ---------------------------------------------------------------------------
SKIP_FLAG="$(echo "$VALIDATED_JSON" | "$JQ" -r '.skip // false')"
if [[ "$SKIP_FLAG" == "true" ]]; then
  log "Gemini returned skip=true — nothing worth extracting."
  exit 0
fi

# ---------------------------------------------------------------------------
# 9. Duplicate check (against JSONL fallback store)
# ---------------------------------------------------------------------------
YEAR_MONTH="$(date '+%Y-%m')"
TODAY="$(date '+%Y-%m-%d')"
TRIPLES_DIR="$TRIPLES_BASE/$YEAR_MONTH"
TRIPLES_FILE="$TRIPLES_DIR/$TODAY.jsonl"

mkdir -p "$TRIPLES_DIR"

if [[ -f "$TRIPLES_FILE" ]] && grep -q "\"session_id\":\"$SESSION_ID\"" "$TRIPLES_FILE"; then
  log "Session $SESSION_ID already in triples, skipping duplicate."
  exit 0
fi

# ---------------------------------------------------------------------------
# 10. Build batch payload for Core API
# ---------------------------------------------------------------------------
# Transform validated JSON into batch format: {"triples": [...], "session_id": ..., "topic": ..., "tags": [...]}
BATCH_FILE="$(mktemp /tmp/triples-XXXXXX.json)"
echo "$VALIDATED_JSON" | "$JQ" -c '{
  triples: [.triples[] | {s, p, o, session_id: $sid, topic: $topic, tags: $tags}],
  session_id: $sid,
  topic: $topic,
  tags: $tags
}' \
  --arg sid "$SESSION_ID" \
  --arg topic "$(echo "$VALIDATED_JSON" | "$JQ" -r '.topic // ""')" \
  --argjson tags "$(echo "$VALIDATED_JSON" | "$JQ" '.tags // []')" \
  > "$BATCH_FILE" || true

# ---------------------------------------------------------------------------
# 11. POST to Core API (primary path)
# ---------------------------------------------------------------------------
CORE_API_SUCCESS=false
if [[ -s "$BATCH_FILE" ]]; then
  HTTP_STATUS="$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "${KG_BATCH_URL}?space_id=${SPACE_ID}" \
    -H 'Content-Type: application/json' \
    -d @"$BATCH_FILE" \
    --max-time 15 2>/dev/null)" || HTTP_STATUS="000"

  if [[ "$HTTP_STATUS" == "201" || "$HTTP_STATUS" == "200" ]]; then
    log "Core API: triples saved (HTTP $HTTP_STATUS)"
    CORE_API_SUCCESS=true
  else
    log "Core API unavailable (HTTP $HTTP_STATUS) — falling back to JSONL"
  fi
fi

# ---------------------------------------------------------------------------
# 12. JSONL fallback (graceful degradation)
# ---------------------------------------------------------------------------
SINGLE_LINE="$(echo "$VALIDATED_JSON" | "$JQ" -c '.')"
if [[ "$CORE_API_SUCCESS" == "false" ]]; then
  echo "$SINGLE_LINE" >> "$TRIPLES_FILE"
  log "Fallback: triples saved to $TRIPLES_FILE"
else
  # Also write to JSONL as backup archive even when Core API succeeded
  echo "$SINGLE_LINE" >> "$TRIPLES_FILE"
  log "Archive: triples mirrored to $TRIPLES_FILE"
fi

# ---------------------------------------------------------------------------
# 12.5. Triple counter + threshold trigger for auto-synthesis
# ---------------------------------------------------------------------------
COUNTER_FILE="$HOME/.memvault-triple-counter"
TRIPLE_COUNT="$(echo "$VALIDATED_JSON" | "$JQ" '.triples | length')"

# Read current counter (fallback to 0 if file missing or corrupt)
CURRENT_COUNT=0
if [[ -f "$COUNTER_FILE" ]]; then
  CURRENT_COUNT="$(cat "$COUNTER_FILE" 2>/dev/null | tr -dc '0-9')" || true
  CURRENT_COUNT="${CURRENT_COUNT:-0}"
fi

NEW_COUNT=$((CURRENT_COUNT + TRIPLE_COUNT))
echo "$NEW_COUNT" > "$COUNTER_FILE"
log "Triple counter: $CURRENT_COUNT + $TRIPLE_COUNT = $NEW_COUNT"

SYNTHESIS_THRESHOLD="${SYNTHESIS_THRESHOLD:-30}"
if [[ "$NEW_COUNT" -ge "$SYNTHESIS_THRESHOLD" ]]; then
  log "Threshold reached ($NEW_COUNT >= $SYNTHESIS_THRESHOLD) — triggering auto-synthesis"
  (
    PIPELINES_DIR="$(cd "$SCRIPT_DIR/../pipelines" && pwd)"
    if [[ -f "$PIPELINES_DIR/cluster_pipeline.py" ]]; then
      "$PYTHON" "$PIPELINES_DIR/cluster_pipeline.py" >> "$LOG_DIR/synthesis.log" 2>&1 || true
      if [[ -f "$PIPELINES_DIR/wisdom_pipeline.py" ]]; then
        "$PYTHON" "$PIPELINES_DIR/wisdom_pipeline.py" >> "$LOG_DIR/synthesis.log" 2>&1 || true
      fi
    fi
    echo "0" > "$COUNTER_FILE"
  ) &
  disown
  log "Auto-synthesis launched in background (PID $!)"
fi

# ---------------------------------------------------------------------------
# 13. Extract corrections to corrections JSONL
# ---------------------------------------------------------------------------
CORRECTIONS_DIR="$CORRECTIONS_BASE/$YEAR_MONTH"
CORRECTIONS_FILE="$CORRECTIONS_DIR/$TODAY.jsonl"

CORRECTION_COUNT="$(echo "$VALIDATED_JSON" | "$JQ" '.corrections | length')"
if [[ "$CORRECTION_COUNT" -gt 0 ]]; then
  mkdir -p "$CORRECTIONS_DIR"
  echo "$VALIDATED_JSON" | "$JQ" -c \
    --arg sid "$SESSION_ID" \
    --arg ts "$TIMESTAMP" \
    '.corrections[]? | . + {session_id: $sid, timestamp: $ts}' \
    >> "$CORRECTIONS_FILE"
  log "$CORRECTION_COUNT correction(s) saved to $CORRECTIONS_FILE"
fi

log "Done."
