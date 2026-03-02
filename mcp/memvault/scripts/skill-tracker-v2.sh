#!/usr/bin/env bash
# skill-tracker-v2.sh — PostToolUse hook for Skill invocations
# Triggered by Claude Code PostToolUse (matcher: "Skill")
# V2: POSTs to Core API (localhost:8801), falls back to JSONL

set -u

export PATH="/opt/homebrew/bin:/Users/joneshong/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

JQ="$(command -v jq 2>/dev/null || echo /usr/bin/jq)"
CORE_API_URL="http://localhost:8801"
SPACE_ID="default"
FALLBACK_FILE="${HOME}/Claude/memvault/skill-invocations.jsonl"
LOG_FILE="${HOME}/Claude/memvault/logs/skill-tracker.log"

# ── Helpers ────────────────────────────────────────────────────────────────

_log() {
    local msg="$1"
    local ts
    ts="$(date +%H:%M:%S)"
    mkdir -p "$(dirname "$LOG_FILE")" || true
    printf '[skill-tracker] %s %s\n' "$ts" "$msg" >> "$LOG_FILE" || true
}

_exit() {
    exit 0
}
trap '_exit' EXIT

# ── Read stdin ─────────────────────────────────────────────────────────────

INPUT="$(cat)"

# ── Filter: only process Skill tool calls ──────────────────────────────────

tool_name="$($JQ -r '.tool_name // ""' <<< "$INPUT" 2>/dev/null || true)"
if [[ "$tool_name" != *"Skill"* ]]; then
    exit 0
fi

# ── Extract fields ─────────────────────────────────────────────────────────

skill_name="$($JQ -r '
    .tool_input.skill_name //
    .tool_input.name //
    (.tool_input | to_entries | map(select(.value | type == "string")) | first | .value) //
    "unknown"
' <<< "$INPUT" 2>/dev/null || echo "unknown")"

session_id="$($JQ -r '.session_id // ""' <<< "$INPUT" 2>/dev/null || true)"
cwd="$($JQ -r '.cwd // ""' <<< "$INPUT" 2>/dev/null || true)"
invoked_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# Detect outcome from tool_response
raw_response="$($JQ -r '.tool_response | tostring' <<< "$INPUT" 2>/dev/null || true)"
raw_response_lower="$(printf '%s' "$raw_response" | tr '[:upper:]' '[:lower:]')"
outcome="success"
if [[ "$raw_response_lower" == *"error"* || "$raw_response_lower" == *"failed"* ]]; then
    outcome="failure"
fi

_log "skill='$skill_name' session='$session_id' outcome='$outcome'"

# ── Build POST body ────────────────────────────────────────────────────────

post_body="$($JQ -n \
    --arg skill_name "$skill_name" \
    --arg source_session "$session_id" \
    --arg cwd "$cwd" \
    --arg invoked_at "$invoked_at" \
    --arg outcome "$outcome" \
    '{
        skill_name: $skill_name,
        source_session: $source_session,
        cwd: $cwd,
        invoked_at: $invoked_at,
        outcome: $outcome,
        duration_ms: null
    }' 2>/dev/null || true)"

if [[ -z "$post_body" ]]; then
    _log "ERROR: failed to build POST body, aborting"
    exit 0
fi

# ── Primary path: POST to Core API ────────────────────────────────────────

http_status="$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 5 \
    -X POST \
    -H "Content-Type: application/json" \
    -d "$post_body" \
    "${CORE_API_URL}/api/memvault/kg/skills/invoke?space_id=${SPACE_ID}" \
    2>/dev/null || echo "000")"

if [[ "$http_status" == "201" ]]; then
    _log "API OK (201) skill='$skill_name'"

    # ── Knowledge Flywheel: capture skill output as memory block ─────────
    KNOWLEDGE_SKILLS="smart-search|company-intel|competitive-intel|content-writer|brainstorming|meeting-insights"
    if echo "$skill_name" | grep -qE "^($KNOWLEDGE_SKILLS)$"; then
        # Clean and truncate response
        clean_response="$(printf '%s' "$raw_response" | head -c 2000)"
        resp_len="${#clean_response}"

        if [[ "$resp_len" -gt 200 ]]; then
            topic_preview="$(printf '%s' "$clean_response" | head -c 80 | tr '\n' ' ')"
            block_body="$($JQ -n \
                --arg topic "skill:$skill_name — $topic_preview" \
                --arg content "$clean_response" \
                --arg block_type "skill_knowledge" \
                --argjson tags "[\"skill:$skill_name\", \"auto-captured\", \"knowledge-flywheel\"]" \
                --arg source "skill-tracker" \
                '{topic: $topic, content: $content, block_type: $block_type, tags: $tags, source: $source}' \
                2>/dev/null || true)"

            if [[ -n "$block_body" ]]; then
                block_status="$(curl -s -o /dev/null -w "%{http_code}" \
                    --max-time 5 \
                    -X POST \
                    -H "Content-Type: application/json" \
                    -d "$block_body" \
                    "${CORE_API_URL}/api/memvault/blocks?space_id=${SPACE_ID}" \
                    2>/dev/null || echo "000")"

                if [[ "$block_status" == "201" ]]; then
                    _log "Knowledge captured for skill='$skill_name' ($resp_len chars)"
                else
                    _log "Knowledge capture failed (HTTP $block_status) for skill='$skill_name'"
                fi
            fi
        else
            _log "Skipping knowledge capture — response too short ($resp_len chars)"
        fi
    fi
    # ── End Knowledge Flywheel ────────────────────────────────────────────

    exit 0
fi

_log "API FAIL (status=$http_status), writing to fallback JSONL"

# ── Fallback: JSONL ────────────────────────────────────────────────────────

fallback_record="$($JQ -n \
    --arg skill_name "$skill_name" \
    --arg source_session "$session_id" \
    --arg cwd "$cwd" \
    --arg invoked_at "$invoked_at" \
    --arg outcome "$outcome" \
    '{
        skill_name: $skill_name,
        source_session: $source_session,
        cwd: $cwd,
        invoked_at: $invoked_at,
        outcome: $outcome,
        duration_ms: null,
        ingested: false
    }' 2>/dev/null || true)"

if [[ -n "$fallback_record" ]]; then
    mkdir -p "$(dirname "$FALLBACK_FILE")" || true
    printf '%s\n' "$fallback_record" >> "$FALLBACK_FILE" || true
    _log "JSONL written skill='$skill_name'"
else
    _log "ERROR: failed to build fallback record"
fi
