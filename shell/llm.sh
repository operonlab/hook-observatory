# LLM CLI wrappers
#
# Stack 概覽：
#   Claude Code (Anthropic protocol) ──→ CCR :3456 ──→ LiteLLM :4000 ──→ providers
#   Codex / Gemini / OpenCode (其他協議) ─────────────→ LiteLLM :4000 ──→ providers
#
# 統一互動：fzf 選 model + 預設帶安全 flag（--dangerously-skip-permissions / --yolo）
# 依賴 _helpers.sh 的 _llm_pick_model / _llm_model_listing / _llm_check_port

# ─────────────────────────────────────────────────────────────────────────
# cc-llm [model] [flags...] — Claude Code via CCR → LiteLLM
#   cc-llm                              → fzf 選單（auto = CCR routing；或鎖定具體 model）
#   cc-llm deepseek-v3                  → 跳過選單，CCR 鎖定 litellm,deepseek-v3
#   cc-llm --effort medium              → fzf 選 model + 設 effort=medium
#   cc-llm deepseek-v3 --effort high    → 鎖 model + 設 effort=high
#   CC_EFFORT=medium cc-llm             → 環境變數設 effort
# 永遠走 CCR :3456。預設帶入 --dangerously-skip-permissions。
# Effort 值：low | medium | high | xhigh | max（Claude Code 預設 xhigh）
# ─────────────────────────────────────────────────────────────────────────
cc-llm() {
  local model="" flags=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --effort)    flags+=("$1" "$2"); shift 2 ;;
      --effort=*)  flags+=("$1"); shift ;;
      -*)          flags+=("$1"); shift ;;
      *)           [[ -z "$model" ]] && model="$1"; shift ;;
    esac
  done
  local has_skip=0 has_effort=0
  for f in "${flags[@]}"; do
    [[ "$f" == --dangerously-skip-permissions ]] && has_skip=1
    [[ "$f" == --effort* ]] && has_effort=1
  done
  (( has_skip == 0 )) && flags+=(--dangerously-skip-permissions)
  # ENV fallback：未指定 --effort 時用 $CC_EFFORT
  if (( has_effort == 0 )) && [[ -n "${CC_EFFORT:-}" ]]; then
    flags+=(--effort "$CC_EFFORT")
  fi

  if [[ -z "$model" ]]; then
    if command -v fzf >/dev/null 2>&1; then
      local pick
      pick=$( {
        printf 'auto\t\033[2;36m[CCR routing] default→deepseek-v3 / think→kimi-k2.5 / long→grok-4.20 / web→qwen3.6-plus\033[0m\n'
        _llm_model_listing
      } | fzf --ansi --layout=reverse --prompt="cc-llm › " --height=40 \
            --header="auto = CCR routing；其他 = CCR 鎖定該 model（仍經 CCR + LiteLLM）" \
            --tabstop=30 --nth=1 --delimiter=$'\t' \
          | cut -f1 )
      [[ -z "$pick" ]] && { echo "取消：未選擇"; return 1; }
      [[ "$pick" == "auto" ]] && model="" || model="$pick"
    else
      echo "⚠️  未安裝 fzf，預設 auto"
      model=""
    fi
  fi
  [[ "$model" == "auto" ]] && model=""

  _llm_check_port 3456 "CCR" "ccr" || return 1

  if [[ -n "$model" ]]; then
    echo "→ Claude × $model · CCR → LiteLLM${flags:+ (${flags[*]})}"
    ANTHROPIC_BASE_URL=http://127.0.0.1:3456 \
    ANTHROPIC_AUTH_TOKEN=any-string-is-ok \
    ANTHROPIC_MODEL="litellm,$model" \
    NO_PROXY=127.0.0.1 \
    claude "${flags[@]}"
  else
    echo "→ Claude × CCR auto-route → LiteLLM${flags:+ (${flags[*]})}"
    ANTHROPIC_BASE_URL=http://127.0.0.1:3456 \
    ANTHROPIC_AUTH_TOKEN=any-string-is-ok \
    NO_PROXY=127.0.0.1 \
    claude "${flags[@]}"
  fi
}

# ─────────────────────────────────────────────────────────────────────────
# cc-llm-direct [model] [flags...] — Claude Code 繞過 CCR、直連 LiteLLM
# 用途：診斷 / 測試 CCR 是否為問題源；正常使用走 cc-llm。
# 同樣支援 --effort flag 和 CC_EFFORT 環境變數。
# ─────────────────────────────────────────────────────────────────────────
cc-llm-direct() {
  local model="" flags=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --effort)    flags+=("$1" "$2"); shift 2 ;;
      --effort=*)  flags+=("$1"); shift ;;
      -*)          flags+=("$1"); shift ;;
      *)           [[ -z "$model" ]] && model="$1"; shift ;;
    esac
  done
  [[ -z "$model" ]] && model=$(_llm_pick_model "")
  if [[ -z "$model" ]]; then echo "取消：未選擇模型"; return 1; fi
  local has_skip=0 has_effort=0
  for f in "${flags[@]}"; do
    [[ "$f" == --dangerously-skip-permissions ]] && has_skip=1
    [[ "$f" == --effort* ]] && has_effort=1
  done
  (( has_skip == 0 )) && flags+=(--dangerously-skip-permissions)
  if (( has_effort == 0 )) && [[ -n "${CC_EFFORT:-}" ]]; then
    flags+=(--effort "$CC_EFFORT")
  fi
  _llm_check_port 4000 "LiteLLM" "litellm" || return 1
  echo "→ Claude × $model · 直連 LiteLLM (繞過 CCR)${flags:+ (${flags[*]})}"
  ANTHROPIC_BASE_URL=http://127.0.0.1:4000 \
  ANTHROPIC_AUTH_TOKEN=sk-litellm-local-dev \
  ANTHROPIC_MODEL="$model" \
  claude "${flags[@]}"
}

# ─────────────────────────────────────────────────────────────────────────
# cx-llm [model] [flags...] — Codex CLI via LiteLLM
# Codex 用 OpenAI Responses API，協議與 CCR 不相容，必須直連 LiteLLM。
# Codex v0.114+ 使用 Responses API，需要 apikey auth mode。
# ─────────────────────────────────────────────────────────────────────────
cx-llm() {
  local model="" flags=()
  for arg in "$@"; do
    if [[ "$arg" == -* ]]; then flags+=("$arg")
    elif [[ -z "$model" ]]; then model="$arg"
    fi
  done
  local has_yolo=0
  for f in "${flags[@]}"; do [[ "$f" == --yolo ]] && has_yolo=1; done
  (( has_yolo == 0 )) && flags+=(--yolo)

  [[ -z "$model" ]] && model=$(_llm_pick_model "" "$_LLM_NO_TOOLS")
  if [[ -z "$model" ]]; then echo "取消：未選擇模型"; return 1; fi
  _llm_check_port 4000 "LiteLLM" "litellm" || return 1
  echo "→ Codex × $model · LiteLLM${flags:+ (${flags[*]})}"
  # Swap auth to apikey mode for LiteLLM (Codex ChatGPT OAuth won't match master key)
  local auth_file="$HOME/.codex/auth.json"
  local auth_bak="$HOME/.codex/auth.json.litellm-bak"
  cp "$auth_file" "$auth_bak" 2>/dev/null
  echo '{"auth_mode":"apikey","OPENAI_API_KEY":"sk-litellm-local-dev"}' > "$auth_file"
  OPENAI_BASE_URL=http://127.0.0.1:4000/v1 \
  codex --profile litellm --model "$model" "${flags[@]}"
  # Restore original auth
  cp "$auth_bak" "$auth_file" 2>/dev/null && rm -f "$auth_bak"
}

# ─────────────────────────────────────────────────────────────────────────
# gm-llm [model] [flags...] — Gemini CLI via LiteLLM
# Gemini CLI 使用 Google generateContent 協議，必須直連 LiteLLM。
# ─────────────────────────────────────────────────────────────────────────
gm-llm() {
  local model="" flags=()
  for arg in "$@"; do
    if [[ "$arg" == -* ]]; then flags+=("$arg")
    elif [[ -z "$model" ]]; then model="$arg"
    fi
  done
  local has_yolo=0
  for f in "${flags[@]}"; do [[ "$f" == --yolo ]] && has_yolo=1; done
  (( has_yolo == 0 )) && flags+=(--yolo)

  [[ -z "$model" ]] && model=$(_llm_pick_model "")
  if [[ -z "$model" ]]; then echo "取消：未選擇模型"; return 1; fi
  _llm_check_port 4000 "LiteLLM" "litellm" || return 1
  echo "→ Gemini × $model · LiteLLM${flags:+ (${flags[*]})}"
  GEMINI_API_KEY=sk-litellm-local-dev \
  gemini --model "openai:$model" "${flags[@]}"
}

# ─────────────────────────────────────────────────────────────────────────
# oc-llm [model] [flags...] — OpenCode via LiteLLM
# OpenCode 使用 OpenAI Chat Completions 協議，必須直連 LiteLLM。
# ─────────────────────────────────────────────────────────────────────────
oc-llm() {
  local model="" flags=()
  for arg in "$@"; do
    if [[ "$arg" == -* ]]; then flags+=("$arg")
    elif [[ -z "$model" ]]; then model="$arg"
    fi
  done
  [[ -z "$model" ]] && model=$(_llm_pick_model "")
  if [[ -z "$model" ]]; then echo "取消：未選擇模型"; return 1; fi
  _llm_check_port 4000 "LiteLLM" "litellm" || return 1
  echo "→ OpenCode × litellm/$model · LiteLLM"
  opencode -m "litellm/$model" "${flags[@]}"
}

# ─────────────────────────────────────────────────────────────────────────
# cc-models — 列出 LiteLLM 可用模型（按 provider 分群）
# ─────────────────────────────────────────────────────────────────────────
cc-models() {
  curl -s -H "Authorization: Bearer sk-litellm-local-dev" \
    http://127.0.0.1:4000/model/info 2>/dev/null \
    | ~/.local/bin/python3 -c "
import json, sys
PROVIDER_MAP = {
    'moonshot/': 'Kimi (Moonshot)',
    'minimax/': 'MiniMax',
    'deepseek/': 'DeepSeek',
    'xai/': 'xAI (Grok)',
    'dashscope/': 'Qwen (Alibaba)',
    'api.z.ai': 'Z.AI (GLM)',
    'opencode.ai/zen': 'OpenCode Zen',
    'api.groq.com': 'Groq',
    'api.openai.com': 'OpenAI',
    'generativelanguage.googleapis.com': 'Google',
    'api.openrouter.ai': 'OpenRouter',
}
def detect(m):
    model = m.get('litellm_params', {}).get('model', '')
    base = m.get('litellm_params', {}).get('api_base', '')
    for k, v in PROVIDER_MAP.items():
        if k in model or k in (base or ''):
            return v
    if '//' in (base or ''):
        return base.split('//')[1].split('/')[0]
    return model.split('/')[0] if '/' in model else 'Other'
try:
    data = json.load(sys.stdin).get('data', [])
    groups = {}
    for m in data:
        p = detect(m)
        backend = m.get('litellm_params', {}).get('model', '?')
        groups.setdefault(p, []).append((m['model_name'], backend))
    for provider in sorted(groups):
        print(f'\033[1;33m── {provider} ──\033[0m')
        for alias, backend in sorted(groups[provider]):
            print(f'  \033[32m{alias:<24}\033[0m → {backend}')
except: pass
" 2>/dev/null || echo "LiteLLM unreachable"
}
