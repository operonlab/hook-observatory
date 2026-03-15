# ~/workshop/shell/init.sh — 語法糖統一入口
# .zshrc 只需: source ~/workshop/shell/init.sh
#
# 載入順序：_*.sh (helpers) → 其餘 *.sh (alphabetical)
# 新增語法糖：丟一個 .sh 進此目錄即自動載入

WORKSHOP_SHELL_DIR="${0:A:h}"

# Phase 1: helpers (underscore prefix)
for _f in "$WORKSHOP_SHELL_DIR"/_*.sh(N); do
  source "$_f"
done

# Phase 2: all other modules
for _f in "$WORKSHOP_SHELL_DIR"/*.sh(N); do
  [[ "${_f:t}" == "init.sh" ]] && continue
  [[ "${_f:t}" == _* ]] && continue
  source "$_f"
done

unset _f
