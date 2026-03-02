#!/usr/bin/env bash
# recall-v2.sh — Memvault V2 recall script
# Triggered by Claude Code UserPromptSubmit hook.
# Searches Core API (cascade recall → search fallback) and returns plain text context.
#
# stdin: JSON {"session_id", "prompt", "cwd"}
# stdout: Plain text context (or empty for no match)

set -u

export PATH="/opt/homebrew/bin:/Users/joneshong/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

CORE_API_URL="${CORE_API_URL:-http://localhost:8801}"
SPACE_ID="${MEMVAULT_SPACE_ID:-default}"
LOG_DIR="$HOME/Claude/memvault/logs"
LOG_FILE="$LOG_DIR/recall.log"
MAX_PROMPT_LEN=2000
CURL_TIMEOUT=10
JQ="$(command -v jq 2>/dev/null || echo /usr/bin/jq)"
PYTHON="$HOME/.local/bin/python3"

# ── Safety net — ALWAYS exit 0 ───────────────────────────────────────────
safe_exit() { exit 0; }
trap safe_exit EXIT INT TERM

mkdir -p "$LOG_DIR" || true
log() { printf '[recall] %s %s\n' "$(date +%H:%M:%S)" "$*" >> "$LOG_FILE" 2>/dev/null || true; }

# ── Read stdin ───────────────────────────────────────────────────────────
INPUT="$(cat)"
PROMPT="$(printf '%s' "$INPUT" | $JQ -r '.prompt // empty' 2>/dev/null)" || PROMPT=""
SESSION_ID="$(printf '%s' "$INPUT" | $JQ -r '.session_id // empty' 2>/dev/null)" || SESSION_ID=""

if [[ -z "$PROMPT" ]]; then
  log "No prompt, skipping"
  exit 0
fi

# ── Skip conditions ──────────────────────────────────────────────────────
if [[ "${MEMVAULT_SKIP_RECALL:-}" == "1" ]]; then
  log "Skipping — MEMVAULT_SKIP_RECALL=1"
  exit 0
fi

if [[ "$PROMPT" == "<"* ]]; then
  log "Skipping system message"
  exit 0
fi

if [[ ${#PROMPT} -gt $MAX_PROMPT_LEN ]]; then
  log "Skipping long prompt (${#PROMPT} chars)"
  exit 0
fi

log "Session: ${SESSION_ID:-unknown} | Prompt: ${PROMPT:0:80}"

# ── URL-encode the query ─────────────────────────────────────────────────
ENCODED_Q="$($PYTHON -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$PROMPT" 2>/dev/null)" || {
  log "Failed to URL-encode prompt"
  exit 0
}

# ── Primary: Cascade Recall (L2→L1→L0→blocks) ────────────────────────────
CASCADE_URL="${CORE_API_URL}/api/memvault/kg/recall?q=${ENCODED_Q}&top_k=5&space_id=${SPACE_ID}"
CASCADE_RESPONSE="$(curl -s --max-time $CURL_TIMEOUT "$CASCADE_URL" 2>/dev/null)" || CASCADE_RESPONSE=""
CASCADE_STATUS=$?

FORMATTED=""

if [[ -n "$CASCADE_RESPONSE" ]] && printf '%s' "$CASCADE_RESPONSE" | $JQ -e '.layers_searched' >/dev/null 2>&1; then
  # Parse cascade recall result
  LAYERS="$(printf '%s' "$CASCADE_RESPONSE" | $JQ -r '.layers_searched | join(", ")' 2>/dev/null)" || LAYERS=""

  if [[ -n "$LAYERS" ]]; then
    FORMATTED="## 相關記憶（cascade recall: $LAYERS）"

    # Wisdom (L2)
    WISDOM_COUNT="$(printf '%s' "$CASCADE_RESPONSE" | $JQ '.wisdom | length' 2>/dev/null)" || WISDOM_COUNT=0
    if [[ "$WISDOM_COUNT" -gt 0 ]]; then
      FORMATTED="$FORMATTED"$'\n\n'"### Wisdom"
      WISDOM_ITEMS="$(printf '%s' "$CASCADE_RESPONSE" | $JQ -r '.wisdom[]? | "- " + .wisdom + " (confidence: " + .confidence + ")"' 2>/dev/null)" || WISDOM_ITEMS=""
      [[ -n "$WISDOM_ITEMS" ]] && FORMATTED="$FORMATTED"$'\n'"$WISDOM_ITEMS"
    fi

    # Clusters (L1)
    CLUSTER_COUNT="$(printf '%s' "$CASCADE_RESPONSE" | $JQ '.clusters | length' 2>/dev/null)" || CLUSTER_COUNT=0
    if [[ "$CLUSTER_COUNT" -gt 0 ]]; then
      FORMATTED="$FORMATTED"$'\n\n'"### Clusters"
      CLUSTER_ITEMS="$(printf '%s' "$CASCADE_RESPONSE" | $JQ -r '.clusters[]? | "- **" + .name + "** (size: " + (.size|tostring) + "): " + (.summary // "—")' 2>/dev/null)" || CLUSTER_ITEMS=""
      [[ -n "$CLUSTER_ITEMS" ]] && FORMATTED="$FORMATTED"$'\n'"$CLUSTER_ITEMS"
    fi

    # Triples (L0)
    TRIPLE_COUNT="$(printf '%s' "$CASCADE_RESPONSE" | $JQ '.triples | length' 2>/dev/null)" || TRIPLE_COUNT=0
    if [[ "$TRIPLE_COUNT" -gt 0 ]]; then
      FORMATTED="$FORMATTED"$'\n\n'"### Triples"
      TRIPLE_ITEMS="$(printf '%s' "$CASCADE_RESPONSE" | $JQ -r '.triples[]? | "- " + .subject + " --" + .predicate + "--> " + .object' 2>/dev/null)" || TRIPLE_ITEMS=""
      [[ -n "$TRIPLE_ITEMS" ]] && FORMATTED="$FORMATTED"$'\n'"$TRIPLE_ITEMS"
    fi

    # Blocks
    BLOCK_COUNT="$(printf '%s' "$CASCADE_RESPONSE" | $JQ '.blocks | length' 2>/dev/null)" || BLOCK_COUNT=0
    if [[ "$BLOCK_COUNT" -gt 0 ]]; then
      FORMATTED="$FORMATTED"$'\n\n'"### Memory Blocks"
      BLOCK_ITEMS="$(printf '%s' "$CASCADE_RESPONSE" | $JQ -r '.blocks[]? | "- **" + (.topic // "untitled") + "**: " + (.content[:200] // "—") + (if (.tags | length) > 0 then " (tags: " + (.tags | join(", ")) + ")" else "" end)' 2>/dev/null)" || BLOCK_ITEMS=""
      [[ -n "$BLOCK_ITEMS" ]] && FORMATTED="$FORMATTED"$'\n'"$BLOCK_ITEMS"
    fi

    log "Cascade recall: $LAYERS ($WISDOM_COUNT wisdom, $CLUSTER_COUNT clusters, $TRIPLE_COUNT triples, $BLOCK_COUNT blocks)"
  fi
fi

# ── Fallback: simple search if cascade returned nothing ───────────────────
if [[ -z "$FORMATTED" ]]; then
  SEARCH_URL="${CORE_API_URL}/api/memvault/search?q=${ENCODED_Q}&top_k=5&space_id=${SPACE_ID}"
  SEARCH_RESPONSE="$(curl -s --max-time $CURL_TIMEOUT "$SEARCH_URL" 2>/dev/null)" || SEARCH_RESPONSE=""

  if [[ -n "$SEARCH_RESPONSE" ]] && printf '%s' "$SEARCH_RESPONSE" | $JQ -e '.[0]' >/dev/null 2>&1; then
    RESULT_COUNT="$(printf '%s' "$SEARCH_RESPONSE" | $JQ 'length' 2>/dev/null)" || RESULT_COUNT=0
    if [[ "$RESULT_COUNT" -gt 0 ]]; then
      FORMATTED="## 相關記憶（search: $RESULT_COUNT results）"
      SEARCH_ITEMS="$(printf '%s' "$SEARCH_RESPONSE" | $JQ -r '.[]? | .block | "- **" + (.topic // "untitled") + "**: " + (.content[:200] // "—") + (if (.tags | length) > 0 then " (tags: " + (.tags | join(", ")) + ")" else "" end)' 2>/dev/null)" || SEARCH_ITEMS=""
      [[ -n "$SEARCH_ITEMS" ]] && FORMATTED="$FORMATTED"$'\n'"$SEARCH_ITEMS"
      log "Search fallback: $RESULT_COUNT results"
    fi
  fi
fi

# ── No results ────────────────────────────────────────────────────────────
if [[ -z "$FORMATTED" ]]; then
  log "No results from API"
  exit 0
fi

# ── Output formatted text ────────────────────────────────────────────────
echo "$FORMATTED"

# ── Skill suggestion ─────────────────────────────────────────────────────
TRIGGERS_FILE="$HOME/.claude/data/skill-index/triggers.json"
if [[ -f "$TRIGGERS_FILE" ]]; then
  SKILL_MATCHES="$($PYTHON -c "
import json,sys
try:
    triggers = json.load(open(sys.argv[2]))
    prompt = sys.argv[1].lower()
    matches = [s['name'] for s in triggers if any(t.lower() in prompt for t in s.get('triggers',[]))]
    if matches:
        print(','.join(matches[:3]))
except: pass
" "$PROMPT" "$TRIGGERS_FILE" 2>/dev/null)" || SKILL_MATCHES=""

  if [[ -n "$SKILL_MATCHES" ]]; then
    SKILL_LIST="$(echo "$SKILL_MATCHES" | tr ',' ', ')"
    echo ""
    echo "建議使用的 Skills: $SKILL_LIST"
    log "Skill suggestions: $SKILL_LIST"
  fi
fi

log "Done"
