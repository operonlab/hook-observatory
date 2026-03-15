# LiteLLM Usage Tracking

## 架構

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  LLM Clients    │────▶│  LiteLLM Proxy   │────▶│  Upstream       │
│  (Claude Code,  │     │  (port 4000)     │     │  Providers      │
│   Codex, etc.)  │     │                  │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                │
                                │ (optional: log each request)
                                ▼
                        ┌──────────────────┐
                        │  agent-metrics   │
                        │  (port 8795)     │
                        │  /litellm/ingest │
                        └──────────────────┘
                                │
                                ▼
                        ┌─────────────────┐
                        │  PostgreSQL     │
                        │  (workshop DB)  │
                        │  litellm_usage  │
                        └─────────────────┘
                                │
                                ▼
                        ┌─────────────────┐
                        │  Dashboard UI   │
                        │  /apps/agent-   │
                        │  metrics/       │
                        └─────────────────┘
```

## 配置

### LiteLLM Proxy

配置文件：`~/.config/litellm/config.yaml`

LiteLLM proxy 運行於 port 4000，提供統一的 API 介面訪問多個 LLM provider。

### agent-metrics

LiteLLM 用量追蹤使用 agent-metrics station 的 `/litellm/*` 端點。

**Endpoints:**
- `GET /litellm/status` — Proxy 狀態檢查
- `POST /litellm/ingest` — 記錄單次 LLM 請求
- `GET /litellm/stats` — 用量統計
- `GET /litellm/summary` — 用量摘要
- `GET /litellm/trends` — 每日趨勢
- `GET /litellm/by-model` — 模型別 breakdown
- `GET /litellm/month-to-date` — 本月累計

## API 使用範例

### 1. 檢查 LiteLLM Proxy 狀態

```bash
curl http://127.0.0.1:8795/litellm/status
```

回傳：
```json
{
  "proxy_alive": true,
  "models_configured": ["glm-5", "kimi-k2.5", "minimax-m2.5", "deepseek-v3", "qwen3.5"]
}
```

### 2. 記錄 LLM 請求（Ingest）

每次透過 LiteLLM proxy 發送請求後，可選記錄用量：

```bash
curl -X POST http://127.0.0.1:8795/litellm/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "unique-request-id",
    "model": "deepseek-v3",
    "provider": "deepseek",
    "total_tokens": 100,
    "prompt_tokens": 50,
    "completion_tokens": 50,
    "cost_usd": 0.0001,
    "start_time": "2026-03-12T10:00:00Z"
  }'
```

### 3. 查看用量統計

```bash
curl http://127.0.0.1:8795/litellm/stats
```

### 4. 查看模型別用量

```bash
curl "http://127.0.0.1:8795/litellm/by-model?days=30"
```

### 5. 查看用量趨勢

```bash
curl "http://127.0.0.1:8795/litellm/trends?days=30"
```

## 模型配置

| Model | LiteLLM Name | Provider | API Base |
|-------|-------------|----------|----------|
| GLM-5 | `glm-5` | z.ai | https://api.z.ai/api/paas/v4 |
| Kimi K2.5 | `kimi-k2.5` | moonshot | https://api.moonshot.ai/v1 |
| MiniMax M2.5 | `minimax-m2.5` | minimax | https://api.minimax.io/v1 |
| DeepSeek V3.2 | `deepseek-v3` | deepseek | https://api.deepseek.com/v1 |
| Qwen 3.5 | `qwen3.5` | alibaba | https://dashscope-intl.aliyuncs.com/compatible-mode/v1 |

## 使用方式

### 透過 LiteLLM Proxy 呼叫 LLM

```bash
curl http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-litellm-local-dev" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v3",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

所有請求會自動記錄到 `litellm_spend` DB，包括：
- request_id
- model
- total_tokens
- response_cost
- start_time / end_time
- metadata (input_tokens, output_tokens, etc.)

## 管理命令

### 重啟 LiteLLM Proxy

```bash
# Stop
ps aux | grep -i litellm | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null

# Start
LITELLM_MASTER_KEY=sk-litellm-local-dev \
  ~/.local/bin/litellm --config ~/.config/litellm/config.yaml \
  --port 4000 --host 127.0.0.1 &
```

### 重啟 agent-metrics

```bash
# Stop
ps aux | grep agent-metrics | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null

# Start
cd /Users/joneshong/workshop/stations/agent-metrics
/opt/homebrew/bin/uv run uvicorn agent_metrics.main:app \
  --host 127.0.0.1 --port 8795 &
```

### 查看 DB 記錄

```bash
docker exec ws-infra-postgres-1 psql -U joneshong -d workshop -c \
  "SELECT model, provider, cost_usd, total_tokens, start_time
   FROM litellm_usage
   ORDER BY start_time DESC
   LIMIT 10"
```

### 清除測試資料

```bash
docker exec ws-infra-postgres-1 psql -U joneshong -d workshop -c \
  "DELETE FROM litellm_usage"
```

## Dashboard

訪問 agent-metrics Dashboard：
- URL: http://workshop.joneshong.com/apps/agent-metrics/

## 自動化建議

### 選項 1：手動 Ingest（推薦）

在呼叫 LiteLLM proxy 後，手動發送 ingest 請求：

```python
import requests
import uuid

# Call LiteLLM
response = requests.post(
    "http://127.0.0.1:4000/v1/chat/completions",
    headers={"Authorization": "Bearer sk-litellm-local-dev"},
    json={"model": "deepseek-v3", "messages": [...]}
)

# Extract usage
usage = response.json().get("usage", {})
request_id = response.json().get("id", str(uuid.uuid4()))

# Ingest to agent-metrics
requests.post(
    "http://127.0.0.1:8795/litellm/ingest",
    json={
        "request_id": request_id,
        "model": "deepseek-v3",
        "provider": "deepseek",
        "total_tokens": usage.get("total_tokens", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "cost_usd": 0.0001,  # Calculate based on model pricing
        "start_time": datetime.utcnow().isoformat() + "Z"
    }
)
```

### 選項 2：修改 LiteLLM Config（進階）

在 `~/.config/litellm/config.yaml` 添加 callback 自動記錄：

```yaml
litellm_settings:
  callbacks: ["agent_metrics_handler"]

# 需要實作自定義 callback handler
```

## 注意事項

1. **Ingest 是可選的**：LiteLLM proxy 本身不需要記錄到 DB，只有需要用量追蹤時才呼叫 ingest
2. **Cost 計算**：需要根據各 provider 的定價自行計算（參考 `~/.config/litellm/MODELS.md`）
3. **Request ID**：建議使用 LiteLLM 回傳的 `response.id` 作為唯一标识
4. **Database**：用量記錄存儲於 `workshop` DB 的 `litellm_usage` 表
