# iTerm2 Shell Integration（tmux 內也啟用）
export ITERM_ENABLE_SHELL_INTEGRATION_WITH_TMUX=YES
test -e "${HOME}/.iterm2_shell_integration.zsh" && source "${HOME}/.iterm2_shell_integration.zsh"

# 在每次 shell prompt 出現時，自動切換到 ABC 輸入法
# 解決 vChewing IMECHT 攔截 Ctrl+A 等終端機快捷鍵的問題
_iterm2_switch_input_to_abc() {
  local _abc_bin="$HOME/workshop/shell/bin/switch-to-abc"
  [[ -x "$_abc_bin" ]] && "$_abc_bin" >/dev/null 2>&1 &!
}
autoload -Uz add-zsh-hook 2>/dev/null
add-zsh-hook precmd _iterm2_switch_input_to_abc
