# Scout 模組（後端）

> Smart Search V2 + Daily Briefing — 搜尋報告結構化儲存與情報管理引擎。

## 定位

Workshop Core 的 `scout` 模組，整合三個現有系統：
1. **research_report service**（`~/Claude/services/research_report/`）— 報告 CRUD + pgvector
2. **smart-search skill**（`~/.claude/skills/smart-search/`）— 多源搜尋引擎
3. **daily-briefing skill**（`~/.claude/skills/daily-briefing/`）— 三 AI 分析師辯論

## 核心能力

| 能力 | 說明 |
|------|------|
| **報告管理** | CRUD + 語意搜尋（pgvector 768d / 1536d） |
| **查重** | 新搜尋前查詢已有相似報告，避免重複 |
| **主題圖譜** | 自動提取主題 + 建立關聯圖（force-directed graph） |
| **每日情報** | 三 AI 分析師獨立分析 + 交叉辯論 |
| **NL Q&A** | 自然語言問答（DB 優先，向量搜尋輔助） |

## DB Schema（`scout` schema）

```sql
-- 搜尋/研究報告
CREATE TABLE scout.reports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    query       TEXT NOT NULL,            -- 原始搜尋查詢
    content     TEXT NOT NULL,            -- Markdown 格式報告全文
    sources     JSONB DEFAULT '[]',       -- 來源 URL + 標題
    tags        TEXT[] DEFAULT '{}',
    skill_name  TEXT,                     -- 產生此報告的 skill（smart-search 等）
    embedding   vector(768),              -- pgvector，Ollama nomic-embed-text
    space_id    UUID NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- 主題分類
CREATE TABLE scout.topics (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT UNIQUE NOT NULL,
    display_name TEXT,
    report_count INT DEFAULT 0,
    embedding    vector(768),
    space_id     UUID NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- 報告 ↔ 主題（多對多）
CREATE TABLE scout.report_topics (
    report_id UUID REFERENCES scout.reports(id) ON DELETE CASCADE,
    topic_id  UUID REFERENCES scout.topics(id) ON DELETE CASCADE,
    relevance FLOAT DEFAULT 1.0,
    PRIMARY KEY (report_id, topic_id)
);

-- 主題關聯圖
CREATE TABLE scout.topic_relations (
    source_topic_id UUID REFERENCES scout.topics(id),
    target_topic_id UUID REFERENCES scout.topics(id),
    weight          FLOAT DEFAULT 1.0,
    PRIMARY KEY (source_topic_id, target_topic_id)
);

-- 情報主題（動態管理，取代 V1 寫死的 6 個 domain）
CREATE TABLE scout.briefing_topics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,              -- 內部識別名（finance, ai, weather...）
    display_name  TEXT NOT NULL,              -- 顯示名稱（金融市場、AI 動態、天氣...）
    description   TEXT,                       -- 主題說明
    enabled       BOOLEAN DEFAULT true,
    priority      INT DEFAULT 0,             -- 排序（數字越大越優先）
    prompt_template TEXT,                     -- 分析師提示詞模板（可自訂）
    sources       JSONB DEFAULT '[]',        -- 偏好資料來源（RSS URLs, 搜尋關鍵字等）
    schedule      TEXT DEFAULT 'daily',      -- daily / weekday / weekly
    space_id      UUID NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- 主題細項（子分類，例如「天氣」底下的「台北、東京、紐約」）
CREATE TABLE scout.briefing_subtopics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id      UUID REFERENCES scout.briefing_topics(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,              -- 細項名稱
    parameters    JSONB DEFAULT '{}',        -- 細項參數（如 region: "台北", lat/lon 等）
    enabled       BOOLEAN DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- 每日情報彙整（改為關聯 briefing_topics）
CREATE TABLE scout.briefings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date        DATE NOT NULL,
    topic_id    UUID REFERENCES scout.briefing_topics(id), -- 關聯動態主題（取代寫死 domain）
    domain      TEXT NOT NULL,            -- 向下相容欄位（= briefing_topics.name）
    raw_data    JSONB,                    -- 原始資料摘要
    analyses    JSONB,                    -- {claude: ..., codex: ..., gemini: ...}
    debate      TEXT,                     -- 交叉辯論結論
    embedding   vector(768),
    space_id    UUID NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (date, topic_id)              -- 每天每個主題一份
);

-- 搜尋紀錄
CREATE TABLE scout.search_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query       TEXT NOT NULL,
    source      TEXT,                     -- smart-search / manual / api
    result_type TEXT,                     -- found_existing / new_report
    report_id   UUID REFERENCES scout.reports(id),
    space_id    UUID NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 索引
CREATE INDEX idx_reports_embedding ON scout.reports USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_reports_tags ON scout.reports USING GIN (tags);
CREATE INDEX idx_reports_created ON scout.reports (created_at DESC);
CREATE INDEX idx_topics_embedding ON scout.topics USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_briefings_date ON scout.briefings (date DESC);
CREATE INDEX idx_briefings_topic ON scout.briefings (topic_id);
CREATE INDEX idx_subtopics_topic ON scout.briefing_subtopics (topic_id);
```

## API 端點（`/api/scout/`）

### 報告

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/reports` | 列表（topic 過濾、tag 過濾、分頁） |
| GET | `/reports/:id` | 單筆報告全文 |
| POST | `/reports` | 建立報告（smart-search Skill 寫入點） |
| PUT | `/reports/:id` | 更新報告 |
| DELETE | `/reports/:id` | 刪除報告 |

### 搜尋

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/search` | 語意搜尋（query + limit + threshold） |
| POST | `/search/check` | 查重（回傳 exists + matches） |
| POST | `/ask` | NL Q&A（DB 優先，向量輔助） |

### 主題

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/topics` | 主題列表 |
| POST | `/topics` | 建立主題 |
| GET | `/topics/:id/related` | 相關主題 |
| GET | `/topics/graph` | 主題關聯圖（nodes + edges） |

### 情報主題管理

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/briefings/topics` | 主題列表（含啟用狀態、子分類數量） |
| POST | `/briefings/topics` | 新增主題（名稱、說明、排程頻率） |
| PUT | `/briefings/topics/:id` | 更新主題（可改名、啟停、調整提示詞） |
| DELETE | `/briefings/topics/:id` | 刪除主題（連帶刪除子分類） |
| PATCH | `/briefings/topics/:id/toggle` | 快速啟停主題 |
| POST | `/briefings/topics/:id/subtopics` | 新增子分類（如天氣→台北） |
| PUT | `/briefings/topics/:id/subtopics/:sid` | 更新子分類 |
| DELETE | `/briefings/topics/:id/subtopics/:sid` | 刪除子分類 |

### 情報

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/briefings` | 情報列表（日期範圍、主題過濾） |
| GET | `/briefings/:date` | 指定日期情報（全部主題） |
| GET | `/briefings/:date/:topic` | 指定日期 + 指定主題的情報 |
| POST | `/briefings` | 建立/觸發情報產生（可指定主題） |
| POST | `/briefings/run` | 觸發完整情報流程（所有啟用主題） |

### 統計

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/dashboard` | 統計摘要（報告數、主題數、趨勢） |
| GET | `/dashboard/timeline` | 時序圖資料 |

## 目錄結構（規劃）

```
core/src/modules/scout/
├── README.md             ← 本文件
├── __init__.py
├── routes.py             ← API 路由
├── schemas.py            ← Pydantic models
├── models.py             ← SQLAlchemy models
├── service.py            ← 業務邏輯（CRUD + 搜尋）
├── search.py             ← pgvector 語意搜尋引擎
├── topic_extractor.py    ← 自動主題提取 + 關聯圖
├── briefing_pipeline.py  ← 三分析師辯論管線
└── events.py             ← 事件定義（scout.report.created 等）
```

## Daily Briefing 主題管理（V2 新增）

### 問題

V1 的 6 個情報主題完全寫死在 `run.sh`（530 行），新增/修改主題需要改 shell 腳本。

```
V1（寫死）：finance | ai | tech | geopolitics | weather | devtools
  ↓
V2（動態）：使用者可透過 UI 自行管理主題 + 子分類
```

### 主題結構

每個主題可以有多個子分類（subtopics），子分類攜帶特定參數：

```yaml
- name: weather
  display_name: "天氣"
  schedule: daily
  subtopics:
    - name: "台北"
      parameters: { region: "Taipei", lat: 25.03, lon: 121.56 }
    - name: "東京"
      parameters: { region: "Tokyo", lat: 35.68, lon: 139.69 }
    - name: "紐約"
      parameters: { region: "New York", lat: 40.71, lon: -74.00 }

- name: finance
  display_name: "金融市場"
  schedule: weekday
  subtopics:
    - name: "美股"
      parameters: { market: "US", indices: ["SPX", "NDX", "DJI"] }
    - name: "台股"
      parameters: { market: "TW", indices: ["TAIEX"] }
    - name: "加密貨幣"
      parameters: { assets: ["BTC", "ETH", "SOL"] }

- name: ai
  display_name: "AI 動態"
  schedule: daily
  subtopics:
    - name: "模型發布"
      parameters: { sources: ["arxiv", "huggingface"] }
    - name: "產品更新"
      parameters: { companies: ["Anthropic", "OpenAI", "Google", "Meta"] }
    - name: "開源工具"
      parameters: { sources: ["github-trending"] }
```

### UI 頁面

| 頁面 | 路徑 | 功能 |
|------|------|------|
| 主題管理 | `/scout/briefings/settings` | CRUD 主題 + 子分類，排程設定 |
| 情報瀏覽 | `/scout/briefings` | 依日期檢視各主題情報 |
| 情報詳情 | `/scout/briefings/:date/:topic` | 三分析師分析 + 辯論 |

**主題管理 UI 概念**：

```
┌─── 情報主題管理 ────────────────────────┐
│                                         │
│  [+ 新增主題]                            │
│                                         │
│  ☑ 金融市場        weekday    3 subtopics│
│    ├── ☑ 美股                           │
│    ├── ☑ 台股                           │
│    └── ☑ 加密貨幣                       │
│    [+ 新增細項]                          │
│                                         │
│  ☑ AI 動態         daily      3 subtopics│
│    ├── ☑ 模型發布                       │
│    ├── ☑ 產品更新                       │
│    └── ☑ 開源工具                       │
│    [+ 新增細項]                          │
│                                         │
│  ☑ 天氣            daily      3 subtopics│
│    ├── ☑ 台北                           │
│    ├── ☑ 東京                           │
│    └── ☑ 紐約                           │
│    [+ 新增細項]                          │
│                                         │
│  ☐ 地緣政治        weekly     0 subtopics│
│    (已停用)                              │
│                                         │
└─────────────────────────────────────────┘
```

### 三分析師管線（保留 V1 設計）

V1 的三分析師辯論模式完全保留，但改為讀取動態主題設定：

```
每日觸發（cron 或 API）
    │
    ├── 讀取 briefing_topics（enabled=true）
    │
    ├── 對每個 topic + subtopics：
    │   ├── 資料收集（RSS + WebSearch + topic.sources）
    │   │
    │   ├── 三分析師獨立分析：
    │   │   ├── Claude Haiku  → 分析 A
    │   │   ├── Codex         → 分析 B
    │   │   └── Gemini Flash  → 分析 C
    │   │
    │   ├── 交叉辯論：極端立場判定 + 被忽略角度
    │   │
    │   └── 寫入 scout.briefings
    │
    └── 發送通知（可選）
```

### V1 預設主題遷移

首次啟動時自動建立 V1 的 6 個主題作為預設值：

| V1 domain | V2 topic | 預設 subtopics |
|-----------|----------|----------------|
| finance | 金融市場 | 美股、台股、加密貨幣 |
| ai | AI 動態 | 模型發布、產品更新、開源工具 |
| tech | 科技產業 | 軟體、硬體、雲端 |
| geopolitics | 地緣政治 | 美中、台海、歐洲 |
| weather | 天氣 | 台北 |
| devtools | 開發工具 | CLI、IDE、框架 |

## 遷移計劃

1. 建立 schema + models → 匯入現有 `pulso_research` DB 資料
2. 回填 52 個 .md fallback 檔案到 DB
3. 實作 Core API（復刻 research_report 端點）
4. 切換 smart-search Skill 端點從 `localhost:8830` → Core API
5. 整合 daily-briefing 三分析師管線
6. 退役 `~/Claude/services/research_report/`

## 相依模組

- **auth** — space_id 隔離
- **lore** — 搜尋報告可觸發記憶建立（跨模組事件）
- **mcp/scout** — MCP 工具對接

## Skill 整合

除了 smart-search 和 daily-briefing 外，以下 Skills 的產出也統一存入 scout DB：

| Skill | 整合方式 |
|-------|---------|
| **company-intel** | 報告存入 `scout.reports`（tag: company-intel） |
| **competitive-intel** | 報告存入 `scout.reports`（tag: competitive-intel） |
| **content-writer** | 文章存入 `scout.reports`（tag: content-article），來源連結存入 `sources` JSONB |

所有研究成果統一入庫後，可跨 skill 語意搜尋，避免資訊孤島。

## 參考

- 現有 research_report：`~/Claude/services/research_report/`
- 現有 smart-search skill：`~/.claude/skills/smart-search/SKILL.md`
- 現有 daily-briefing skill：`~/.claude/skills/daily-briefing/`
- 現有 company-intel skill：`~/.claude/skills/company-intel/SKILL.md`
- 現有 competitive-intel skill：`~/.claude/skills/competitive-intel/SKILL.md`
- 現有 content-writer skill：`~/.claude/skills/content-writer/SKILL.md`
- V1 前端 Research Hub：port 3005
