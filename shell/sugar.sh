# sugar — 列出所有 workshop shell 語法糖
#   sugar          → 列出所有可用指令
#   sugar <name>   → 顯示該指令的用法說明
sugar() {
  local shell_dir="$HOME/workshop/shell"
  local target="${1:-}"

  if [[ -n "$target" ]]; then
    # 搜尋特定指令的說明
    local found=0
    for f in "$shell_dir"/*.sh(N); do
      [[ "${f:t}" == "init.sh" || "${f:t}" == "sugar.sh" ]] && continue
      local match=$(grep -A 5 "^# *${target}[ [(]\\|^${target}()" "$f" 2>/dev/null | head -10)
      if [[ -n "$match" ]]; then
        echo "\033[1;36m[${f:t}]\033[0m"
        echo "$match"
        echo ""
        found=1
      fi
    done
    (( found == 0 )) && echo "找不到指令: $target"
    return
  fi

  # 列出所有指令
  echo "\033[1;33m── Workshop Shell Sugar ──\033[0m"
  echo ""
  for f in "$shell_dir"/*.sh(N); do
    [[ ! -f "$f" ]] && continue
    [[ "${f:t}" == "init.sh" || "${f:t}" == "sugar.sh" ]] && continue
    local module="${f:t:r}"
    local cmds=()
    # 抓 function 定義
    while IFS= read -r line; do
      cmds+=("$line")
    done < <(grep -E '^[a-zA-Z_][a-zA-Z0-9_-]*\(\)' "$f" | sed 's/().*//')
    # 抓 alias 定義
    while IFS= read -r line; do
      cmds+=("$line")
    done < <(grep -E "^alias " "$f" | sed "s/alias //;s/=.*//")
    # 抓 export PATH（標記為 [env]）
    local envs=$(grep -c "^export " "$f" 2>/dev/null)

    if (( ${#cmds[@]} > 0 || envs > 0 )); then
      echo "\033[1;36m${module}\033[0m  \033[2m(${f:t})\033[0m"
      for cmd in "${cmds[@]}"; do
        # 取得該指令上方的第一行註解作為說明
        local desc=$(grep -B 1 "^${cmd}()\|^alias ${cmd}=" "$f" 2>/dev/null | grep "^#" | head -1 | sed 's/^# *//')
        if [[ -n "$desc" ]]; then
          printf "  \033[32m%-20s\033[0m %s\n" "$cmd" "$desc"
        else
          printf "  \033[32m%-20s\033[0m\n" "$cmd"
        fi
      done
      (( envs > 0 )) && echo "  \033[2m+ ${envs} env exports\033[0m"
      echo ""
    fi
  done
  echo "\033[2m用法: sugar <指令名> 查看詳細說明\033[0m"
}
