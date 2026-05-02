#!/bin/bash
# LiteLLM log redaction + rotation
# 對 LOG_DIR 內的 *.log 和 *.gz 做敏感資料 mask + 7 天 retention。
# 排程建議：每日 04:00 跑一次（透過 Cronicle 或 launchd）。

set -euo pipefail

LOG_DIR="${LITELLM_LOG_DIR:-/opt/homebrew/var/log/workshop/litellm}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# 敏感資料 pattern（持續擴充）
declare -a PATTERNS=(
  's/AIzaSy[A-Za-z0-9_-]\{33\}/AIzaSy[REDACTED]/g'                  # Gemini API key
  's/sk-[A-Za-z0-9_-]\{40,\}/sk-[REDACTED]/g'                        # OpenAI / DeepSeek / Moonshot / DashScope
  's/xai-[A-Za-z0-9_-]\{40,\}/xai-[REDACTED]/g'                      # xAI Grok
  's/Bearer [A-Za-z0-9._-]\{20,\}/Bearer [REDACTED]/g'               # 通用 Bearer token
  's/[a-f0-9]\{32\}\.[A-Za-z0-9]\{16\}/[ZAI-KEY-REDACTED]/g'         # Z.AI key (32hex.16char)
)

apply_redact() {
  local file="$1"
  local sed_cmd=""
  for p in "${PATTERNS[@]}"; do
    sed_cmd="$sed_cmd; $p"
  done
  sed -i.bak "${sed_cmd:2}" "$file"
  rm -f "${file}.bak"
}

main() {
  [ -d "$LOG_DIR" ] || { echo "Log dir not found: $LOG_DIR" >&2; exit 1; }

  local today
  today=$(date +%Y-%m-%d)

  echo "[$(date '+%H:%M:%S')] Redacting logs in $LOG_DIR (today=$today)"

  # 1. 對非 today 的 .log 做 redact + gzip（avoid clashing with live writer）
  for f in "$LOG_DIR"/*.log; do
    [ -f "$f" ] || continue
    local base
    base=$(basename "$f")
    if [[ "$base" == "${today}"*.log ]]; then
      echo "  skip live: $base"
      continue
    fi
    echo "  redact + gzip: $base"
    apply_redact "$f"
    gzip "$f"
  done

  # 2. 對所有 .gz 補做 redact（即使是舊檔，patterns 可能更新）
  for gz in "$LOG_DIR"/*.gz; do
    [ -f "$gz" ] || continue
    if zcat "$gz" 2>/dev/null | grep -qE "AIzaSy[A-Za-z0-9_-]{33}|sk-[A-Za-z0-9_-]{40,}|xai-[A-Za-z0-9_-]{40,}"; then
      echo "  re-redact: $(basename "$gz")"
      local tmp
      tmp=$(mktemp)
      zcat "$gz" > "$tmp"
      apply_redact "$tmp"
      gzip -c "$tmp" > "$gz.new" && mv "$gz.new" "$gz"
      rm -f "$tmp"
    fi
  done

  # 3. 刪除超過 retention 天數的 .gz
  echo "  prune > ${RETENTION_DAYS} days"
  find "$LOG_DIR" -name "*.gz" -type f -mtime "+${RETENTION_DAYS}" -delete

  echo "[$(date '+%H:%M:%S')] Done."
}

main "$@"
