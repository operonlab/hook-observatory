#!/usr/bin/env bash
# adapt-client.sh — 根據 detect-client 結果切換 cmux workaround
#
# CMUX 模式：套 cmux 0.63.2 截字 workaround
#   - window-size manual + ww=cw-1 (見 rebalance.sh)
#   - status-format[1] / status-right 末端 2 字 trailing buffer
#
# OTHER 模式（ghostty/iterm2/外部）：撤回 workaround
#   - window-size latest（tmux 自動跟 client_width，無補償）
#   - status-format[1] / status-right 末端 0 字 trailing
#
# 配合 hook：tmux.conf 中 set-hook -g client-attached / client-detached
#
# 設計演進：見 rebalance.sh head comment（共用 _hook-lib.sh）

set -uo pipefail

: "${TRIGGER:=adapt-direct}"
export TRIGGER

# shellcheck source=./_hook-lib.sh
source ~/workshop/shell/tmux/_hook-lib.sh

STATE_FILE=/tmp/tmux-client-mode

# ── Watchdog 20s（含 rebalance.sh 15s + 自身 ~5s tmux 操作）──
WATCHDOG_PID=$(_watchdog 20)
trap 'kill "$WATCHDOG_PID" 2>/dev/null; exit 0' ERR EXIT INT TERM

MODE=$(~/workshop/shell/tmux/detect-client.sh)

# 防重複套用：mode 沒變就 noop
PREV=$(cat "$STATE_FILE" 2>/dev/null || echo "")
if [ "$PREV" = "$MODE" ]; then
    _log INFO "adapt skip (mode unchanged: ${MODE})"
    exit 0
fi
echo "$MODE" > "$STATE_FILE"

trim_trailing() {
    echo "$1" | sed -E 's/[[:space:]]+$//'
}

SF_CUR=$(_tmux_call "show_status_format" show -gv 'status-format[1]')
SF_RC=$?
SR_CUR=$(_tmux_call "show_status_right" show -gv 'status-right')
SR_RC=$?

if [ "$SF_RC" -eq 124 ] || [ "$SR_RC" -eq 124 ]; then
    _log WARN "abort (server unresponsive at show) sf_rc=$SF_RC sr_rc=$SR_RC"
    exit 0
fi

SF_BASE=$(trim_trailing "$SF_CUR")
SR_BASE=$(trim_trailing "$SR_CUR")

case "$MODE" in
    cmux)
        _tmux_call "set_window_size_manual" set -g window-size manual >/dev/null
        _tmux_call "set_status_format_pad2" set -g 'status-format[1]' "${SF_BASE}  " >/dev/null
        _tmux_call "set_status_right_pad2" set -gF 'status-right' "${SR_BASE}  " >/dev/null
        ;;
    *)
        _tmux_call "set_window_size_latest" set -g window-size latest >/dev/null
        _tmux_call "set_status_format_pad0" set -g 'status-format[1]' "${SF_BASE}" >/dev/null
        _tmux_call "set_status_right_pad0" set -gF 'status-right' "${SR_BASE}" >/dev/null
        ;;
esac

# 委派 rebalance.sh（TRIGGER 傳遞 lineage 方便 log 追溯）
TRIGGER="adapt-${TRIGGER}->rebalance" ~/workshop/shell/tmux/rebalance.sh

_log OK "adapt mode=${MODE} prev=${PREV:-none}"
