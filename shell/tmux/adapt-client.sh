#!/usr/bin/env bash
# adapt-client.sh — 根據 detect-client 結果切換 cmux workaround
#
# CMUX 模式：套 cmux 0.63.2 截字 workaround
#   - window-size manual + ww=cw-1 (見 debounce-rebalance.sh)
#   - status-format[1] / status-right 末端 2 字 trailing buffer
#
# OTHER 模式（ghostty/iterm2/外部）：撤回 workaround
#   - window-size latest（tmux 自動跟 client_width，無補償）
#   - status-format[1] / status-right 末端 0 字 trailing
#
# 配合 hook：tmux.conf 中 set-hook -g client-attached / client-detached
set -uo pipefail
# 防止 hook 失敗訊息「returned 1」leak 到 pane，迫使少爺 enter 清屏
trap 'exit 0' ERR EXIT INT TERM

MODE=$(~/workshop/shell/tmux/detect-client.sh)
STATE_FILE=/tmp/tmux-client-mode
LOG=/tmp/tmux-resize.log

# 防重複套用：mode 沒變就 noop
PREV=$(cat "$STATE_FILE" 2>/dev/null || echo "")
if [ "$PREV" = "$MODE" ]; then
  exit 0
fi
echo "$MODE" > "$STATE_FILE"

# 取當前 status 字串、去末尾空白（保留尾端 #[...] color marker）
trim_trailing() {
  echo "$1" | sed -E 's/[[:space:]]+$//'
}

SF_CUR=$(tmux show -gv 'status-format[1]' 2>/dev/null || echo "")
SR_CUR=$(tmux show -gv 'status-right' 2>/dev/null || echo "")
SF_BASE=$(trim_trailing "$SF_CUR")
SR_BASE=$(trim_trailing "$SR_CUR")

case "$MODE" in
  cmux)
    # 套 cmux workaround
    tmux set -g window-size manual
    CW=$(tmux display -p '#{client_width}' 2>/dev/null || echo "")
    CH=$(tmux display -p '#{client_height}' 2>/dev/null || echo "")
    # 水平 cw-1 補償截字 render bug；垂直 ch-1 讓 Claude Code 認知 pane 矮 1 row，
    # 自動把 3-row input box 往上排，最底 hint 行落在 cmux 物理可見區內
    if [ -n "$CW" ] && [ "$CW" -ge 20 ] && [ -n "$CH" ] && [ "$CH" -ge 10 ] 2>/dev/null; then
      tmux resize-window -x $((CW - 1)) -y $((CH - 1)) 2>/dev/null || true
    elif [ -n "$CW" ] && [ "$CW" -ge 20 ] 2>/dev/null; then
      tmux resize-window -x $((CW - 1)) 2>/dev/null || true
    fi
    # status trailing buffer 2 字
    tmux set -g 'status-format[1]' "${SF_BASE}  "
    tmux set -gF 'status-right' "${SR_BASE}  "
    ;;
  *)
    # 撤回 workaround → 走 tmux 預設行為
    tmux set -g window-size latest
    # 主動 resize 還原為 cw/ch（清掉 cmux mode 殘留的 -1 補償）
    # 否則 wh 會停在 cmux mode 設下的值，window-size latest 要等下次
    # client-resized 才跟新
    CW=$(tmux display -p '#{client_width}' 2>/dev/null || echo "")
    CH=$(tmux display -p '#{client_height}' 2>/dev/null || echo "")
    if [ -n "$CW" ] && [ -n "$CH" ] && [ "$CW" -ge 20 ] && [ "$CH" -ge 10 ] 2>/dev/null; then
      tmux resize-window -x "$CW" -y "$CH" 2>/dev/null || true
    fi
    # status 0 字 trailing
    tmux set -g 'status-format[1]' "${SF_BASE}"
    tmux set -gF 'status-right' "${SR_BASE}"
    ;;
esac

tmux select-layout -E 2>/dev/null || true
WW=$(tmux display -p '#{window_width}' 2>/dev/null || echo "?")
echo "[$(date +%H:%M:%S)] adapt: MODE=$MODE ww=$WW" >> "$LOG"
