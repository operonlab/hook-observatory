#!/usr/bin/env bash
# debounce-rebalance.sh — client-resized hook 專用 debounce wrapper
#
# 設計：
#   - 250ms debounce 過濾 cmux 0.63.2 focus pane 的 size oscillation
#     （cmux 連續 emit 多個 client_width，要等穩定才動）
#   - 不呼叫 tmux（純 shell + 寫檔），不需 _tmux_call wrapper
#   - resize 邏輯委派給 rebalance.sh（TRIGGER 透過 env 傳下去做 log lineage）

set -uo pipefail

: "${TRIGGER:=debounce-direct}"
export TRIGGER

# shellcheck source=./_hook-lib.sh
source ~/workshop/shell/tmux/_hook-lib.sh

TS_FILE=/tmp/tmux-resize.ts

trap 'exit 0' ERR EXIT INT TERM

TS=$(date +%s%N)
echo "$TS" > "$TS_FILE"

sleep 0.25

CUR=$(cat "$TS_FILE" 2>/dev/null || echo "")
if [ "$CUR" != "$TS" ]; then
    # 被更新的 timestamp 取代 → 有更新的 resize event，這個 instance 退場
    exit 0
fi

_log INFO "debounce ok → delegating to rebalance.sh"
# 透過 env propagate trigger lineage
TRIGGER="${TRIGGER}->debounce" exec ~/workshop/shell/tmux/rebalance.sh
