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
    model=$(_llm_pick_model "")
  fi
  if [[ -z "$model" ]]; then echo "取消：未選擇模型"; return 1; fi
  echo "→ Codex × $model${flags:+ (${flags[*]})}"
  OPENAI_BASE_URL=http://127.0.0.1:4000/v1 \
  OPENAI_API_KEY=sk-litellm-local-dev \
  codex --model "$model" "${flags[@]}"
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

# cc-models — 列出 LiteLLM 可用模型
cc-models() {
  curl -s -H "Authorization: Bearer sk-litellm-local-dev" \
    http://127.0.0.1:4000/model/info 2>/dev/null \
    | ~/.local/bin/python3 -c "
import json,sys
data=json.load(sys.stdin).get('data',[])
models=sorted(data, key=lambda x: x.get('model_name',''))
for m in models:
    alias=m['model_name']
    backend=m.get('litellm_params',{}).get('model','?')
    print(f'  {alias:<24} → {backend}')
" 2>/dev/null || echo "LiteLLM unreachable"
}
