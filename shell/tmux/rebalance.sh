#!/usr/bin/env bash
# rebalance.sh — 把當前 active window resize 為 client size
#
# 設計演進：
#   2026-05-14 v1：atomic mkdir lock 防併發 hook（事故首發後加）
#   2026-05-15 v2：每個 tmux call timeout 2 + 整段 watchdog 15s
#                  （事故第二次重演 9hr，發現 shell mkdir lock 防不住
#                   tmux server 內 hook callback chain 的 reentrant deadlock）
#   2026-05-15 v3：拆 _hook-lib.sh 共用 _log/_tmux_call/_watchdog
#                  （補 structured logger + stderr capture + duration 分類，
#                   下次事故 grep '\[TIMEOUT\]' 即可定位第一個卡住的 call）
#
# 觸發點（TRIGGER 由各 hook 透過環境變數帶入，未帶則為 rebalance-direct）：
#   - debounce-rebalance.sh ← client-resized hook
#   - after-select-window hook
#   - after-new-window hook
#   - prefix-= keybind（手動）
#   - adapt-client.sh 結尾
#   - new_window_from_8.sh 結尾
#
# cmux mode：ww=cw-1, wh=ch-1（補償 cmux 0.63.2 截字 render bug）
# other mode：走 tmux 預設值

set -uo pipefail

# TRIGGER 識別呼叫來源；caller 未 export 則記為 direct
: "${TRIGGER:=rebalance-direct}"
export TRIGGER

# shellcheck source=./_hook-lib.sh
source ~/workshop/shell/tmux/_hook-lib.sh

LOCK_DIR=/tmp/tmux-resize.lock.d

# ── Stale lock cleanup ──
# rebalance 正常 <1s 結束；存在 >5s 必是 SIGKILL 殘留或 watchdog 觸發後 trap 沒清乾淨
if [ -d "$LOCK_DIR" ]; then
    AGE=$(( $(date +%s) - $(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0) ))
    if [ "$AGE" -gt 5 ]; then
        rmdir "$LOCK_DIR" 2>/dev/null || true
        _log WARN "stale lock cleared age=${AGE}s"
    fi
fi

# ── Acquire lock（多 hook 併發只跑一個）──
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    _log INFO "skip lock-held"
    exit 0
fi

# ── Watchdog：tmux call 全卡時 15s 內自殺 ──
WATCHDOG_PID=$(_watchdog 15)
trap 'kill "$WATCHDOG_PID" 2>/dev/null; rmdir "$LOCK_DIR" 2>/dev/null; exit 0' ERR EXIT INT TERM

# ── try-catch 模式：每個 tmux 呼叫透過 _tmux_call，rc 顯式判斷 ──
CW=$(_tmux_call "display_cw" display -p '#{client_width}')
CW_RC=$?
CH=$(_tmux_call "display_ch" display -p '#{client_height}')
CH_RC=$?

# 任何一個 timeout → 不繼續 resize（避免 server 已 hang 還硬塞命令）
if [ "$CW_RC" -eq 124 ] || [ "$CH_RC" -eq 124 ]; then
    _log WARN "abort (server unresponsive at display) cw_rc=$CW_RC ch_rc=$CH_RC"
    exit 0
fi

if [ -z "$CW" ] || [ "$CW" -lt 20 ] 2>/dev/null; then
    _log INFO "skip cw=${CW} too small"
    exit 0
fi
if [ -z "$CH" ] || [ "$CH" -lt 10 ] 2>/dev/null; then
    _log INFO "skip ch=${CH} too small"
    exit 0
fi

MODE=$(cat /tmp/tmux-client-mode 2>/dev/null || echo "cmux")
if [ "$MODE" = "cmux" ]; then
    TX=$((CW - 1))
    TY=$((CH - 1))
else
    TX="$CW"
    TY="$CH"
fi

_tmux_call "resize_window" resize-window -x "$TX" -y "$TY" >/dev/null
RESIZE_RC=$?
_tmux_call "select_layout" select-layout -E >/dev/null
LAYOUT_RC=$?

# 任何 timeout 在這裡 → 後面 display 也不必跑了
if [ "$RESIZE_RC" -eq 124 ] || [ "$LAYOUT_RC" -eq 124 ]; then
    _log WARN "abort (server hung mid-resize) resize_rc=$RESIZE_RC layout_rc=$LAYOUT_RC mode=$MODE target=${TX}x${TY}"
    exit 0
fi

WW=$(_tmux_call "display_ww" display -p '#{window_width}')
WH=$(_tmux_call "display_wh" display -p '#{window_height}')
WIN=$(_tmux_call "display_win" display -p '#{window_index}')

_log OK "rebalance mode=$MODE w=${WIN:-?} cw=${CW}x${CH} target=${TX}x${TY} ww=${WW:-?}x${WH:-?}"
