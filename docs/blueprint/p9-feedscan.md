# P9 — Feedscan（社群搜尋管線）

> 狀態：**規劃中** | 優先級：待排定 | 靈感來源：[mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill)

## 動機

目前 smart-search Skill 的社群搜尋邏輯全在 SKILL.md 指令裡，沒有 Python 處理管線。
搜尋結果缺乏量化評分（engagement-weighted scoring）和標準化格式。
從 last30days-skill 學到三個核心模式需要獨立模組承載：

1. **NormalizedResult schema** — 統一跨平台結果格式
2. **Engagement-weighted scoring** — 用真實社群互動信號排名
3. **Two-phase search** — 廣泛發現 → 實體提取 → 定向鑽深

## 架構定位

```
Smart-Search Skill ─── POST /api/feedscan/search ───→ Feedscan（收集+處理）
                                                          │
                                                          ├─ event: feedscan.job.completed
                                                          ▼
                                                       Intelflow（儲存+分析）
```

| 層 | 職責 | 不做什麼 |
|---|---|---|
| **Skill** | 查詢分類、路由選擇、合成回答 | 不做評分、標準化 |
| **Feedscan** | 平台搜尋、標準化、評分、enrichment | 不存報告、不做語意搜尋 |
| **Intelflow** | embedding、語意搜尋、主題圖譜、報告儲存 | 不做資料收集 |

## 模組結構

```
core/src/modules/feedscan/
├── __init__.py              # 模組入口、export router
├── routes.py                # REST API 端點
├── models.py                # SQLAlchemy models (schema: feedscan)
├── schemas.py               # Pydantic request/response
├── services.py              # 業務邏輯 — PUBLIC API
├── events.py                # 事件訂閱
├── deps.py                  # FastAPI dependencies
├── scoring.py               # 多因子評分引擎
├── normalize.py             # 平台 → NormalizedResult 轉換
└── adapters/                # 平台適配器（Strategy Pattern）
    ├── __init__.py           # AdapterRegistry
    ├── base.py               # BasePlatformAdapter ABC
    ├── reddit.py             # Reddit adapter
    ├── twitter.py            # X/Twitter adapter
    └── youtube.py            # YouTube adapter
```

## DB Schema（`feedscan`）

### search_jobs — 搜尋任務

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | VARCHAR(32) PK | UUID v7 |
| space_id | VARCHAR(32) | multi-tenant |
| query | TEXT | 原始查詢 |
| platforms | TEXT[] | ['reddit', 'twitter', 'youtube'] |
| status | VARCHAR(20) | pending → running → completed → failed |
| phase | INTEGER | 1 = broad, 2 = targeted |
| config | JSONB | {depth, time_range_days} |
| result_summary | JSONB | {reddit: 12, twitter: 8} |
| error | TEXT | 失敗原因 |
| started_at / completed_at | TIMESTAMP | 時間戳 |

### search_results — 標準化結果

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | VARCHAR(32) PK | UUID v7 |
| job_id | VARCHAR(32) FK | → search_jobs |
| platform | VARCHAR(20) | reddit / twitter / youtube / web |
| source_id | TEXT | 原始平台 ID |
| url / title / content / author | TEXT | 基本資料 |
| published_at | TIMESTAMP | 發布時間 |
| upvotes / comments / likes / reposts / views | INTEGER | 平台互動指標 |
| relevance_score / recency_score / engagement_score | FLOAT | 分項分數 |
| final_score | FLOAT | 加權總分 |
| entities | TEXT[] | Phase 2 提取的實體 |
| raw_data | JSONB | 原始回應（debug） |

### platform_configs — 平台設定

| 欄位 | 類型 | 說明 |
|------|------|------|
| platform | VARCHAR(20) | UNIQUE per space |
| enabled | BOOLEAN | 啟停 |
| config | JSONB | API keys, rate limits |
| daily_budget / daily_used | INTEGER | 每日 API 呼叫預算 |

## 評分演算法

```python
# 權重
SOCIAL_WEIGHTS = {"relevance": 0.45, "recency": 0.25, "engagement": 0.30}
WEB_WEIGHTS    = {"relevance": 0.55, "recency": 0.45, "engagement": 0.00}

# Engagement 公式（per platform, 借鏡 last30days）
reddit:  0.55 * log1p(upvotes) + 0.40 * log1p(comments) + 0.05 * (upvote_ratio * 10)
twitter: 0.55 * log1p(likes)   + 0.25 * log1p(reposts)  + 0.15 * log1p(replies) + 0.05 * log1p(quotes)
youtube: 0.50 * log1p(views)   + 0.30 * log1p(likes)    + 0.20 * log1p(comments)
```

## API 端點

```
POST   /api/feedscan/search              # 同步搜尋（Quick mode, <30s）
POST   /api/feedscan/jobs                # 建立非同步搜尋任務
GET    /api/feedscan/jobs/{id}           # 取得任務 + 結果
POST   /api/feedscan/score               # 對已有結果重新評分
GET    /api/feedscan/platforms            # 列出可用平台
PUT    /api/feedscan/platforms/{name}     # 更新平台設定
GET    /api/feedscan/status               # 模組狀態 + 配額
```

## 平台適配器（Strategy Pattern）

```python
class BasePlatformAdapter(ABC):
    platform: str
    async def search(self, query, time_range_days, depth) -> list[RawResult]: ...
    async def enrich(self, results: list[RawResult]) -> list[RawResult]: ...
```

- **Reddit**：httpx + Reddit JSON API（`{url}.json`）— 不依賴 OpenAI API
- **X/Twitter**：Bearer Token（如有）→ fallback WebSearch `site:x.com`
- **YouTube**：yt-dlp CLI（Phase 2）

## 事件

```python
class FeedscanEvents:
    JOB_CREATED   = "feedscan.job.created"
    JOB_COMPLETED = "feedscan.job.completed"
    JOB_FAILED    = "feedscan.job.failed"
```

## 分階段實作

### Phase 1（MVP）
- 模組骨架 + DB schema + migration
- `normalize.py` + `scoring.py`
- Reddit adapter
- 同步 `POST /search` 端點
- 掛載到 main.py
- smart-search SKILL.md Community Search 改呼叫 feedscan API

### Phase 2
- X/Twitter adapter
- Two-phase search（entity extraction → targeted drill-down）
- 非同步 job 執行
- Platform config CRUD + budget guard

### Phase 3
- YouTube adapter
- Intelflow 事件監聽自動建報告
- 快取層（query cache 24h）
- WebSearch adapter（統一 Web 結果進入 pipeline）

## 現有檔案修改

| 檔案 | 改動 |
|------|------|
| `core/src/main.py` | 新增 feedscan_router mount |
| `core/src/events/types.py` | 新增 FeedscanEvents class |
| `core/migrations/versions/` | 新增 feedscan schema migration |

## 設計靈感來源

- **mvanhorn/last30days-skill** — Two-phase search、engagement-weighted scoring、Judge Agent synthesis、platform-specific normalize
- Workshop 既有模式 — BaseCRUDService、SpaceScopedModel、EventBus、shared embedding
