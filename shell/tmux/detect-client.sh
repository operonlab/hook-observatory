#!/usr/bin/env bash
# detect-client.sh — 偵測當前 attached clients 中是否有 cmux
# 規則：「有 cmux 就以 cmux 為準」(保守，避免 cmux client 被截字)
# 回傳 stdout: "cmux" 或 "other"
set -uo pipefail
trap 'echo "other"; exit 0' ERR INT TERM

PIDS=$(tmux list-clients -F '#{client_pid}' 2>/dev/null || true)
[ -z "$PIDS" ] && { echo "other"; exit 0; }

for pid in $PIDS; do
  cur=$pid
  # 追父進程鏈到 root，看是否含 cmux app
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -z "$cur" ] || [ "$cur" = "1" ] || [ "$cur" = "0" ] && break
    info=$(ps -o ppid=,comm= -p "$cur" 2>/dev/null) || break
    [ -z "$info" ] && break
    name=$(echo "$info" | awk '{$1=""; sub(/^ /,""); print}')
    if echo "$name" | grep -qi 'cmux'; then
      echo "cmux"
      exit 0
    fi
    cur=$(echo "$info" | awk '{print $1}' | tr -d ' ')
  done
done

echo "other"
