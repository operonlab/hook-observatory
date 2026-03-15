#!/usr/bin/env bash
set -euo pipefail

session="$(tmux display-message -p '#{session_name}')"
max_idx="$(tmux list-windows -t "$session" -F '#{window_index}' | sort -n | tail -n1)"

if [[ -z "${max_idx:-}" || "$max_idx" -lt 8 ]]; then
  next_idx=8
else
  next_idx=$((max_idx + 1))
fi

tmux new-window -t "${session}:$next_idx"
