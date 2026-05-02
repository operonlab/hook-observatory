#!/bin/zsh
# End-to-end TUI 測試 v2：等到 model 真正 idle 才判定，並用 LLM-as-Judge 評分。
#
# 用法：./test_cc_llm_e2e.sh <model_name> [<prompt>]
#       ./test_cc_llm_e2e.sh deepseek-v3
#       ./test_cc_llm_e2e.sh kimi-k2.5 "/smart-search 高雄天氣"

set -uo pipefail

MODEL="${1:?usage: $0 <model_name> [<prompt>]}"
PROMPT="${2:-/smart-search 今天高雄天氣如何?不查現有報告 去幫我 web fetch}"
TIMEOUT_S="${TIMEOUT_S:-600}"           # 10 分鐘上限
EFFORT="${CC_EFFORT:-medium}"           # 預設 medium 加速測試
JUDGE_MODEL="${JUDGE_MODEL:-deepseek-v3}"
TRANSCRIPT_DIR="${TRANSCRIPT_DIR:-/tmp/cc-llm-e2e}"

mkdir -p "$TRANSCRIPT_DIR"

SAFE_NAME=$(echo "$MODEL" | tr '/' '-' | tr '.' '_')
SESSION="cce2e-${SAFE_NAME}-$$"
TRANSCRIPT_FILE="$TRANSCRIPT_DIR/${SAFE_NAME}.transcript"

# ── 啟動 tmux session ──
tmux start-server 2>/dev/null
tmux new-session -d -s "$SESSION" -x 220 -y 60

# 啟 cc-llm with effort
tmux send-keys -t "$SESSION" "CC_EFFORT='$EFFORT' cc-llm '$MODEL'" Enter

# 等 TUI 就緒（最多 25s）
READY=0
for i in $(seq 1 25); do
  sleep 1
  if tmux capture-pane -t "$SESSION" -p 2>/dev/null | grep -qE "bypass permissions|cycle\)"; then
    READY=1; break
  fi
done
[ "$READY" != "1" ] && {
  tmux kill-session -t "$SESSION" 2>/dev/null
  echo "❌ NO_START · $MODEL · TUI 未在 25s 內啟動"
  exit 1
}
sleep 2

# ── 送 prompt ──
START=$(date +%s)
tmux send-keys -t "$SESSION" "$PROMPT" Enter

# ── Polling 直到 model 真的 idle（不看 tool output 提早 break）──
LAST_HASH=""
STABLE=0
TIMEOUT_HIT=1
while [ $(($(date +%s) - START)) -lt "$TIMEOUT_S" ]; do
  sleep 2
  OUT=$(tmux capture-pane -t "$SESSION" -S -2000 -p 2>/dev/null || true)

  # 偵測 idle：tail 50 行 hash 連續 6 次相同（= 12 秒沒新內容）
  HASH=$(echo "$OUT" | tail -50 | md5)
  if [ "$HASH" = "$LAST_HASH" ]; then
    STABLE=$((STABLE + 1))
    if [ "$STABLE" -ge 6 ]; then
      TIMEOUT_HIT=0; break
    fi
  else
    STABLE=0
    LAST_HASH="$HASH"
  fi
done

ELAPSED=$(($(date +%s) - START))

# ── 抓完整 transcript ──
FULL_TRANSCRIPT=$(tmux capture-pane -t "$SESSION" -S -3000 -p 2>/dev/null || true)
echo "$FULL_TRANSCRIPT" > "$TRANSCRIPT_FILE"

# 退出 cc-llm
tmux send-keys -t "$SESSION" Escape
sleep 0.5
tmux send-keys -t "$SESSION" "/exit" Enter
sleep 1.5
tmux kill-session -t "$SESSION" 2>/dev/null

# ── 統計指標 ──
TOOL_CALLS=$(echo "$FULL_TRANSCRIPT" | grep -cE "^⏺ (Bash|Web Search|Fetch|Skill|Read|Write|Edit)" || true)
API_ERRORS=$(echo "$FULL_TRANSCRIPT" | grep -c "API Error" || true)
RETRIES=$(echo "$FULL_TRANSCRIPT" | grep -ciE "(retry|retrying|fallback)" || true)

# ── LLM-as-Judge：整個 pipeline 走 Python（避免 shell unicode 處理踩雷）──
JUDGE_JSON=$(~/.local/bin/python3 - "$JUDGE_MODEL" "$TRANSCRIPT_FILE" <<'PYEOF'
import json, re, sys, urllib.request

judge_model = sys.argv[1]
transcript_path = sys.argv[2]

# 讀 transcript（強制 UTF-8 容錯）
with open(transcript_path, 'rb') as f:
    raw_bytes = f.read()
text = raw_bytes.decode('utf-8', errors='replace')

# Strip ANSI escape + 控制字元
text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
text = ''.join(c for c in text if c == '\n' or c == '\t' or ord(c) >= 32)

# 取末尾 200 行
lines = text.split('\n')[-200:]
transcript = '\n'.join(lines)

system_prompt = """你是 Claude Code transcript 評審。以下 transcript 是某個 model 透過 Claude Code 跑 user prompt 的完整過程。

評分標準（1-5）：
5 = 完整完成 user 請求，回覆有結構，資料正確且 user-friendly
4 = 完成請求但有小瑕疵（一兩次 retry、格式不完美、有效 fallback）
3 = 部分完成（拿到部分資料但沒整理、或回覆品質差）
2 = 嘗試但失敗（持續 retry、hallucinate、答非所問）
1 = 完全失敗（API Error 持續、沒輸出 / off-topic 廢話）

只輸出 JSON（不要任何其他文字）：
{
  "score": <int 1-5>,
  "completed": <bool>,
  "duration_judgment": "<fast|reasonable|slow|very-slow>",
  "key_issues": [<最多 3 個 string>]
}"""

payload = {
    'model': judge_model,
    'messages': [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': f'=== Transcript ===\n{transcript}'}
    ],
    'response_format': {'type': 'json_object'},
    'max_tokens': 500,
    'temperature': 0.0,
}

req = urllib.request.Request(
    'http://127.0.0.1:4000/v1/chat/completions',
    data=json.dumps(payload).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer sk-litellm-local-dev',
    },
    method='POST',
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.load(resp)
    content = result['choices'][0]['message']['content']
    content = re.sub(r'^\s*```(?:json)?\s*', '', content)
    content = re.sub(r'\s*```\s*$', '', content)
    obj = json.loads(content, strict=False)
    print(json.dumps(obj, ensure_ascii=False))
except Exception as e:
    print(json.dumps({
        'score': 0, 'completed': False,
        'duration_judgment': 'error',
        'key_issues': [f'judge call failed: {type(e).__name__}: {str(e)[:120]}']
    }, ensure_ascii=False))
PYEOF
)

# ── 解析 judge 結果 ──
SCORE=$(echo "$JUDGE_JSON" | ~/.local/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('score', 0))")
COMPLETED=$(echo "$JUDGE_JSON" | ~/.local/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('completed', False))")
ISSUES=$(echo "$JUDGE_JSON" | ~/.local/bin/python3 -c "import json,sys; d=json.load(sys.stdin); print(' / '.join(d.get('key_issues', [])[:3]))")

# ── 輸出單行報告 ──
case "$SCORE" in
  5)  EMOJI="🥇" ;;
  4)  EMOJI="✅" ;;
  3)  EMOJI="⚠️" ;;
  2)  EMOJI="❌" ;;
  1)  EMOJI="💀" ;;
  *)  EMOJI="❓" ;;
esac

[ "$TIMEOUT_HIT" = "1" ] && TIMEOUT_TAG="⏱️TIMEOUT(${TIMEOUT_S}s)" || TIMEOUT_TAG="idle@${ELAPSED}s"

printf "%s score=%s · %s · %s · tools=%d errs=%d retries=%d · %s\n" \
  "$EMOJI" "$SCORE" "$MODEL" "$TIMEOUT_TAG" "$TOOL_CALLS" "$API_ERRORS" "$RETRIES" "${ISSUES:-no issues}"
