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
