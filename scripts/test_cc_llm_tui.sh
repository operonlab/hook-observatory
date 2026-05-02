#!/bin/zsh
# TUI 自動化測試：在 tmux 開啟 cc-llm $MODEL，送 /smart-search prompt，
# polling 直到結果穩定或 timeout，回報 PASS / FAIL / UNCLEAR / TIMEOUT。
#
# 用法：./test_cc_llm_tui.sh <model_name>

set -uo pipefail

MODEL="${1:?usage: $0 <model_name>}"
TIMEOUT_S="${TIMEOUT_S:-90}"
SAFE_NAME=$(echo "$MODEL" | tr '/' '-' | tr '.' '_')
SESSION="cctest-${SAFE_NAME}-$$"

# 確保 tmux server 在
tmux start-server 2>/dev/null

# 開 detached session（200x50 寬度避免換行），inherit shell 自動 source ~/.zshrc
tmux new-session -d -s "$SESSION" -x 200 -y 50

# 啟動 cc-llm
tmux send-keys -t "$SESSION" "cc-llm $MODEL" Enter

# 等 TUI 就緒（看到 bypass permissions on 字樣或 ❯ prompt，最多 25s）
READY=0
for i in $(seq 1 25); do
  sleep 1
  OUT=$(tmux capture-pane -t "$SESSION" -p 2>/dev/null || true)
  if echo "$OUT" | grep -qE "bypass permissions|Welcome back|cycle\)"; then
    READY=1
    break
  fi
done

if [ "$READY" != "1" ]; then
  tmux kill-session -t "$SESSION" 2>/dev/null
  echo "❌ NO_START · $MODEL · TUI 未在 25s 內啟動"
  exit 1
fi

# 多等 2s 確保 prompt 穩定
sleep 2

# 送測試 prompt
tmux send-keys -t "$SESSION" "/smart-search 今天高雄天氣如何" Enter

# Polling：給 5s grace period 讓 user input echo 出現，然後才開始判斷
sleep 5

# 關鍵：PASS 模式必須是「實際天氣資料」，不能是 user input 的 "高雄" echo。
# 用「天氣資料 marker」：氣溫單位、天氣 emoji、降雨機率、體感，這些不會出現在 prompt 本身
WEATHER_MARKER='°C|⛅|🌧|☀|🌤|🌦|⛈|🌨|降雨機率|體感|多雲時晴|多雲時陰|轉陰|陣雨|氣溫.*度'

START=$(date +%s)
LAST_HASH=""
STABLE=0
RESULT="TIMEOUT"
DETECTED=""
while [ $(($(date +%s) - START)) -lt "$TIMEOUT_S" ]; do
  sleep 1
  OUT=$(tmux capture-pane -t "$SESSION" -S -300 -p 2>/dev/null || true)

  # PASS 判斷可提早（看到天氣資料就確定 OK）
  if echo "$OUT" | grep -qE "$WEATHER_MARKER"; then
    RESULT="PASS"
    DETECTED=$(echo "$OUT" | grep -m1 -E "$WEATHER_MARKER" | cut -c1-100)
    break
  fi
  # FAIL 不提早 break！Claude Code 會自我 retry，要等穩定後才能判定真正 fatal。
  # 只在最後 stable 階段檢查 "API Error" 殘留 + 沒有 weather marker → 才算 FAIL

  # 穩定偵測：尾部 30 行 hash 連 6 次相同 → 認定 idle
  HASH=$(echo "$OUT" | tail -30 | md5)
  if [ "$HASH" = "$LAST_HASH" ]; then
    STABLE=$((STABLE + 1))
    if [ "$STABLE" -ge 6 ]; then
      # Idle 後判定：沒看到 weather marker，看是否有 API Error 殘留
      if echo "$OUT" | grep -q "API Error"; then
        RESULT="FAIL"
        DETECTED=$(echo "$OUT" | grep -m1 "API Error" | cut -c1-150)
      else
        RESULT="UNCLEAR"
        DETECTED=$(echo "$OUT" | tail -8 | tr '\n' ' ' | cut -c1-150)
      fi
      break
    fi
  else
    STABLE=0
    LAST_HASH="$HASH"
  fi
done

# 退出 cc-llm（先 ESC 取消任何輸入，再 /exit）
tmux send-keys -t "$SESSION" Escape
sleep 0.5
tmux send-keys -t "$SESSION" "/exit" Enter
sleep 1.5
tmux kill-session -t "$SESSION" 2>/dev/null

# 報告
ELAPSED=$(($(date +%s) - START))
case "$RESULT" in
  PASS)    echo "✅ PASS · $MODEL · ${ELAPSED}s · $DETECTED" ;;
  FAIL)    echo "❌ FAIL · $MODEL · ${ELAPSED}s · $DETECTED" ;;
  UNCLEAR) echo "⚠️ UNCLEAR · $MODEL · ${ELAPSED}s · $DETECTED" ;;
  TIMEOUT) echo "⏱️ TIMEOUT · $MODEL · ${ELAPSED}s" ;;
esac
