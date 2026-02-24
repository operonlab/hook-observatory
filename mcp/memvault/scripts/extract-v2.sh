#!/usr/bin/env bash
# KAS Memory V2 — extraction pipeline with Core API backend
# Same dual-LLM extraction as V1, but writes to PostgreSQL via memvault Core API
# instead of markdown files.
#
# Pipeline: transcript → Gemini Flash extraction → Haiku refinement → Core API POST
# Fallback: if Core API is unreachable, falls back to V1 .md file writing.

set -euo pipefail

# ---------------------------------------------------------------------------
# 0. Configuration & logging
# ---------------------------------------------------------------------------
LOG_DIR="$HOME/Claude/kas-memory/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/extract-v2.log"
exec 2> >(tee -a "$LOG_FILE" >&2)
echo "" >> "$LOG_FILE"
echo "[kas-memory-v2] ====== $(date '+%Y-%m-%d %H:%M:%S') ======" >&2

# Core API config
MEMVAULT_API_URL="${MEMVAULT_API_URL:-http://localhost:8800}"
KAS_SPACE_ID="${KAS_SPACE_ID:-default}"

# V1 fallback paths (used when Core API is down)
V1_MEMORIES_DIR="${MEMORIES_DIR:-$HOME/Claude/kas-memory/memories}"
V1_TAGS_IDX="$(dirname "$V1_MEMORIES_DIR")/tags.idx"

# ---------------------------------------------------------------------------
# 1. Read stdin JSON and extract fields
# ---------------------------------------------------------------------------
INPUT_JSON="$(cat)"

SESSION_ID="$(echo "$INPUT_JSON" | jq -r '.session_id // empty')"
TRANSCRIPT_PATH="$(echo "$INPUT_JSON" | jq -r '.transcript_path // empty')"
CWD="$(echo "$INPUT_JSON" | jq -r '.cwd // empty')"

if [[ -z "$SESSION_ID" || -z "$TRANSCRIPT_PATH" ]]; then
  echo "[kas-memory-v2] Missing session_id or transcript_path, skipping." >&2
  exit 0
fi

if [[ ! -f "$TRANSCRIPT_PATH" ]]; then
  echo "[kas-memory-v2] Transcript file not found: $TRANSCRIPT_PATH" >&2
  exit 0
fi

echo "[kas-memory-v2] Processing session $SESSION_ID ..." >&2

# ---------------------------------------------------------------------------
# 2. Read JSONL transcript, filter user/assistant messages
# ---------------------------------------------------------------------------
CONVERSATION="$(jq -r '
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
  echo "[kas-memory-v2] No conversation content found, skipping." >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# 3. Count message pairs — skip if fewer than 3 exchanges
# ---------------------------------------------------------------------------
USER_COUNT="$(echo "$CONVERSATION" | grep -c '^USER: ' || true)"
ASSISTANT_COUNT="$(echo "$CONVERSATION" | grep -c '^ASSISTANT: ' || true)"

if [[ "$USER_COUNT" -lt 3 ]] || [[ "$ASSISTANT_COUNT" -lt 3 ]]; then
  PAIR_COUNT=$(( USER_COUNT < ASSISTANT_COUNT ? USER_COUNT : ASSISTANT_COUNT ))
  echo "[kas-memory-v2] Only $PAIR_COUNT exchange(s), skipping (need >= 3)." >&2
  exit 0
fi

echo "[kas-memory-v2] Found $USER_COUNT user + $ASSISTANT_COUNT assistant messages." >&2

# ---------------------------------------------------------------------------
# 4. Truncate conversation to last ~30000 chars
# ---------------------------------------------------------------------------
CONV_LEN="${#CONVERSATION}"
if [[ "$CONV_LEN" -gt 30000 ]]; then
  CONVERSATION="${CONVERSATION: -30000}"
  CONVERSATION="$(echo "$CONVERSATION" | tail -n +2)"
  echo "[kas-memory-v2] Truncated conversation from $CONV_LEN to ~30000 chars." >&2
fi

# ---------------------------------------------------------------------------
# 5. Build extraction prompt and call LLM
# ---------------------------------------------------------------------------
TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"

PROMPT_FILE="$(mktemp)"
REFINE_FILE="$(mktemp)"
trap 'rm -f "$PROMPT_FILE" "$REFINE_FILE"' EXIT

cat > "$PROMPT_FILE" <<PROMPT_EOF
你是對話記憶提煉專家。分析以下 Claude Code 對話 transcript，提取值得長期記住的資訊。

只提取以下類型（按重要性排序）：
1. 失敗的方法 — 嘗試了什麼但沒成功，為什麼
2. 使用者修正 — 使用者糾正了 AI 的什麼錯誤
3. 決策記錄 — 為什麼選了 A 而不是 B
4. 溝通偏好 — 使用者的語言習慣、偏好
5. 技術洞察 — workaround、gotcha、best practice
6. 共同成果 — 一起完成了什麼重要的事
7. 最近關注 — 使用者最近在研究或關心什麼

忽略：簡單檔案讀寫、常規 git 操作、trivial 問答。

如果沒有值得記住的內容，只回傳 "SKIP"（不要加其他文字）。

否則，用以下格式回傳（嚴格遵守，每個欄位一行）：
## Session: ${SESSION_ID} (${TIMESTAMP})
**Topic**: [簡短主題，10字以內]
**Type**: [只選一個最主要的: failed-approach | user-correction | decision | communication | technical | achievement | recent-focus]
**Tags**: [3-8 個小寫標籤，逗號分隔。包括工具名、技術名、概念名。例如: react, zustand, safari-bug, css-grid。禁止使用過於泛泛的單詞標籤如: ai, technical, design, code, tool, system, project, workflow — 必須用複合標籤如: ai-memory, technical-insight, css-design, cli-tool]
**Project**: ${CWD}

- [記憶點 1]
- [記憶點 2]
- [記憶點 N]

---

以下是對話 transcript：

${CONVERSATION}
PROMPT_EOF

# Prevent recall.sh from firing on our internal claude -p calls
export KAS_SKIP_RECALL=1

KAS_LLM="${KAS_LLM:-gemini}"

if [[ "$KAS_LLM" == "gemini" ]]; then
  KAS_MODEL="${KAS_MODEL:-gemini-2.5-flash}"
elif [[ "$KAS_LLM" == "claude" ]]; then
  KAS_MODEL="${KAS_MODEL:-haiku}"
elif [[ "$KAS_LLM" == "codex" ]]; then
  KAS_MODEL="${KAS_MODEL:-}"
fi

echo "[kas-memory-v2] Calling $KAS_LLM (${KAS_MODEL:-default}) for extraction ..." >&2

if [[ "$KAS_LLM" == "gemini" ]]; then
  LLM_OUTPUT="$(cat "$PROMPT_FILE" | gemini -m "$KAS_MODEL" -p "按照以下指示分析對話並提煉記憶：" 2>/dev/null)" || {
    echo "[kas-memory-v2] Gemini call failed (exit $?), skipping." >&2
    exit 0
  }
elif [[ "$KAS_LLM" == "claude" ]]; then
  LLM_OUTPUT="$(claude -p --model "$KAS_MODEL" < "$PROMPT_FILE" 2>/dev/null)" || {
    echo "[kas-memory-v2] Claude call failed (exit $?), skipping." >&2
    exit 0
  }
elif [[ "$KAS_LLM" == "codex" ]]; then
  CODEX_ARGS="--skip-git-repo-check"
  if [[ -n "$KAS_MODEL" ]]; then
    CODEX_ARGS="$CODEX_ARGS -m $KAS_MODEL"
  fi
  LLM_OUTPUT="$(cat "$PROMPT_FILE" | codex exec $CODEX_ARGS 2>/dev/null)" || {
    echo "[kas-memory-v2] Codex call failed (exit $?), skipping." >&2
    exit 0
  }
else
  echo "[kas-memory-v2] Unknown LLM: $KAS_LLM, skipping." >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# 6. Check for SKIP response
# ---------------------------------------------------------------------------
TRIMMED="$(echo "$LLM_OUTPUT" | sed '/^[[:space:]]*$/d' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

if [[ "$TRIMMED" == "SKIP" ]]; then
  echo "[kas-memory-v2] LLM returned SKIP — nothing worth remembering." >&2
  exit 0
fi

if [[ -z "$TRIMMED" ]]; then
  echo "[kas-memory-v2] LLM returned empty response, skipping." >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# 6.5. Refinement pass — Haiku validates, fixes format, improves quality
# ---------------------------------------------------------------------------
KAS_REFINE="${KAS_REFINE:-1}"
KAS_REFINE_MODEL="${KAS_REFINE_MODEL:-haiku}"

if [[ "$KAS_REFINE" == "1" ]]; then
  echo "[kas-memory-v2] Refinement pass: calling Claude ($KAS_REFINE_MODEL) ..." >&2

  cat > "$REFINE_FILE" <<REFINE_EOF
你是記憶品質審查員。以下是從 Claude Code 對話中提煉的記憶草稿。
請審查並改善品質，然後輸出最終版本。

## 審查規則

1. **格式驗證** — 確保有且僅有以下欄位：## Session, **Topic**, **Type**, **Tags**, **Project**, 以及 bullet points
2. **Type 正規化** — 只允許一個值：failed-approach | user-correction | decision | communication | technical | achievement | recent-focus
3. **Tags 品質** — 3-8 個小寫標籤，禁止泛泛單詞（ai, technical, design, code, tool, system, project, workflow），必須用複合標籤（ai-memory, css-design, cli-tool）
4. **記憶點品質** — 每條必須具體可操作，刪除空泛的（如「偏好使用繁體中文」若已是已知事實）
5. **去重** — 合併重複或高度相似的記憶點
6. **精簡** — 總記憶點控制在 3-7 條，寧精不濫

## 輸出格式

如果審查後認為記憶完全不值得保留，只回傳 "SKIP"。

否則直接輸出修正後的完整記憶（不要加解釋、不要加 code fence）：
## Session: ...
**Topic**: ...
**Type**: ...
**Tags**: ...
**Project**: ...

- ...

## 待審查的記憶草稿

${TRIMMED}
REFINE_EOF

  REFINED_OUTPUT="$(claude -p --model "$KAS_REFINE_MODEL" < "$REFINE_FILE" 2>/dev/null)" || {
    echo "[kas-memory-v2] Refinement call failed (exit $?), using raw extraction." >&2
    REFINED_OUTPUT=""
  }

  REFINED_TRIMMED="$(echo "$REFINED_OUTPUT" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  REFINED_FIRST_LINE="$(echo "$REFINED_TRIMMED" | head -1 | tr -d '[:space:]')"

  if [[ "$REFINED_FIRST_LINE" == "SKIP" ]]; then
    echo "[kas-memory-v2] Refinement returned SKIP — Haiku judged not worth keeping." >&2
    exit 0
  fi

  if [[ -n "$REFINED_TRIMMED" ]] && echo "$REFINED_TRIMMED" | grep -q '## Session:'; then
    REFINED_BLOCK="$(echo "$REFINED_TRIMMED" | sed -n '/^## Session:/,$p')"
    if [[ -n "$REFINED_BLOCK" ]]; then
      echo "[kas-memory-v2] Refinement accepted — using Haiku-refined output." >&2
      TRIMMED="$REFINED_BLOCK"
    else
      echo "[kas-memory-v2] Refinement block extraction failed, using raw extraction." >&2
    fi
  else
    echo "[kas-memory-v2] Refinement output invalid, using raw extraction." >&2
  fi
fi

# ---------------------------------------------------------------------------
# 7. Clean output — strip LLM artifacts
# ---------------------------------------------------------------------------
CLEAN_OUTPUT="$(echo "$TRIMMED" | grep -v '^Created execution plan for ' | grep -v '^Expanding hook command:' | grep -v '^Hook execution for ')"
CLEAN_OUTPUT="$(echo "$CLEAN_OUTPUT" | sed '/^```/d')"
CLEAN_OUTPUT="$(echo "$CLEAN_OUTPUT" | sed -E 's/^(\*\*Type\*\*: [a-zA-Z-]+) \|.*/\1/')"

# ---------------------------------------------------------------------------
# 8. Parse LLM output into structured fields
# ---------------------------------------------------------------------------
ENTRY_TOPIC="$(echo "$CLEAN_OUTPUT" | grep '^\*\*Topic\*\*:' | head -1 | sed 's/^\*\*Topic\*\*: //')" || true
ENTRY_TYPE="$(echo "$CLEAN_OUTPUT" | grep '^\*\*Type\*\*:' | head -1 | sed 's/^\*\*Type\*\*: //' | tr -d ' ')" || true
ENTRY_TAGS="$(echo "$CLEAN_OUTPUT" | grep '^\*\*Tags\*\*:' | head -1 | sed 's/^\*\*Tags\*\*: //')" || true
ENTRY_PROJECT="$(echo "$CLEAN_OUTPUT" | grep '^\*\*Project\*\*:' | head -1 | sed 's/^\*\*Project\*\*: //')" || true

# Extract content: everything from first "- " line onwards, excluding trailing "---"
ENTRY_CONTENT="$(echo "$CLEAN_OUTPUT" | sed -n '/^- /,$p' | sed '/^---$/,$d')"
if [[ -z "$ENTRY_CONTENT" ]]; then
  ENTRY_CONTENT="$(echo "$CLEAN_OUTPUT" | sed -n '/^## Session:/,$p')"
fi

if [[ -z "$ENTRY_TOPIC" || -z "$ENTRY_CONTENT" ]]; then
  echo "[kas-memory-v2] Failed to parse LLM output — missing topic or content, skipping." >&2
  exit 0
fi

# Map V1 free-form types to V2 block_type enum
case "$ENTRY_TYPE" in
  failed-approach|technical)       V2_TYPE="technical" ;;
  user-correction|communication)   V2_TYPE="preference" ;;
  decision)                        V2_TYPE="decision" ;;
  achievement|recent-focus|insight) V2_TYPE="insight" ;;
  pattern)                         V2_TYPE="pattern" ;;
  *)                               V2_TYPE="technical" ;;
esac

# Build tags JSON array via jq
TAGS_JSON="$(echo "$ENTRY_TAGS" | tr ',' '\n' | sed 's/^ *//;s/ *$//' | grep -v '^$' | jq -R . | jq -s .)"

echo "[kas-memory-v2] Parsed: topic='$ENTRY_TOPIC' type=$ENTRY_TYPE→$V2_TYPE tags=$ENTRY_TAGS" >&2

# ---------------------------------------------------------------------------
# 9. POST to Core API (with V1 fallback)
# ---------------------------------------------------------------------------

# Build JSON payload using jq for safe escaping
PAYLOAD="$(jq -n \
  --arg topic "$ENTRY_TOPIC" \
  --arg content "$ENTRY_CONTENT" \
  --arg block_type "$V2_TYPE" \
  --arg session_id "$SESSION_ID" \
  --arg project "${ENTRY_PROJECT:-$CWD}" \
  --argjson tags "$TAGS_JSON" \
  '{
    topic: $topic,
    content: $content,
    block_type: $block_type,
    session_id: $session_id,
    project: $project,
    tags: $tags,
    source: "session_end"
  }'
)"

# Attempt Core API call
API_RESPONSE_FILE="$(mktemp /tmp/kas-api-resp-XXXXXX.json)"
HTTP_CODE="$(curl -s -o "$API_RESPONSE_FILE" -w '%{http_code}' \
  --connect-timeout 3 \
  --max-time 10 \
  -X POST "${MEMVAULT_API_URL}/api/memvault/blocks?space_id=${KAS_SPACE_ID}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null)" || HTTP_CODE="000"

if [[ "$HTTP_CODE" == "201" ]]; then
  BLOCK_ID="$(jq -r '.id // empty' "$API_RESPONSE_FILE" 2>/dev/null)" || true
  echo "[kas-memory-v2] Block created via Core API (id=$BLOCK_ID)." >&2

  # Sync tags in background (non-critical)
  curl -s --connect-timeout 3 --max-time 5 \
    -X POST "${MEMVAULT_API_URL}/api/memvault/tags/sync?space_id=${KAS_SPACE_ID}" \
    >/dev/null 2>&1 || true

  echo "[kas-memory-v2] Done (via Core API)." >&2
  rm -f "$API_RESPONSE_FILE"
  exit 0
fi

# ---------------------------------------------------------------------------
# 10. Core API failed — fallback to V1 .md file writing
# ---------------------------------------------------------------------------
echo "[kas-memory-v2] Core API returned HTTP $HTTP_CODE, falling back to V1 .md write." >&2
API_ERROR="$(jq -r '.detail // .message // empty' "$API_RESPONSE_FILE" 2>/dev/null)" || true
if [[ -n "$API_ERROR" ]]; then
  echo "[kas-memory-v2] API error: $API_ERROR" >&2
fi
rm -f "$API_RESPONSE_FILE"

# V1 duplicate check
YEAR_MONTH="$(date '+%Y-%m')"
DAY_FILE="$(date '+%Y-%m-%d').md"
TARGET_DIR="$V1_MEMORIES_DIR/$YEAR_MONTH"
TARGET_FILE="$TARGET_DIR/$DAY_FILE"
mkdir -p "$TARGET_DIR"

if [[ -f "$TARGET_FILE" ]] && grep -q "## Session: ${SESSION_ID}" "$TARGET_FILE"; then
  echo "[kas-memory-v2] Session $SESSION_ID already in $DAY_FILE (V1 fallback dedup)." >&2
  exit 0
fi

# V1 communication dedup
BLOCK_TYPE_RAW="$(echo "$CLEAN_OUTPUT" | grep '^\*\*Type\*\*:' | head -1 | sed 's/^\*\*Type\*\*: //' | tr -d ' ')" || true
if [[ "$BLOCK_TYPE_RAW" == "communication" ]]; then
  CONTENT_LOWER="$(echo "$CLEAN_OUTPUT" | tr '[:upper:]' '[:lower:]')"
  if echo "$CONTENT_LOWER" | grep -q '繁體中文' || echo "$CONTENT_LOWER" | grep -q 'traditional.chinese'; then
    RECENT_COMM="$(find "$V1_MEMORIES_DIR" -name '*.md' 2>/dev/null -exec grep -l '繁體中文' {} \; 2>/dev/null | head -1)" || true
    if [[ -n "$RECENT_COMM" ]]; then
      echo "[kas-memory-v2] Communication dedup: language preference already recorded, skipping." >&2
      exit 0
    fi
  fi
fi

# Write to .md (V1 format)
{
  echo ""
  echo "$CLEAN_OUTPUT"
  echo ""
} >> "$TARGET_FILE"

# Write to tags.idx (V1 format)
if [[ -n "$ENTRY_TAGS" ]]; then
  printf '%s\t%s\t%s\t%s\t%s\n' "$YEAR_MONTH/$DAY_FILE" "$SESSION_ID" "$ENTRY_TYPE" "$ENTRY_TOPIC" "$ENTRY_TAGS" >> "$V1_TAGS_IDX"
  echo "[kas-memory-v2] V1 fallback: index entry added to tags.idx" >&2
fi

echo "[kas-memory-v2] V1 fallback: memories saved to $TARGET_FILE" >&2

# V1 auto-promote (only in fallback mode)
KAS_AUTO_PROMOTE="${KAS_AUTO_PROMOTE:-1}"
PROMOTE_SCRIPT="$HOME/Claude/projects/kas-memory/scripts/promote.sh"
if [[ "$KAS_AUTO_PROMOTE" == "1" ]] && [[ -x "$PROMOTE_SCRIPT" ]]; then
  PROMOTE_DRYRUN="$(bash "$PROMOTE_SCRIPT" --dry-run 2>&1)" || true
  if echo "$PROMOTE_DRYRUN" | grep -q "qualifying for promotion"; then
    echo "[kas-memory-v2] V1 fallback: running auto-promote ..." >&2
    bash "$PROMOTE_SCRIPT" 2>&1 | while IFS= read -r line; do
      echo "[kas-memory-v2] promote: $line" >&2
    done || true
  fi
fi

echo "[kas-memory-v2] Done (V1 fallback)." >&2
