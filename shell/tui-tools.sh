# TUI 工具語法糖 — glow (Markdown) + chafa (Image)
# lazygit 的 lg/lgw 已在 tools.sh 定義

# --- Glow（Markdown 閱讀器） ---

# glow 預設使用 auto style（依終端背景自動選擇）
export GLAMOUR_STYLE="${GLAMOUR_STYLE:-dark}"

# md — 閱讀 markdown（單檔或目錄），有分頁
alias md='glow -p'

# mdw — 寬版模式（適合 BenQ 2K 螢幕，固定 120 字元寬）
alias mdw='glow -p -w 120'

# rr — 查看最新的 outputs markdown 報告（按 mtime 倒序）
#      用法：rr        → 列出最新 10 筆
#           rr <n>    → 直接開啟第 n 筆
rr() {
  local outputs_dir="$HOME/workshop/outputs"
  [[ ! -d "$outputs_dir" ]] && { echo "outputs 目錄不存在: $outputs_dir"; return 1; }

  local files=("${(@f)$(find "$outputs_dir" -type f -name '*.md' -print0 2>/dev/null | xargs -0 stat -f '%m %N' | sort -rn | head -10 | cut -d' ' -f2-)}")

  if (( ${#files[@]} == 0 )); then
    echo "沒有 markdown 檔案在 $outputs_dir"
    return 1
  fi

  if [[ -n "$1" && "$1" =~ ^[0-9]+$ ]]; then
    local idx=$1
    (( idx < 1 || idx > ${#files[@]} )) && { echo "索引超出範圍 (1-${#files[@]})"; return 1; }
    glow -p "${files[$idx]}"
    return
  fi

  echo "\033[1;33m── 最新 Markdown 報告 ──\033[0m"
  local i=1
  for f in "${files[@]}"; do
    local rel="${f#$outputs_dir/}"
    local mtime=$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$f")
    printf "  \033[36m%2d\033[0m  \033[2m%s\033[0m  %s\n" "$i" "$mtime" "$rel"
    ((i++))
  done
  echo "\033[2m用法: rr <n> 開啟第 n 筆\033[0m"
}

# --- 圖片檢視（macOS Quick Look 優先，chafa fallback） ---

# img — 快速預覽（Quick Look 彈窗，等同 imgp）
alias img='imgp'

# imgp — 大圖單張檢視（macOS Quick Look 彈窗，不污染終端）
#        按空白鍵或 Cmd+W 關閉；背景執行不阻塞 shell
imgp() {
  [[ -z "$1" ]] && { echo "用法: imgp <圖檔>"; return 1; }
  [[ ! -f "$1" ]] && { echo "找不到檔案: $1"; return 1; }
  qlmanage -p "$@" >/dev/null 2>&1 &!
}

# imgo — 用 Preview.app 開啟（需要編輯/標註時用）
imgo() {
  [[ -z "$1" ]] && { echo "用法: imgo <圖檔>"; return 1; }
  open -a Preview "$@"
}

# imgs — 批量 Quick Look 多張圖片（同時預覽，左右方向鍵切換）
#        用法：imgs [目錄]（預設當前目錄）
imgs() {
  local dir="${1:-.}"
  [[ ! -d "$dir" ]] && { echo "不是目錄: $dir"; return 1; }

  setopt localoptions nullglob
  local files=("$dir"/*.{png,jpg,jpeg,gif,webp,PNG,JPG,JPEG,GIF,WEBP})
  (( ${#files[@]} == 0 )) && { echo "沒有圖片在 $dir"; return 1; }

  qlmanage -p "${files[@]}" >/dev/null 2>&1 &!
  echo "Quick Look 預覽 ${#files[@]} 張圖片（← → 切換）"
}

