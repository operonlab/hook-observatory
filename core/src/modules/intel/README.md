# Intel 模組（後端）

> Smart Search V2 + Daily Briefing — 搜尋報告結構化儲存與情報管理引擎。

## 定位

Workshop Core 的 `intel` 模組，整合三個現有系統：
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

## DB Schema（`intel` schema）

```sql
-- 搜尋/研究報告
CREATE TABLE intel.reports (
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
CREATE TABLE intel.topics (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT UNIQUE NOT NULL,
    display_name TEXT,
    report_count INT DEFAULT 0,
    embedding    vector(768),
    space_id     UUID NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- 報告 ↔ 主題（多對多）
CREATE TABLE intel.report_topics (
    report_id UUID REFERENCES intel.reports(id) ON DELETE CASCADE,
    topic_id  UUID REFERENCES intel.topics(id) ON DELETE CASCADE,
    relevance FLOAT DEFAULT 1.0,
    PRIMARY KEY (report_id, topic_id)
);

-- 主題關聯圖
CREATE TABLE intel.topic_relations (
    source_topic_id UUID REFERENCES intel.topics(id),
    target_topic_id UUID REFERENCES intel.topics(id),
    weight          FLOAT DEFAULT 1.0,
    PRIMARY KEY (source_topic_id, target_topic_id)
);

-- 每日情報彙整
CREATE TABLE intel.briefings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date        DATE NOT NULL UNIQUE,
    domain      TEXT NOT NULL,            -- finance / ai / tech / geopolitics / weather
    raw_data    JSONB,                    -- 原始資料摘要
    analyses    JSONB,                    -- {claude: ..., codex: ..., gemini: ...}
    debate      TEXT,                     -- 交叉辯論結論
    embedding   vector(768),
    space_id    UUID NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 搜尋紀錄
CREATE TABLE intel.search_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query       TEXT NOT NULL,
    source      TEXT,                     -- smart-search / manual / api
    result_type TEXT,                     -- found_existing / new_report
    report_id   UUID REFERENCES intel.reports(id),
    space_id    UUID NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 索引
CREATE INDEX idx_reports_embedding ON intel.reports USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_reports_tags ON intel.reports USING GIN (tags);
CREATE INDEX idx_reports_created ON intel.reports (created_at DESC);
CREATE INDEX idx_topics_embedding ON intel.topics USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_briefings_date ON intel.briefings (date DESC);
```

## API 端點（`/api/intel/`）

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

### 情報

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/briefings` | 情報列表（日期範圍） |
| GET | `/briefings/:date` | 指定日期情報 |
| POST | `/briefings` | 建立/觸發情報產生 |

### 統計

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/dashboard` | 統計摘要（報告數、主題數、趨勢） |
| GET | `/dashboard/timeline` | 時序圖資料 |

## 目錄結構（規劃）

```
core/src/modules/intel/
├── README.md             ← 本文件
├── __init__.py
├── routes.py             ← API 路由
├── schemas.py            ← Pydantic models
├── models.py             ← SQLAlchemy models
├── service.py            ← 業務邏輯（CRUD + 搜尋）
├── search.py             ← pgvector 語意搜尋引擎
├── topic_extractor.py    ← 自動主題提取 + 關聯圖
├── briefing_pipeline.py  ← 三分析師辯論管線
└── events.py             ← 事件定義（intel.report.created 等）
```

## 遷移計劃

1. 建立 schema + models → 匯入現有 `pulso_research` DB 資料
2. 回填 52 個 .md fallback 檔案到 DB
3. 實作 Core API（復刻 research_report 端點）
4. 切換 smart-search Skill 端點從 `localhost:8830` → Core API
5. 整合 daily-briefing 三分析師管線
6. 退役 `~/Claude/services/research_report/`

## 相依模組

- **auth** — space_id 隔離
- **memory** — 搜尋報告可觸發記憶建立（跨模組事件）
- **mcp/intel** — MCP 工具對接

## 參考

- 現有 research_report：`~/Claude/services/research_report/`
- 現有 smart-search skill：`~/.claude/skills/smart-search/SKILL.md`
- 現有 daily-briefing skill：`~/.claude/skills/daily-briefing/`
- V1 前端 Research Hub：port 3005
