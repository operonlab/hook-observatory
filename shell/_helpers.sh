# 共用 helper functions（其他模組可依賴）

# fzf 互動式選擇 LiteLLM 模型
_llm_pick_model() {
  local model="${1:-}"
  [[ "$model" == -* ]] && model=""
  if [[ -z "$model" ]] && command -v fzf >/dev/null 2>&1; then
    model=$(curl -s -H "Authorization: Bearer sk-litellm-local-dev" \
      http://127.0.0.1:4000/model/info 2>/dev/null \
      | ~/.local/bin/python3 -c "
import json,sys
try:
    data=json.load(sys.stdin).get('data',[])
    for m in sorted(data, key=lambda x: x.get('model_name','')):
        print(m['model_name'])
except: pass" 2>/dev/null | fzf --prompt="LiteLLM model> " --height=20)
  fi
  echo "$model"
}
