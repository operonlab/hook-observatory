#!/usr/bin/env bash
# debounce-rebalance.sh — 抑制 cmux 0.63.2 focus pane 時 PTY size oscillation
#                       並主動鎖窗寬 = cw-2 規避 cmux off-by-one render bug
#
# 問題 1（size oscillation）：cmux focus pane 會連續 emit 多個 client_width
# （356→349→328→330→...），tmux 每次都觸發 client-resized hook。若 hook 立刻
# resize，會把 window_width 鎖在中間錯誤的 cw 值。
# → 解法：debounce 250ms 等 cmux size 穩定後才 resize。
#
# 問題 2（off-by-one render bug, 2026-05-07）：cmux 0.63.2 把 PTY col N 的字
# 寫到視窗 col N+1，導致最右 ~2 字 cell 被視窗邊吃掉，tmux 不知情。先前用
# trailing space buffer 救得了 status，救不了 pane content。
# → 解法：tmux.conf set window-size manual，本 script 主動 resize-window -x (cw-2)，
# 讓 tmux 內部寬度永遠比物理視窗少 2 col，cmux 截字截到視窗外不存在的 col。
set -uo pipefail
# 不用 -e：hook 在背景跑，任一 tmux 指令暫時失敗（例如 layout 衝突）不該讓
# 整支腳本 exit 1 觸發 tmux 顯示「returned 1」訊息，迫使少爺 enter 清屏。
trap 'exit 0' ERR EXIT INT TERM

LOG=/tmp/tmux-resize.log
TS_FILE=/tmp/tmux-resize.ts

TS=$(date +%s%N)
echo "$TS" > "$TS_FILE"

sleep 0.25

CUR=$(cat "$TS_FILE" 2>/dev/null || echo "")
if [ "$CUR" != "$TS" ]; then
    exit 0
fi

CW=$(tmux display -p "#{client_width}" 2>/dev/null || echo "")
if [ -z "$CW" ] || [ "$CW" -lt 20 ] 2>/dev/null; then
    echo "[$(date +%H:%M:%S)] DEBOUNCED skip (cw=$CW too small or empty)" >> "$LOG"
    exit 0
fi

# 只在 cmux mode 套 cw-1 / ch-1 補償；other mode 走 tmux 預設
# (window-size latest 自動跟 client，不需手動 resize)
MODE=$(cat /tmp/tmux-client-mode 2>/dev/null || echo "cmux")
TARGET="$CW"   # 預設 = cw（other mode），cmux mode 下覆蓋為 cw-1
if [ "$MODE" = "cmux" ]; then
    TARGET=$((CW - 1))
    CH=$(tmux display -p '#{client_height}' 2>/dev/null || echo "")
    # 注意：不加 -A flag —「-A 設最大 session 寬」會跟 -x 指定值打架
    if [ -n "$CH" ] && [ "$CH" -ge 10 ] 2>/dev/null; then
        tmux resize-window -x "$TARGET" -y $((CH - 1)) 2>/dev/null || true
    else
        tmux resize-window -x "$TARGET" 2>/dev/null || true
    fi
fi
tmux select-layout -E 2>/dev/null || true
WW=$(tmux display -p "#{window_width}" 2>/dev/null || echo "?")
echo "[$(date +%H:%M:%S)] DEBOUNCED rebalance mode=$MODE cw=$CW target=$TARGET ww=$WW" >> "$LOG"
