#!/usr/bin/env bash
# _hook-lib.sh — tmux hook 共用 lib：structured logger + try-catch tmux call + watchdog
#
# Purpose (2026-05-15):
#   1. 防 tmux server 內部 hook callback chain reentrant deadlock
#      （shell-layer mkdir lock 防不住，第 4 次事故對應措施）
#   2. 留 forensic trail：下次卡死時 log 顯示第一個 TIMEOUT 是哪個 call、誰觸發、卡多久
#
# Usage:
#   source ~/workshop/shell/tmux/_hook-lib.sh
#   # TRIGGER 由呼叫者 export 進來（tmux.conf 各 hook 帶上）
#   _log INFO "starting"
#   out=$(_tmux_call "display_cw" display -p '#{client_width}')
#   rc=$?  # 0=ok, 124=timeout, other=tmux error (見 case 分類)
#
# Logger schema（每行）：
#   [HH:MM:SS] [pid=NNNN] [LEVEL] [trig=SOURCE] message
#   LEVEL: INFO / OK / SLOW / WARN / TIMEOUT / FATAL
#
# _tmux_call duration 分類：
#   rc=0   + dur<1s  → 不 log（happy path 已由呼叫者統整 log）
#   rc=0   + dur≥1s  → SLOW（server 壓力警訊）
#   rc=124           → TIMEOUT（server hang 強烈指標 — grep '\[TIMEOUT\]' 一秒定位）
#   其他             → WARN（tmux 回非零，多半是 no session / no client）

: "${TMUX_HOOK_LOG:=/tmp/tmux-resize.log}"
: "${TRIGGER:=unknown}"
: "${TMUX_CALL_TIMEOUT:=2}"

# Structured logger.
# Args: LEVEL message...
_log() {
    local level="$1"; shift
    local msg="$*"
    # tr 把 stderr 多行壓成單行（防 log 被 tmux runtime 多執行緒交錯切碎）
    printf '[%s] [pid=%s] [%s] [trig=%s] %s\n' \
        "$(date +'%H:%M:%S')" "$$" "$level" "$TRIGGER" "$msg" \
        >> "$TMUX_HOOK_LOG" 2>/dev/null || true
}

# _tmux_call <description> <tmux args...>
#   - timeout-wrapped（$TMUX_CALL_TIMEOUT 秒，default 2）
#   - stderr 捕捉到 temp，失敗時 log；成功時丟掉
#   - duration 量到秒（SECONDS 內建變數，秒級對 hook 追溯足夠）
#   - stdout echo 出去（caller 用 $(_tmux_call ...) 接），return code = tmux rc 或 124
#
# 為何不用 set -e / pipefail：bash 在 hook 子程序若 set -e + tmux 失敗會整段 exit，
# 丟掉後續清理；用顯式 rc 分類 + return 才能 graceful。
_tmux_call() {
    local desc="$1"; shift
    local start=$SECONDS
    local stderr_file
    stderr_file=$(mktemp -t tmux-hook-err.XXXXXX 2>/dev/null) \
        || stderr_file="/tmp/tmux-hook-err-$$-$RANDOM.tmp"

    local stdout
    stdout=$(timeout "$TMUX_CALL_TIMEOUT" tmux "$@" 2>"$stderr_file")
    local rc=$?
    local dur=$((SECONDS - start))

    # 把 stderr 壓成單行（去 \n \r、頭 3 行截斷防爆 log）
    local stderr_summary=""
    if [ -s "$stderr_file" ]; then
        stderr_summary=$(head -3 "$stderr_file" 2>/dev/null \
            | tr '\n' '|' | tr -d '\r' | head -c 200)
    fi
    rm -f "$stderr_file"

    case "$rc" in
        0)
            if [ "$dur" -ge 1 ]; then
                _log SLOW "tmux ${desc} dur=${dur}s args='$*'"
            fi
            ;;
        124)
            # 這是 server hang 第一手信號 — log 一定要寫
            _log TIMEOUT "tmux ${desc} HUNG ${dur}s args='$*' stderr='${stderr_summary}'"
            ;;
        *)
            _log WARN "tmux ${desc} rc=${rc} dur=${dur}s args='$*' stderr='${stderr_summary}'"
            ;;
    esac

    printf '%s' "$stdout"
    return "$rc"
}

# _watchdog <seconds>
# Fork 一個 background child（sleep N + kill -TERM $$），return child PID。
# 呼叫者要在 trap 中 kill 這個 PID 以免 sleep 倒計時繼續執行。
# 為何用 -TERM 而非 -KILL：讓 caller 的 trap 能跑 cleanup（rmdir lock 等）。
#
# 為何 fd redirection `</dev/null >/dev/null 2>&1`：
#   被 $(...) command substitution 呼叫時，若 background subshell 還繼承
#   stdout/stderr fd，bash 會等該 fd 關閉才結束 `$(...)` — 也就是 caller
#   `WATCHDOG_PID=$(_watchdog 15)` 會卡整整 15 秒（2026-05-15 實證）。
#   detach fd 讓 background 真正脫離 caller 的 wait 鏈。
_watchdog() {
    local secs="${1:-15}"
    ( sleep "$secs" && {
        # 留 log 標記 watchdog 觸發（這代表 timeout-wrapped 仍堆積 >secs）
        printf '[%s] [pid=%s] [FATAL] [trig=%s] watchdog fired after %ss — caller stuck despite tmux timeouts\n' \
            "$(date +'%H:%M:%S')" "$$" "$TRIGGER" "$secs" \
            >> "$TMUX_HOOK_LOG" 2>/dev/null || true
        kill -TERM "$$" 2>/dev/null
    } ) </dev/null >/dev/null 2>&1 &
    echo $!
}
