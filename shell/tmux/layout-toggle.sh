#!/usr/bin/env bash
set -euo pipefail
# layout-toggle.sh — Merge/Unmerge windows + Layout Switch
#
# Usage: layout-toggle.sh grid|cols
#
# 狀態追蹤：
#   @_merged_panes  = "pane_id:orig_name:orig_idx|..."
#   @_layout_mode   = "grid" | "cols"
#   @_merged_host   = 合併前當前 window 的原始名稱

mode="${1:-grid}"

merged=$(tmux show-option -wqv @_merged_panes 2>/dev/null || true)
current_mode=$(tmux show-option -wqv @_layout_mode 2>/dev/null || true)

apply_layout() {
  case "$1" in
    grid) tmux select-layout tiled ;;
    cols) tmux select-layout even-horizontal ;;
  esac
  tmux set-option -w @_layout_mode "$1"
}

if [ -n "$merged" ]; then
  # ═══ 已合併狀態 ═══
  if [ "$current_mode" = "$mode" ]; then
    # ── UNMERGE ──
    IFS='|' read -ra entries <<< "$merged"
    cur_win=$(tmux display-message -p '#{window_id}')

    # Step 1: 先收集所有 pane ID（按視覺位置排序），再逐一 break
    sorted_pids=()
    while read -r _top _left pid; do
      sorted_pids+=("$pid")
    done < <(tmux list-panes -t "$cur_win" -F '#{pane_top} #{pane_left} #{pane_id}' | sort -n -k1 -k2)

    # Step 2: 逐一 break（跳過 host pane）
    for pid in "${sorted_pids[@]}"; do
      orig_name=""
      orig_idx=""
      for entry in "${entries[@]}"; do
        e_pid="${entry%%:*}"
        rest="${entry#*:}"
        e_name="${rest%%:*}"
        e_idx="${rest#*:}"
        if [ "$e_pid" = "$pid" ]; then
          orig_name="$e_name"
          orig_idx="$e_idx"
          break
        fi
      done
      [ -z "$orig_name" ] && continue

      new_win=$(tmux break-pane -dP -s "$pid" -F '#{window_id}')
      tmux rename-window -t "$new_win" "$orig_name"
      # 還原到原始 window 編號
      if [ -n "$orig_idx" ]; then
        tmux move-window -s "$new_win" -t ":${orig_idx}" 2>/dev/null || true
      fi
    done

    # 還原 host window 名稱
    host_name=$(tmux show-option -wqv @_merged_host 2>/dev/null || true)
    if [ -n "$host_name" ]; then
      tmux rename-window "$host_name"
    fi

    # 清除狀態
    tmux set-option -wu @_merged_panes 2>/dev/null || true
    tmux set-option -wu @_layout_mode 2>/dev/null || true
    tmux set-option -wu @_merged_host 2>/dev/null || true
    tmux display-message "Unmerged → windows restored"
  else
    # ── SWITCH LAYOUT ──
    apply_layout "$mode"
    tmux display-message "Switch → $mode"
  fi
else
  # ═══ 未合併 → MERGE ═══
  cur_pane_count=$(tmux list-panes | wc -l | tr -d ' ')
  if [ "$cur_pane_count" -gt 1 ]; then
    tmux display-message "Window has $cur_pane_count panes — merge only from single-pane window"
    exit 0
  fi

  cur_win_idx=$(tmux display-message -p '#{window_index}')
  cur_win_name=$(tmux display-message -p '#{window_name}')

  # 收集其他單 pane window（跳過多 pane window）
  other_wins=()
  while IFS= read -r line; do
    idx="${line%%:*}"
    pcount="${line#*:}"
    [ "$idx" != "$cur_win_idx" ] && [ "$pcount" -eq 1 ] && other_wins+=("$idx")
  done < <(tmux list-windows -F '#{window_index}:#{window_panes}')

  # 不足 3 個 → 自動建新 window（host+1, +2, +3，跳過已佔用）
  if [ ${#other_wins[@]} -lt 3 ]; then
    next_idx=$((cur_win_idx + 1))
    while [ ${#other_wins[@]} -lt 3 ]; do
      while tmux list-windows -F '#{window_index}' | grep -qx "$next_idx"; do
        next_idx=$((next_idx + 1))
      done
      tmux new-window -d -t ":${next_idx}"
      other_wins+=("$next_idx")
      next_idx=$((next_idx + 1))
    done
  fi

  # 排序取前 3（join 順序 = tiled 視覺位置）
  sorted_wins=($(printf '%s\n' "${other_wins[@]}" | sort -n | head -3))

  # join-pane + 記錄 metadata（含原始 window 編號）
  metadata=""
  for win_idx in "${sorted_wins[@]}"; do
    pane_id=$(tmux list-panes -t ":${win_idx}" -F '#{pane_id}' | head -1)
    win_name=$(tmux display-message -t ":${win_idx}" -p '#{window_name}')
    metadata="${metadata}${metadata:+|}${pane_id}:${win_name}:${win_idx}"
    tmux join-pane -dh -s ":${win_idx}" -t ":${cur_win_idx}"
  done

  tmux set-option -w @_merged_panes "$metadata"
  tmux set-option -w @_merged_host "$cur_win_name"

  apply_layout "$mode"
  pane_count=$(tmux list-panes | wc -l | tr -d ' ')
  tmux display-message "Merged → $mode ($pane_count panes) | prefix+z zoom"
fi
