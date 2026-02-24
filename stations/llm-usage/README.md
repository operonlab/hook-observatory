# LLM Usage 工作站

> 統一 LLM 使用量追蹤 — 會員制 CLI 工具用量 + LiteLLM API 成本。

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

目前 LLM 使用量分散在兩個不同的世界，無法統一回答「這個月用了多少？花了多少？」：

```
── 會員制 CLI 工具（Subscription） ──────────────
Claude Code → Anthropic Max Plan → 用量比率（5h/7d window）
Codex CLI   → OpenAI (ChatGPT)   → 用量不透明
Gemini CLI  → Google (Gemini)    → 用量不透明
model-policy → 只看 CC 比率       → 用於 boost/normal 切換

── API 服務（Pay-per-use） ─────────────────────
LiteLLM     → 多 Provider API    → SQLite（有資料但沒 UI）
（用於 Anthropic Agent SDK 等自建 Agent 場景）
```

## V2 目標

### 1. 雙軌資料收集

```
┌── 會員制 CLI 工具（Subscription）─────────────────────┐
│                                                       │
│  Claude Code → session hooks → 用量比率 + session 統計 │
│  Codex CLI   → session logs  → 呼叫次數 + 估算        │
│  Gemini CLI  → session logs  → 呼叫次數 + 估算        │
│                                                       │
│  特性：固定月費，追蹤「用量額度」而非「實際金額」       │
│  資料來源：hooks, CLI logs, provider dashboard scrape  │
└───────────────────────────────────────────────────────┘

┌── API 服務（Pay-per-use via LiteLLM）────────────────┐
│                                                       │
│  Agent SDK ─┐                                         │
│  自建服務  ─┼─► LiteLLM Proxy ─► DB (token + cost)   │
│  實驗腳本  ─┘     (統一路由)                           │
│                                                       │
│  特性：按量計費，追蹤「實際 token 數 + 金額」          │
│  資料來源：LiteLLM SQLite（即時）+ Provider API（對帳）│
└───────────────────────────────────────────────────────┘
```

**兩條資料流本質不同**：
- **會員制**：追蹤用量額度消耗比率（如 CC 5h window 用了 30%），月費固定
- **API 服務**：追蹤實際 token 消耗 + 金額（LiteLLM Proxy 記錄每次呼叫），按量計費

### 2. 資料模型

**會員制用量紀錄**（Subscription Usage）：
```json
{
  "subscription_usage": {
    "id": "uuid",
    "timestamp": "2026-02-24T10:30:00Z",
    "provider": "anthropic",        // anthropic / openai / google
    "cli": "claude-code",           // claude-code / codex-cli / gemini-cli
    "plan": "max_5",                // max_5 / max_20 / pro / advanced
    "monthly_cost_usd": 100.00,    // 固定月費
    "quota_used_pct": 30.0,        // 額度消耗比率（如 CC 5h window）
    "session_count": 15,           // 當日 session 數
    "session_id": "optional",
    "task_type": "coding"           // coding / research / chat / briefing
  }
}
```

**API 用量紀錄**（Pay-per-use）：
```json
{
  "api_usage": {
    "id": "uuid",
    "timestamp": "2026-02-24T10:30:00Z",
    "provider": "anthropic",        // anthropic / openai / google / ollama
    "model": "claude-sonnet-4-6",
    "caller": "agent-sdk",          // agent-sdk / script / service
    "input_tokens": 15000,
    "output_tokens": 3200,
    "cache_read_tokens": 8000,
    "cache_write_tokens": 2000,
    "cost_usd": 0.042,
    "task_id": "optional",
    "litellm_call_id": "optional"
  }
}
```

### 3. 分析維度

| 維度 | 會員制 | API 服務 |
|------|--------|----------|
| **按 Provider** | 各平台月費總計 | 各 Provider 實際花費 |
| **按 Model** | — | Opus vs Sonnet vs Haiku 成本佔比 |
| **按 CLI/Caller** | CC vs Codex vs Gemini 用量比率 | Agent SDK vs 腳本 |
| **按時間** | 每日 session 數 + 額度趨勢 | 每日/每週/每月 token + 金額 |
| **按用途** | coding / research / briefing | 按 task 分類 |
| **Cache 效率** | — | cache hit rate，省了多少錢 |
| **總成本** | Σ 月費（固定） | Σ API 花費（變動） |

### 4. Model Policy 整合

現有 model-policy boost/normal 切換邏輯繼續運作，資料來源改從統一 DB 取得：

```
V1：model-policy 自己算 CC 5h/7d 用量比率
  ↓
V2：model-policy 從 LLM Usage DB 讀取會員制用量 → 更精確的切換判斷
    （且可參考 API 花費決定是否該切回會員制工具以節省成本）
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
┌─── LLM Usage ─── February 2026 ────────┐
│                                         │
│  ── 會員制（固定月費） ──                │
│  Anthropic Max:  $100/mo  CC 5h: 30%   │
│  OpenAI Pro:      $20/mo               │
│  Gemini Advanced: $20/mo               │
│  小計: $140/mo                          │
│                                         │
│  ── API 服務（按量計費） ──              │
│  LiteLLM: $12.30 / $50 budget  🟢     │
│  ████████░░░░░░░░░░░░░  25%            │
│  Today: 45K tokens ($1.20)              │
│  Cache savings: $3.80 this month        │
│                                         │
│  ── 總計 ──                             │
│  本月: $152.30 (固定 $140 + API $12.30) │
│  [View Details →]                       │
└─────────────────────────────────────────┘
```

## 目錄結構

```
stations/llm-usage/
├── README.md             ← 本文件
├── subscription.py       ← 會員制用量收集（CC hooks, CLI logs）
├── api_collector.py      ← LiteLLM DB 同步 + Provider API 對帳
├── analyzer.py           ← 雙軌分析引擎
├── config.json           ← 會員方案設定、API 預算、同步頻率
└── policy_adapter.py     ← model-policy 整合（讀取統一 DB）
```

## 遷移計劃

1. 整理會員制方案資訊（各 CLI 的 plan + 月費 + 額度計算方式）
2. 解析 LiteLLM SQLite DB 結構，建立 API 用量同步腳本
3. 建立雙軌資料模型（subscription_usage + api_usage）
4. 實作 subscription collector（CC hooks → session 統計 + 額度比率）
5. 實作 api_collector（每小時同步 LiteLLM → 統一 DB）
6. 建立 Core API 端點
7. 改寫 model-policy 從統一 DB 讀取
8. 建立 Workbench Widget（雙軌成本儀表板）
9. （可選）接入 Provider 帳單 API 做 API 服務對帳

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
