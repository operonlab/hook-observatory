# 開發工具初始化

# mise（統一版本管理：node, python, go, rust 等）
command -v mise >/dev/null 2>&1 && eval "$(mise activate zsh)"

# zoxide（智能 cd：z <目錄片段> 直接跳轉）
command -v zoxide >/dev/null 2>&1 && eval "$(zoxide init zsh)"

# fzf + fd 整合（fd 更快、尊重 .gitignore）
export FZF_DEFAULT_COMMAND='fd --type f --hidden --follow --exclude .git'
export FZF_CTRL_T_COMMAND="$FZF_DEFAULT_COMMAND"
export FZF_ALT_C_COMMAND='fd --type d --hidden --follow --exclude .git'

# bat（cat 替代，語法高亮）
export BAT_THEME="Catppuccin Mocha"
alias cat='bat --paging=never'
