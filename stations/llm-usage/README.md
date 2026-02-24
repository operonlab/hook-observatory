# LLM Usage 工作站

> 統一 LLM Token/Cost 追蹤 — 整合 Claude Code + Codex CLI + Gemini CLI + LiteLLM Proxy。

## 定位

Workshop `stations/` 下的獨立工作站，提供跨 LLM 服務的統一使用量與成本追蹤。

## V1 資產

| 元件 | 位置 | 狀態 |
|------|------|------|
| `model-policy.py` | `~/.claude/scripts/model-policy.py` | 運作中，追蹤 Claude Code 5h/7d 用量 |
| `state.json` | `~/.claude/data/model-policy/state.json` | boost/normal 模式切換 |
| LiteLLM Proxy | `~/.config/litellm/` | 運作中，統一 LLM API 路由 |
| LiteLLM DB | LiteLLM 內部 SQLite | 有 token/cost 紀錄但未被利用 |

## 問題分析

目前 LLM 使用量分散在各處，無法統一回答「這個月花了多少？」：

```
Claude Code → Anthropic API → 帳單（Web Console 手動查看）
Codex CLI   → OpenAI API   → 帳單（Web Console 手動查看）
Gemini CLI  → Google API   → 帳單（Web Console 手動查看）
LiteLLM     → 多 Provider  → SQLite（有資料但沒 UI）
model-policy → 只看 CC 比率  → 用於 boost/normal 切換（不追蹤金額）
```

## V2 目標

### 1. 統一資料收集

```
┌── 資料來源 ──────────────────────────────┐
│                                          │
│  Claude Code ─┐                          │
│  Codex CLI   ─┼─► LiteLLM Proxy ─► DB   │
│  Gemini CLI  ─┘     (統一路由)           │
│                                          │
│  Anthropic Console ─┐                    │
│  OpenAI Console    ─┼─► API 拉取 ─► DB   │
│  Google Console    ─┘   (每日同步)       │
│                                          │
└──────────────────────────────────────────┘
```

**兩條資料流**：
- **即時流**：LiteLLM Proxy 記錄每次 API 呼叫的 token 數 + 模型 + 成本
- **對帳流**：每日從各 Provider 帳單 API 拉取實際花費（校正用）

### 2. 資料模型

```json
{
  "usage_records": {
    "id": "uuid",
    "timestamp": "2026-02-24T10:30:00Z",
    "provider": "anthropic",        // anthropic / openai / google / ollama
    "model": "claude-opus-4-6",
    "caller": "claude-code",        // claude-code / codex-cli / gemini-cli / litellm / api
    "input_tokens": 15000,
    "output_tokens": 3200,
    "cache_read_tokens": 8000,
    "cache_write_tokens": 2000,
    "cost_usd": 0.42,
    "session_id": "optional",
    "task_type": "coding"           // coding / research / chat / briefing
  }
}
```

### 3. 成本分析維度

| 維度 | 分析 |
|------|------|
| **按 Provider** | Anthropic vs OpenAI vs Google 各花多少 |
| **按 Model** | Opus vs Sonnet vs Haiku 成本佔比 |
| **按 Caller** | Claude Code vs Codex vs Gemini CLI 用量 |
| **按時間** | 每日/每週/每月趨勢 |
| **按用途** | coding / research / briefing 分類 |
| **cache 效率** | cache hit rate，省了多少錢 |

### 4. Model Policy 整合

現有 model-policy boost/normal 切換邏輯繼續運作，但資料來源改從統一 DB 取得：

```
V1：model-policy 自己算 CC 5h/7d 用量
  ↓
V2：model-policy 從 LLM Usage DB 讀取統一用量 → 更精確的切換判斷
```

## API 端點（`/api/stations/llm-usage/`）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/summary` | 總覽（今日/本週/本月 token 數 + 成本） |
| GET | `/records` | 使用紀錄列表（provider/model/caller 過濾、分頁） |
| GET | `/breakdown` | 多維度拆解（provider/model/caller/time） |
| GET | `/trends` | 趨勢資料（時序圖用） |
| GET | `/budget` | 預算追蹤（設定月度上限 vs 實際花費） |
| POST | `/budget` | 設定預算上限 |
| POST | `/sync` | 手動觸發 LiteLLM DB 同步 |
| GET | `/cache-stats` | Cache 效率統計 |

## Workbench Widget

Dashboard 首頁卡片：

```
┌─── LLM Usage ───────────────────────────┐
│                                         │
│  February 2026                          │
│  Total: $142.30 / $200 budget  🟡      │
│  ████████████████░░░░░░░  71%           │
│                                         │
│  Anthropic: $89.50  (63%)               │
│  OpenAI:    $32.80  (23%)               │
│  Google:    $20.00  (14%)               │
│                                         │
│  Today: 180K tokens ($4.20)             │
│  Cache savings: $12.50 this month       │
│  [View Details →]                       │
└─────────────────────────────────────────┘
```

## 目錄結構

```
stations/llm-usage/
├── README.md             ← 本文件
├── collector.py          ← LiteLLM DB 同步 + Provider API 拉取
├── analyzer.py           ← 多維度分析引擎
├── config.json           ← Provider API keys 引用、預算設定、同步頻率
└── policy_adapter.py     ← model-policy 整合（讀取統一 DB）
```

## 遷移計劃

1. 解析 LiteLLM SQLite DB 結構，建立同步腳本
2. 建立統一 usage_records 資料模型（PostgreSQL 或本地 SQLite）
3. 實作 collector（每小時同步 LiteLLM → 統一 DB）
4. 建立 Core API 端點
5. 改寫 model-policy 從統一 DB 讀取
6. 建立 Workbench Widget（成本儀表板）
7. （可選）接入 Provider 帳單 API 做對帳

## 相依

- **station-sdk**（`libs/python/station-sdk/`）— Core API 推送、Widget 資料格式、通知整合（參見 [AD-8](../../docs/architecture/architecture-decisions.md#ad-8-station-sdk--工作站共享層)）
- **LiteLLM Proxy** — 主要資料來源
- **model-policy** — 現有 boost/normal 切換邏輯
- **Core API**（可選）— 持久化到 PostgreSQL
- **notification bridge**（可選）— 預算超標警報

## 參考

- Model Policy：`~/.claude/scripts/model-policy.py`
- Model Policy 狀態：`~/.claude/data/model-policy/state.json`
- LiteLLM 設定：`~/.config/litellm/`
- LiteLLM 文件：https://docs.litellm.ai/
