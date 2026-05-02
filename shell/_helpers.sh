# 共用 helper functions（其他模組可依賴）

# 不支援 tool calling 的模型（Codex CLI 需要 tool use）
_LLM_NO_TOOLS="deepseek-r1"

# 檢查 TCP port 是否處於 LISTEN，失敗回 1 並印警告。
# Usage: _llm_check_port <port> <display-name> <service-id>
#   display-name: 印給人看（CCR / LiteLLM）
#   service-id:   workshop_services.py 的 service id（ccr / litellm）
_llm_check_port() {
  local port="$1" name="$2" svc="$3"
  if ! lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "⚠️  $name not running on :$port — start: workshop_services.py start $svc"
    return 1
  fi
}

# 列出 LiteLLM 註冊模型（含 provider tag），不跑 fzf。
# Usage: _llm_model_listing [exclude_pattern]
# Output (per line): "model_name\t\033[2;33m[Provider]\033[0m"
_llm_model_listing() {
  local exclude="${1:-}"
  export _LLM_EXCLUDE="$exclude"
  curl -s -H "Authorization: Bearer sk-litellm-local-dev" \
    http://127.0.0.1:4000/model/info 2>/dev/null \
    | ~/.local/bin/python3 -c "
import json, sys, os, re
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
    'mycena.com.tw': 'Mycena (self-hosted)',
}
exclude_pat = os.environ.get('_LLM_EXCLUDE', '')
exclude_re = re.compile(exclude_pat) if exclude_pat else None
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
        name = m['model_name']
        if exclude_re and exclude_re.search(name):
            continue
        p = detect(m)
        groups.setdefault(p, []).append(name)
    for provider in sorted(groups):
        for name in sorted(groups[provider]):
            tag = f'[{provider}]'
            print(f'{name}\t\033[2;33m{tag}\033[0m')
except: pass
" 2>/dev/null
  unset _LLM_EXCLUDE
}

# fzf 互動式選擇 LiteLLM 模型（按 provider 分群）
# Usage: _llm_pick_model [model] [exclude_pattern]
#   exclude_pattern: regex to exclude models (e.g. "deepseek-r1|zen/")
_llm_pick_model() {
  local model="${1:-}"
  local exclude="${2:-}"
  [[ "$model" == -* ]] && model=""
  if [[ -z "$model" ]] && command -v fzf >/dev/null 2>&1; then
    model=$(_llm_model_listing "$exclude" \
      | fzf --ansi --layout=reverse --prompt="LiteLLM model> " --height=40 \
        --header="↑↓ 選模型 · 輸入關鍵字篩選" \
        --tabstop=30 --nth=1 --delimiter=$'\t' \
      | cut -f1)
  fi
  echo "$model"
}
