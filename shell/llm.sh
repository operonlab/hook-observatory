# LiteLLM proxy CLI wrappers（依賴 _helpers.sh 的 _llm_pick_model）

# cc-llm [model] [flags...] — Claude Code via LiteLLM
#   cc-llm                          → fzf 選模型，一般權限
#   cc-llm deepseek-v3              → 指定模型 + auto --dangerously-skip-permissions
#   cc-llm --dangerously-skip-permissions → fzf 選模型 + 傳入該 flag
cc-llm() {
  local model="" flags=()
  for arg in "$@"; do
    if [[ "$arg" == -* ]]; then flags+=("$arg")
    elif [[ -z "$model" ]]; then model="$arg"
    fi
  done
  if [[ -n "$model" ]]; then
    local has_skip=0
    for f in "${flags[@]}"; do [[ "$f" == --dangerously-skip-permissions ]] && has_skip=1; done
    (( has_skip == 0 )) && flags+=(--dangerously-skip-permissions)
  else
    model=$(_llm_pick_model "")
  fi
  if [[ -z "$model" ]]; then echo "取消：未選擇模型"; return 1; fi
  echo "→ Claude × $model${flags:+ (${flags[*]})}"
  ANTHROPIC_BASE_URL=http://127.0.0.1:4000 \
  ANTHROPIC_AUTH_TOKEN=sk-litellm-local-dev \
  ANTHROPIC_MODEL="$model" \
  claude "${flags[@]}"
}

# cx-llm [model] [flags...] — Codex CLI via LiteLLM
#   Codex v0.114+ 使用 Responses API，需要 apikey auth mode
cx-llm() {
  local model="" flags=()
  for arg in "$@"; do
    if [[ "$arg" == -* ]]; then flags+=("$arg")
    elif [[ -z "$model" ]]; then model="$arg"
    fi
  done
  if [[ -n "$model" ]]; then
    local has_yolo=0
    for f in "${flags[@]}"; do [[ "$f" == --yolo ]] && has_yolo=1; done
    (( has_yolo == 0 )) && flags+=(--yolo)
  else
    # Filter out models without tool calling support (Codex requires it)
    model=$(_llm_pick_model "" "$_LLM_NO_TOOLS")
  fi
  if [[ -z "$model" ]]; then echo "取消：未選擇模型"; return 1; fi
  echo "→ Codex × $model${flags:+ (${flags[*]})}"
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

# gm-llm [model] [flags...] — Gemini CLI via LiteLLM
gm-llm() {
  local model="" flags=()
  for arg in "$@"; do
    if [[ "$arg" == -* ]]; then flags+=("$arg")
    elif [[ -z "$model" ]]; then model="$arg"
    fi
  done
  if [[ -n "$model" ]]; then
    local has_yolo=0
    for f in "${flags[@]}"; do [[ "$f" == --yolo ]] && has_yolo=1; done
    (( has_yolo == 0 )) && flags+=(--yolo)
  else
    model=$(_llm_pick_model "")
  fi
  if [[ -z "$model" ]]; then echo "取消：未選擇模型"; return 1; fi
  echo "→ Gemini × $model${flags:+ (${flags[*]})}"
  GEMINI_API_KEY=sk-litellm-local-dev \
  gemini --model "openai:$model" "${flags[@]}"
}

# oc-llm [model] [flags...] — OpenCode via LiteLLM
#   oc-llm                          → fzf 選模型
#   oc-llm deepseek-v3              → 指定模型
oc-llm() {
  local model="" flags=()
  for arg in "$@"; do
    if [[ "$arg" == -* ]]; then flags+=("$arg")
    elif [[ -z "$model" ]]; then model="$arg"
    fi
  done
  [[ -z "$model" ]] && model=$(_llm_pick_model "")
  if [[ -z "$model" ]]; then echo "取消：未選擇模型"; return 1; fi
  echo "→ OpenCode × litellm/$model"
  opencode -m "litellm/$model" "${flags[@]}"
}

# cc-models — 列出 LiteLLM 可用模型（按 provider 分群）
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
