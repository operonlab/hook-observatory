#!/usr/bin/env bash
set -euo pipefail

session="${1:-$(tmux display-message -p '#{session_name}') }"
session="${session% }"

window_id_by_index() {
  local idx="$1"
  tmux list-windows -t "$session" -F '#{window_index} #{window_id}' | awk -v i="$idx" '$1==i {print $2; exit}'
}

# Keep indexes stable.
tmux set-option -t "$session" renumber-windows off

# Move existing special windows into requested slots when possible.
wid5="$(window_id_by_index 5)"
wid6="$(window_id_by_index 6)"
wid7="$(window_id_by_index 7)"

# If index 7 currently holds mutil-claude variant, move it to 6 when 6 is empty.
if [[ -n "${wid7:-}" && -z "${wid6:-}" ]]; then
  w7_name="$(tmux display-message -p -t "$wid7" '#{window_name}')"
  if [[ "$w7_name" == mutil-claude* ]]; then
    tmux move-window -s "$wid7" -t "${session}:6"
    wid6="$(window_id_by_index 6)"
    wid7=""
  fi
fi

# If index 5 is zsh-like and 7 empty, move 5 -> 7 to reserve 5 as merge.
wid5="$(window_id_by_index 5)"
wid7="$(window_id_by_index 7)"
if [[ -n "${wid5:-}" && -z "${wid7:-}" ]]; then
  w5_name="$(tmux display-message -p -t "$wid5" '#{window_name}')"
  if [[ "$w5_name" == "zsh" || "$w5_name" == "zshM" || "$w5_name" == "zsh-M" ]]; then
    tmux move-window -s "$wid5" -t "${session}:7"
  fi
fi

ensure_named_window() {
  local idx="$1"
  local name="$2"
  local wid
  wid="$(window_id_by_index "$idx")"
  if [[ -z "${wid:-}" ]]; then
    tmux new-window -d -t "${session}:$idx" -n "$name"
    wid="$(window_id_by_index "$idx")"
  fi
  tmux rename-window -t "$wid" "$name"
}

ensure_named_window 1 openclaw
ensure_named_window 2 claude
ensure_named_window 3 codex
ensure_named_window 4 gemini
ensure_named_window 5 merge
ensure_named_window 6 mutil-claude
ensure_named_window 7 zsh

# Keep focus sane.
wid1="$(window_id_by_index 1)"
[[ -n "${wid1:-}" ]] && tmux select-window -t "$wid1" >/dev/null 2>&1 || true

tmux display-message "Normalized window layout: 1 openclaw, 2 claude, 3 codex, 4 gemini, 5 merge, 6 mutil-claude, 7 zsh"
