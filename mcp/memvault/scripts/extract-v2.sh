#!/usr/bin/env bash
# Memvault — extraction pipeline with Core API backend
# Same dual-LLM extraction as V1, but writes to PostgreSQL via memvault Core API
# instead of markdown files.
#
# Pipeline: transcript → Gemini Flash extraction → Haiku refinement → Core API POST
# Fallback: if Core API is unreachable, falls back to V1 .md file writing.

set -euo pipefail

# ---------------------------------------------------------------------------
# 0. Configuration & logging
# ---------------------------------------------------------------------------
LOG_DIR="$HOME/Claude/memvault/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/extract-v2.log"
exec 2> >(tee -a "$LOG_FILE" >&2)
echo "" >> "$LOG_FILE"
echo "[memvault] ====== $(date '+%Y-%m-%d %H:%M:%S') ======" >&2

# Core API config
MEMVAULT_API_URL="${MEMVAULT_API_URL:-http://localhost:8801}"
MEMVAULT_SPACE_ID="${MEMVAULT_SPACE_ID:-default}"

# JSONL fallback path (used when Core API is down)
FALLBACK_DIR="$HOME/Claude/memvault/extractions"

# ---------------------------------------------------------------------------
# 1. Read stdin JSON and extract fields
# ---------------------------------------------------------------------------
INPUT_JSON="$(cat)"

SESSION_ID="$(echo "$INPUT_JSON" | jq -r '.session_id // empty')"
TRANSCRIPT_PATH="$(echo "$INPUT_JSON" | jq -r '.transcript_path // empty')"
CWD="$(echo "$INPUT_JSON" | jq -r '.cwd // empty')"

if [[ -z "$SESSION_ID" || -z "$TRANSCRIPT_PATH" ]]; then
  echo "[memvault] Missing session_id or transcript_path, skipping." >&2
  exit 0
fi

if [[ ! -f "$TRANSCRIPT_PATH" ]]; then
  echo "[memvault] Transcript file not found: $TRANSCRIPT_PATH" >&2
  exit 0
fi

echo "[memvault] Processing session $SESSION_ID ..." >&2

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
  echo "[memvault] No conversation content found, skipping." >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# 3. Count message pairs — skip if fewer than 3 exchanges
# ---------------------------------------------------------------------------
USER_COUNT="$(echo "$CONVERSATION" | grep -c '^USER: ' || true)"
ASSISTANT_COUNT="$(echo "$CONVERSATION" | grep -c '^ASSISTANT: ' || true)"

if [[ "$USER_COUNT" -lt 3 ]] || [[ "$ASSISTANT_COUNT" -lt 3 ]]; then
  PAIR_COUNT=$(( USER_COUNT < ASSISTANT_COUNT ? USER_COUNT : ASSISTANT_COUNT ))
  echo "[memvault] Only $PAIR_COUNT exchange(s), skipping (need >= 3)." >&2
  exit 0
fi

echo "[memvault] Found $USER_COUNT user + $ASSISTANT_COUNT assistant messages." >&2

# ---------------------------------------------------------------------------
# 4. Truncate conversation to last ~30000 chars
# ---------------------------------------------------------------------------
CONV_LEN="${#CONVERSATION}"
if [[ "$CONV_LEN" -gt 30000 ]]; then
  CONVERSATION="${CONVERSATION: -30000}"
  CONVERSATION="$(echo "$CONVERSATION" | tail -n +2)"
  echo "[memvault] Truncated conversation from $CONV_LEN to ~30000 chars." >&2
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

**Attitudes**: [使用者表達的偏好/信念/原則，格式 category|fact，0-5 條]
  - category 只限: tool_behavior | config | architecture | workflow | preference | technical | naming | syntax | performance
  - 只提取有明確證據的態度，不猜測。沒有就留空

---

以下是對話 transcript：

${CONVERSATION}
PROMPT_EOF

# Prevent recall.sh from firing on our internal claude -p calls
export MEMVAULT_SKIP_RECALL=1

MEMVAULT_LLM="${MEMVAULT_LLM:-gemini}"

if [[ "$MEMVAULT_LLM" == "gemini" ]]; then
  MEMVAULT_MODEL="${MEMVAULT_MODEL:-gemini-2.5-pro}"
elif [[ "$MEMVAULT_LLM" == "claude" ]]; then
  MEMVAULT_MODEL="${MEMVAULT_MODEL:-haiku}"
elif [[ "$MEMVAULT_LLM" == "codex" ]]; then
  MEMVAULT_MODEL="${MEMVAULT_MODEL:-}"
fi

echo "[memvault] Calling $MEMVAULT_LLM (${MEMVAULT_MODEL:-default}) for extraction ..." >&2

if [[ "$MEMVAULT_LLM" == "gemini" ]]; then
  LLM_OUTPUT="$(cat "$PROMPT_FILE" | gemini -m "$MEMVAULT_MODEL" -p "按照以下指示分析對話並提煉記憶：" 2>/dev/null)" || {
    echo "[memvault] Gemini call failed (exit $?), skipping." >&2
    exit 0
  }
elif [[ "$MEMVAULT_LLM" == "claude" ]]; then
  LLM_OUTPUT="$(claude -p --model "$MEMVAULT_MODEL" < "$PROMPT_FILE" 2>/dev/null)" || {
    echo "[memvault] Claude call failed (exit $?), skipping." >&2
    exit 0
  }
elif [[ "$MEMVAULT_LLM" == "codex" ]]; then
  CODEX_ARGS="--skip-git-repo-check"
  if [[ -n "$MEMVAULT_MODEL" ]]; then
    CODEX_ARGS="$CODEX_ARGS -m $MEMVAULT_MODEL"
  fi
  LLM_OUTPUT="$(cat "$PROMPT_FILE" | codex exec $CODEX_ARGS 2>/dev/null)" || {
    echo "[memvault] Codex call failed (exit $?), skipping." >&2
    exit 0
  }
else
  echo "[memvault] Unknown LLM: $MEMVAULT_LLM, skipping." >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# 6. Check for SKIP response
# ---------------------------------------------------------------------------
TRIMMED="$(echo "$LLM_OUTPUT" | sed '/^[[:space:]]*$/d' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

if [[ "$TRIMMED" == "SKIP" ]]; then
  echo "[memvault] LLM returned SKIP — nothing worth remembering." >&2
  exit 0
fi

if [[ -z "$TRIMMED" ]]; then
  echo "[memvault] LLM returned empty response, skipping." >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# 6.5. Refinement pass — Haiku validates, fixes format, improves quality
# ---------------------------------------------------------------------------
MEMVAULT_REFINE="${MEMVAULT_REFINE:-1}"
MEMVAULT_REFINE_MODEL="${MEMVAULT_REFINE_MODEL:-sonnet}"

if [[ "$MEMVAULT_REFINE" == "1" ]]; then
  echo "[memvault] Refinement pass: calling Claude ($MEMVAULT_REFINE_MODEL) ..." >&2

  cat > "$REFINE_FILE" <<REFINE_EOF
你是記憶品質審查員。以下是從 Claude Code 對話中提煉的記憶草稿。
請審查並改善品質，然後輸出最終版本。

## 審查規則

1. **格式驗證** — 確保有且僅有以下欄位：## Session, **Topic**, **Type**, **Tags**, **Project**, bullet points, 以及可選的 **Attitudes**
2. **Type 正規化** — 只允許一個值：failed-approach | user-correction | decision | communication | technical | achievement | recent-focus
3. **Tags 品質** — 3-8 個小寫標籤，禁止泛泛單詞（ai, technical, design, code, tool, system, project, workflow），必須用複合標籤（ai-memory, css-design, cli-tool）
4. **記憶點品質** — 每條必須具體可操作，刪除空泛的（如「偏好使用繁體中文」若已是已知事實）
5. **去重** — 合併重複或高度相似的記憶點
6. **精簡** — 總記憶點控制在 3-7 條，寧精不濫
7. **Attitudes 驗證** — category 必須在以下 9 個枚舉值中：tool_behavior, config, architecture, workflow, preference, technical, naming, syntax, performance。刪除不確定或猜測性態度，刪除 category 不在枚舉中的條目

## 輸出格式

如果審查後認為記憶完全不值得保留，只回傳 "SKIP"。

否則直接輸出修正後的完整記憶（不要加解釋、不要加 code fence）：
## Session: ...
**Topic**: ...
**Type**: ...
**Tags**: ...
**Project**: ...

- ...

**Attitudes**: (可選，0-5 條，格式: category|fact)
  - category|fact

## 待審查的記憶草稿

${TRIMMED}
REFINE_EOF

  REFINED_OUTPUT="$(claude -p --model "$MEMVAULT_REFINE_MODEL" < "$REFINE_FILE" 2>/dev/null)" || {
    echo "[memvault] Refinement call failed (exit $?), using raw extraction." >&2
    REFINED_OUTPUT=""
  }

  REFINED_TRIMMED="$(echo "$REFINED_OUTPUT" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  REFINED_FIRST_LINE="$(echo "$REFINED_TRIMMED" | head -1 | tr -d '[:space:]')"

  if [[ "$REFINED_FIRST_LINE" == "SKIP" ]]; then
    echo "[memvault] Refinement returned SKIP — Haiku judged not worth keeping." >&2
    exit 0
  fi

  if [[ -n "$REFINED_TRIMMED" ]] && echo "$REFINED_TRIMMED" | grep -q '## Session:'; then
    REFINED_BLOCK="$(echo "$REFINED_TRIMMED" | sed -n '/^## Session:/,$p')"
    if [[ -n "$REFINED_BLOCK" ]]; then
      echo "[memvault] Refinement accepted — using Haiku-refined output." >&2
      TRIMMED="$REFINED_BLOCK"
    else
      echo "[memvault] Refinement block extraction failed, using raw extraction." >&2
    fi
  else
    echo "[memvault] Refinement output invalid, using raw extraction." >&2
  fi
fi

# ---------------------------------------------------------------------------
# 7. Clean output — strip LLM artifacts
# ---------------------------------------------------------------------------
CLEAN_OUTPUT="$(echo "$TRIMMED" | grep -v '^Created execution plan for ' | grep -v '^Expanding hook command:' | grep -v '^Hook execution for ')"
CLEAN_OUTPUT="$(echo "$CLEAN_OUTPUT" | sed '/^```/d')"
CLEAN_OUTPUT="$(echo "$CLEAN_OUTPUT" | sed -E 's/^(\*\*Type\*\*: [a-zA-Z-]+) \|.*/\1/')"

# ---------------------------------------------------------------------------
# 7.5. Extract attitudes and POST to Core API
# ---------------------------------------------------------------------------
VALID_CATEGORIES="tool_behavior|config|architecture|workflow|preference|technical|naming|syntax|performance"

ATTITUDE_LINES="$(echo "$CLEAN_OUTPUT" | sed -n '/^\*\*Attitudes\*\*:/,/^\*\*[^A]\|^---$\|^## /p' | grep '^ *- ' | sed 's/^ *- //')" || true

if [[ -n "$ATTITUDE_LINES" ]]; then
  ATTITUDE_COUNT=0
  while IFS= read -r line; do
    ATTITUDE_CATEGORY="$(echo "$line" | cut -d'|' -f1 | sed 's/^ *//;s/ *$//')"
    ATTITUDE_FACT="$(echo "$line" | cut -d'|' -f2- | sed 's/^ *//;s/ *$//')"

    # Validate category against enum
    if ! echo "$ATTITUDE_CATEGORY" | grep -qE "^($VALID_CATEGORIES)$"; then
      echo "[memvault] Attitude skipped — invalid category: $ATTITUDE_CATEGORY" >&2
      continue
    fi

    if [[ -z "$ATTITUDE_FACT" ]]; then
      continue
    fi

    ATTITUDE_PAYLOAD="$(jq -n \
      --arg fact "$ATTITUDE_FACT" \
      --arg category "$ATTITUDE_CATEGORY" \
      --arg source_session "$SESSION_ID" \
      '{fact: $fact, category: $category, source_session: $source_session}')"

    curl -s --connect-timeout 3 --max-time 10 \
      -X POST "${MEMVAULT_API_URL}/api/memvault/kg/attitudes/evolve?space_id=${MEMVAULT_SPACE_ID}" \
      -H "Content-Type: application/json" \
      -d "$ATTITUDE_PAYLOAD" >/dev/null 2>&1 || true

    ATTITUDE_COUNT=$((ATTITUDE_COUNT + 1))
    echo "[memvault] Attitude evolve: [$ATTITUDE_CATEGORY] $ATTITUDE_FACT" >&2
  done <<< "$ATTITUDE_LINES"
  echo "[memvault] $ATTITUDE_COUNT attitude(s) sent to Core API." >&2
fi

# ---------------------------------------------------------------------------
# 8. Parse LLM output into structured fields
# ---------------------------------------------------------------------------
ENTRY_TOPIC="$(echo "$CLEAN_OUTPUT" | grep '^\*\*Topic\*\*:' | head -1 | sed 's/^\*\*Topic\*\*: //')" || true
ENTRY_TYPE="$(echo "$CLEAN_OUTPUT" | grep '^\*\*Type\*\*:' | head -1 | sed 's/^\*\*Type\*\*: //' | tr -d ' ')" || true
ENTRY_TAGS="$(echo "$CLEAN_OUTPUT" | grep '^\*\*Tags\*\*:' | head -1 | sed 's/^\*\*Tags\*\*: //')" || true
ENTRY_PROJECT="$(echo "$CLEAN_OUTPUT" | grep '^\*\*Project\*\*:' | head -1 | sed 's/^\*\*Project\*\*: //')" || true

# Extract content: everything from first "- " line onwards, excluding Attitudes block and trailing "---"
ENTRY_CONTENT="$(echo "$CLEAN_OUTPUT" | sed -n '/^- /,$p' | sed '/^\*\*Attitudes\*\*:/,$d' | sed '/^---$/,$d')"
if [[ -z "$ENTRY_CONTENT" ]]; then
  ENTRY_CONTENT="$(echo "$CLEAN_OUTPUT" | sed -n '/^## Session:/,$p')"
fi

if [[ -z "$ENTRY_TOPIC" || -z "$ENTRY_CONTENT" ]]; then
  echo "[memvault] Failed to parse LLM output — missing topic or content, skipping." >&2
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

echo "[memvault] Parsed: topic='$ENTRY_TOPIC' type=${ENTRY_TYPE} -> ${V2_TYPE} tags=$ENTRY_TAGS" >&2

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
API_RESPONSE_FILE="$(mktemp /tmp/memvault-api-resp-XXXXXX.json)"
HTTP_CODE="$(curl -s -o "$API_RESPONSE_FILE" -w '%{http_code}' \
  --connect-timeout 3 \
  --max-time 10 \
  -X POST "${MEMVAULT_API_URL}/api/memvault/blocks?space_id=${MEMVAULT_SPACE_ID}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null)" || HTTP_CODE="000"

if [[ "$HTTP_CODE" == "201" ]]; then
  BLOCK_ID="$(jq -r '.id // empty' "$API_RESPONSE_FILE" 2>/dev/null)" || true
  echo "[memvault] Block created via Core API (id=$BLOCK_ID)." >&2

  # Sync tags in background (non-critical)
  curl -s --connect-timeout 3 --max-time 5 \
    -X POST "${MEMVAULT_API_URL}/api/memvault/tags/sync?space_id=${MEMVAULT_SPACE_ID}" \
    >/dev/null 2>&1 || true

  echo "[memvault] Done (via Core API)." >&2
  rm -f "$API_RESPONSE_FILE"
  exit 0
fi

# ---------------------------------------------------------------------------
# 10. Core API failed — fallback to JSONL file (graceful degradation)
# ---------------------------------------------------------------------------
echo "[memvault] Core API returned HTTP $HTTP_CODE, falling back to JSONL." >&2
API_ERROR="$(jq -r '.detail // .message // empty' "$API_RESPONSE_FILE" 2>/dev/null)" || true
if [[ -n "$API_ERROR" ]]; then
  echo "[memvault] API error: $API_ERROR" >&2
fi
rm -f "$API_RESPONSE_FILE"

# Write structured JSONL (can be re-ingested when Core API is back)
YEAR_MONTH="$(date '+%Y-%m')"
TODAY="$(date '+%Y-%m-%d')"
FALLBACK_FILE="$FALLBACK_DIR/$YEAR_MONTH/$TODAY.jsonl"
mkdir -p "$FALLBACK_DIR/$YEAR_MONTH"

# Dedup check
if [[ -f "$FALLBACK_FILE" ]] && grep -q "\"session_id\":\"$SESSION_ID\"" "$FALLBACK_FILE"; then
  echo "[memvault] Session $SESSION_ID already in fallback JSONL, skipping." >&2
  exit 0
fi

# Build JSONL entry
FALLBACK_ENTRY="$(jq -n \
  --arg topic "$ENTRY_TOPIC" \
  --arg content "$ENTRY_CONTENT" \
  --arg block_type "$V2_TYPE" \
  --arg session_id "$SESSION_ID" \
  --arg project "${ENTRY_PROJECT:-$CWD}" \
  --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --argjson tags "$TAGS_JSON" \
  '{
    session_id: $session_id,
    topic: $topic,
    content: $content,
    block_type: $block_type,
    project: $project,
    tags: $tags,
    timestamp: $timestamp,
    source: "session_end",
    ingested: false
  }'
)"

echo "$FALLBACK_ENTRY" >> "$FALLBACK_FILE"
echo "[memvault] Fallback: extraction saved to $FALLBACK_FILE" >&2
echo "[memvault] Done (JSONL fallback)." >&2
