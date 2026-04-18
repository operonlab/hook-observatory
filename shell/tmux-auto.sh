# tmux-auto [always|once|off] — 切換 tmux 自動啟動模式
#   tmux-auto          → 顯示目前模式
#   tmux-auto always   → 每個新 tab 自動進 tmux
#   tmux-auto once     → 只有開機後第一個 tab 自動進 tmux
#   tmux-auto off      → 停用自動進 tmux（新視窗開一般 shell）
tmux-auto() {
  local mode_file="$HOME/.config/tmux-autostart-mode"
  mkdir -p "$(dirname "$mode_file")"
  case "${1:-}" in
    always) echo "always" > "$mode_file"; echo "tmux autostart: always (every new tab)" ;;
    once)   echo "once"   > "$mode_file"; echo "tmux autostart: once (first tab after boot)" ;;
    off)    echo "off"    > "$mode_file"; echo "tmux autostart: off (normal shell on new tab)" ;;
    *)      echo "Current: ${$(cat "$mode_file" 2>/dev/null):-always}"; echo "Usage: tmux-auto <always|once|off>" ;;
  esac
}

# ── 自動啟動邏輯 ──
# 讀 mode file 決定是否 exec tmux。由 init.sh 在 interactive shell 啟動時觸發。
_tmux_autostart_maybe() {
  # 防嵌套 / 非 interactive / ssh 連線一律 skip
  [ -n "$TMUX" ] && return 0
  [[ ! -o interactive ]] && return 0
  [ -n "$SSH_CONNECTION" ] && return 0
  command -v tmux >/dev/null 2>&1 || return 0

  local mode_file="$HOME/.config/tmux-autostart-mode"
  local mode="$(cat "$mode_file" 2>/dev/null || echo always)"

  case "$mode" in
    off)    return 0 ;;
    once)
      # 每次開機只在第一個 interactive shell 進 tmux
      # 抓第一個 >=10 位數字（epoch seconds），避開 usec 的 6 位數值
      local boot_sec
      boot_sec=$(sysctl -n kern.boottime 2>/dev/null | grep -oE '[0-9]{10,}' | head -1)
      local sentinel="/tmp/tmux-autostart-boot-${boot_sec:-0}"
      [ -f "$sentinel" ] && return 0
      touch "$sentinel" 2>/dev/null
      ;;
    always) ;;
    *)      return 0 ;;
  esac

  exec tmux new-session -A -s default
}
_tmux_autostart_maybe
unset -f _tmux_autostart_maybe
