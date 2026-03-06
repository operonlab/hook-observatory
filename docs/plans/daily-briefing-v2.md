# Daily Briefing V2 — Architecture Blueprint

> Status: DRAFT | Date: 2026-03-06
> Goal: 將每日情報從 intelflow 完全抽離為第 14 個獨立 core module `briefing`

## 1. Design Decisions

| # | 決策 | 選項 |
|---|------|------|
| 1 | 入口 | `/briefing` 獨立頂層路由 |
| 2 | 辯論 UI | 對話氣泡式（分析師頭像 + 氣泡） |
| 3 | 結論互動 | 唯讀，使用者可提出延伸疑問 → 追加報告 |
| 4 | 多領域 | 合併結論 + 分開詳情（Option C） |
| 5 | 分析師 | 可配置（非硬編碼 Claude/Codex/Gemini） |
| 6 | 後端 | **完全獨立 core module** — 獨立 DB schema、model、service、route |

## 2. Module Separation Plan

### 2.1 From intelflow → briefing (遷移)

```
intelflow schema (BEFORE)           briefing schema (AFTER)
─────────────────────────           ────────────────────────
reports              ─ stays        briefings              ← moved
report_embeddings    ─ stays        briefing_entries       ← moved
topics               ─ stays        briefing_topics        ← moved
report_topics        ─ stays        briefing_subtopics     ← moved
topic_relations      ─ stays        briefing_analysts      ← NEW
search_sessions      ─ stays        briefing_follow_ups    ← NEW
briefings            ─ MOVES →      briefings_archive      ← moved
briefing_entries     ─ MOVES →      briefings_frozen       ← moved
briefing_topics      ─ MOVES →
briefing_subtopics   ─ MOVES →
briefings_archive    ─ MOVES →
briefings_frozen     ─ MOVES →
reports_archive      ─ stays
reports_frozen       ─ stays
```

### 2.2 Impact Analysis

| 影響範圍 | 檔案 | 改動 |
|---------|------|------|
| intelflow/models.py | 442 lines | 移除 6 個 Briefing 相關 class (~150 lines) |
| intelflow/schemas.py | 251 lines | 移除 Briefing 相關 schema (~80 lines) |
| intelflow/services.py | 907 lines | 移除 BriefingService + BriefingTopicService (~400 lines) |
| intelflow/routes.py | 681 lines | 移除 Briefing 相關 routes (~300 lines) |
| intelflow dashboard | services.py:828 | `total_briefings` 改為跨模組查詢或移除 |
| test_lifecycle_imports.py | 4 lines | 改 import path |
| 前端 intelflow module | 多檔案 | BriefingList/Detail/Settings 保留但標記 deprecated |
| main.py | 0 lines | 無直接 briefing 引用，只需新增 briefing router |

### 2.3 Cross-Module Communication

```
briefing module                    intelflow module
─────────────────                  ──────────────────
                                   ReportService (public API)
BriefingService ─── reads ──────→  report_service.search()
                                   report_service.get()

BriefingService ─── publishes ──→  EventBus
                                   briefing.daily.completed
                                   briefing.follow_up.answered

intelflow ──────── subscribes ──→  briefing.daily.completed
  (optional: update dashboard)     (if dashboard needs briefing count)
```

## 3. Backend Module Structure

```
core/src/modules/briefing/
├── __init__.py          # Module registration, router export
├── models.py            # 8 tables in `briefing` schema
├── schemas.py           # Request/response types
├── services.py          # BriefingService, TopicService, AnalystService, FollowUpService
├── routes.py            # All /api/briefing/* endpoints
├── events.py            # Event type definitions
├── deps.py              # FastAPI dependencies (if needed)
└── hooks.py             # Plugin hook points (if needed)
```

### 3.1 Models — `briefing` Schema (8 tables)

```python
SCHEMA = "briefing"
EMBEDDING_DIM = 768

BRIEFING_STATUSES = (
    "searching",     # Phase 1: 搜集原始資料
    "analyzing",     # Phase 2: 多分析師獨立分析
    "debating",      # Phase 3: 交叉辯論
    "synthesizing",  # Phase 4: 結論合成
    "completed",
    "failed",
)

ENTRY_PHASES = ("raw", "analysis", "debate", "conclusion")


# ── Moved from intelflow (schema changed) ──

class BriefingTopic(SpaceScopedModel):
    """Configurable briefing topic — e.g. tech-trends, weather"""
    __tablename__ = "briefing_topics"
    # Fields: name, display_name, description, enabled, priority,
    #         prompt_template, sources (JSONB), schedule
    #         + relationship → subtopics

class BriefingSubtopic(SpaceScopedModel):
    """Subtopic within a topic — e.g. weather → 土城, 高雄"""
    __tablename__ = "briefing_subtopics"
    # Fields: topic_id (FK), name, parameters (JSONB), enabled

class Briefing(SpaceScopedModel):
    """A daily briefing — one per date per topic"""
    __tablename__ = "briefings"
    # Fields: date, topic_id (FK), domain, status, embedding
    # Legacy JSONB: raw_data, analyses, debate (nullable, migration compat)
    # Relationships: entries, topic, follow_ups

class BriefingEntry(SpaceScopedModel):
    """Phase-keyed content unit — raw|analysis|debate|conclusion"""
    __tablename__ = "briefing_entries"
    # Fields: briefing_id (FK), phase, key, content, embedding, metadata

class BriefingArchive(Base):
    __tablename__ = "briefings_archive"

class BriefingFrozen(Base):
    __tablename__ = "briefings_frozen"


# ── New tables ──

class BriefingAnalyst(SpaceScopedModel):
    """Configurable analyst persona"""
    __tablename__ = "briefing_analysts"
    __table_args__ = (
        Index("idx_ba_name", "space_id", "name", unique=True),
        {"schema": SCHEMA},
    )
    name: str              # "claude"
    display_name: str      # "Claude"
    color: str             # "#c4a7e7"
    avatar_url: str | None
    model_id: str | None   # "claude-opus-4-6" — which LLM to use
    system_prompt: str | None
    enabled: bool          # default True
    priority: int          # display order

class BriefingFollowUp(SpaceScopedModel):
    """User follow-up question on a briefing conclusion"""
    __tablename__ = "briefing_follow_ups"
    __table_args__ = (
        Index("idx_bfu_briefing", "briefing_id"),
        Index("idx_bfu_created", "created_at"),
        {"schema": SCHEMA},
    )
    briefing_id: str       # FK → briefings.id
    question: str          # user's question
    answer: str | None     # AI-generated follow-up report
    status: str            # pending | generating | completed | failed
    metadata: dict | None  # sources, analyst used, generation time
```

### 3.2 Conclusion Entry Structure

```python
BriefingEntry(
    phase="conclusion",
    key="synthesis",               # or domain name for per-domain
    content="## 今日結論\n\n...",    # Markdown
    metadata={
        "consensus_points": [
            "AI 晶片供應鏈持續吃緊",
            "聯準會暗示 Q3 可能降息",
        ],
        "dissent_points": [
            {
                "topic": "加密貨幣走勢",
                "positions": {
                    "claude": "短期看多，機構資金持續流入",
                    "gemini": "技術面超買，可能回調",
                }
            }
        ],
        "confidence": 0.85,
        "sources_count": 12,
        "analysts": ["claude", "codex", "gemini"],
        "generated_at": "2026-03-06T08:00:00+08:00",
    }
)
```

### 3.3 API Endpoints — `/api/briefing/*`

```
# ── Briefing CRUD ──
GET    /api/briefing/daily                           → PaginatedResponse[BriefingResponse]
GET    /api/briefing/daily/{date}                    → list[BriefingResponse]
GET    /api/briefing/daily/{date}/summary            → DailySummaryResponse (merged)
GET    /api/briefing/daily/{date}/{domain}           → BriefingResponse
POST   /api/briefing/daily                           → BriefingResponse (201)
PATCH  /api/briefing/daily/{briefing_id}             → BriefingResponse

# ── Entries ──
GET    /api/briefing/daily/{briefing_id}/entries     → list[BriefingEntryResponse]
POST   /api/briefing/daily/{briefing_id}/entries     → BriefingEntryResponse (201)

# ── Follow-ups ──
GET    /api/briefing/daily/{briefing_id}/follow-ups  → list[FollowUpResponse]
POST   /api/briefing/daily/{briefing_id}/follow-ups  → FollowUpResponse (201)

# ── Topics (config) ──
GET    /api/briefing/topics                          → PaginatedResponse[TopicResponse]
POST   /api/briefing/topics                          → TopicResponse (201)
PUT    /api/briefing/topics/{id}                     → TopicResponse
DELETE /api/briefing/topics/{id}                     → 204
PATCH  /api/briefing/topics/{id}/toggle              → TopicResponse

# ── Subtopics ──
POST   /api/briefing/topics/{id}/subtopics           → SubtopicResponse (201)
PUT    /api/briefing/topics/{id}/subtopics/{sid}      → SubtopicResponse
DELETE /api/briefing/topics/{id}/subtopics/{sid}      → 204

# ── Analysts (config) ──
GET    /api/briefing/analysts                        → list[AnalystResponse]
POST   /api/briefing/analysts                        → AnalystResponse (201)
PUT    /api/briefing/analysts/{id}                   → AnalystResponse
DELETE /api/briefing/analysts/{id}                   → 204
PATCH  /api/briefing/analysts/{id}/toggle            → AnalystResponse

# ── Frozen / Archive ──
GET    /api/briefing/frozen                          → list[FrozenBriefingMeta]
GET    /api/briefing/frozen/{id}/thaw                → full content from S3
```

### 3.4 DailySummaryResponse (merged view)

```python
class DailySummaryResponse(BaseModel):
    """Merged conclusion across all domains for a given date."""
    date: date
    status: str                          # worst-case of all briefings
    domains: list[DomainSummary]         # per-domain mini summary
    merged_conclusion: str | None        # LLM-merged or concatenated
    consensus_points: list[str]
    dissent_points: list[dict]
    confidence: float | None
    briefing_ids: list[str]
    follow_up_count: int

class DomainSummary(BaseModel):
    domain: str
    display_name: str
    briefing_id: str
    status: str
    sources_count: int                   # number of raw entries
    analysts_count: int                  # number of analysis entries
    has_conclusion: bool
```

## 4. Information Architecture

```
/briefing                       Landing — 今日合併結論（所有領域）
/briefing/history               歷史日期列表
/briefing/:date                 單日詳情頁
  Tab 1: 結論 (default)           合併所有領域的結論 + 追問入口
  Tab 2: 交叉辯論                  對話氣泡式，按領域分 section
  Tab 3: 原始資料                  按領域折疊，可展開
/briefing/:date/:domain         單一領域詳情（從合併頁點進去）
/briefing/settings              主題 / 子主題 / 分析師 配置
/briefing/follow-ups            追問記錄總覽
```

## 5. Frontend Module Structure

```
workbench/src/modules/briefing/
├── index.tsx                    # 路由定義 + 模組 export
├── api/
│   └── client.ts               # API client → /api/briefing/*
├── types/
│   └── index.ts                # Briefing-specific types
├── stores/
│   └── index.ts                # Zustand store
├── hooks/
│   └── useBriefing.ts          # Custom hooks
├── components/
│   ├── BriefingLayout.tsx      # 獨立 Layout
│   ├── ConclusionCard.tsx      # 結論卡片 (共識/分歧/信心度)
│   ├── DebateBubble.tsx        # 對話氣泡組件
│   ├── FollowUpInput.tsx       # 追問輸入框
│   ├── FollowUpThread.tsx      # 追問對話串
│   ├── DomainSection.tsx       # 領域區塊 (展開/折疊)
│   ├── AnalystAvatar.tsx       # 分析師頭像 + 色標
│   ├── ConfidenceMeter.tsx     # 信心度視覺指標
│   ├── DateNavigator.tsx       # 日期快速切換
│   └── MarkdownBlock.tsx       # Markdown 渲染 (shared)
├── pages/
│   ├── TodayBriefing.tsx       # Landing: 今日合併結論
│   ├── BriefingHistory.tsx     # 歷史日期列表
│   ├── BriefingDetail.tsx      # 單日 3-tab 詳情
│   ├── DomainDetail.tsx        # 單一領域深入
│   └── BriefingConfig.tsx      # 設定 (主題+子主題+分析師)
└── styles/
    └── briefing.css            # 沿用深色奢華主題 (--bf-* 或 reuse --if-*)
```

## 6. UI/UX Wireframes

### 6.1 Landing — 今日合併結論

```
┌─────────────────────────────────────────────────┐
│ DAILY BRIEFING                    ← 2026-03-06 →│
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │  Executive Summary                           │ │
│ │                                              │ │
│ │  [完整 Markdown 結論 — 合併所有領域]           │ │
│ │                                              │ │
│ │  ── Consensus ──────────────────             │ │
│ │  ● AI 晶片供應鏈持續吃緊                      │ │
│ │  ● 聯準會暗示 Q3 可能降息                      │ │
│ │  ● 台北明日午後雷陣雨                          │ │
│ │                                              │ │
│ │  ── Dissent ────────────────────             │ │
│ │  ▲ 加密貨幣走勢                               │ │
│ │    Claude: 短期看多   vs   Gemini: 技術超買   │ │
│ │                                              │ │
│ │  Confidence ████████░░ 85%                   │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│  Covered Domains                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │ 科技趨勢  │ │ 金融市場  │ │ 天氣預報  │ →      │
│  │ 3 sources │ │ 5 sources│ │ 3 cities │         │
│  └──────────┘ └──────────┘ └──────────┘         │
│                                                  │
│  ┌──────────────────────────────────────────────┐│
│  │ 有疑問？針對今日情報提出延伸問題...             ││
│  └──────────────────────────────────────────────┘│
│                                                  │
│  Follow-ups (2)                                  │
│  ┌──────────────────────────────────────────────┐│
│  │ Q: 聯準會降息對台股的影響？                    ││
│  │ A: 根據分析... (展開/收合)                     ││
│  └──────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
```

### 6.2 Debate Tab — 對話氣泡式

```
┌──────────────────────────────────────────────┐
│  [結論]  [交叉辯論]  [原始資料]                │
│  ────────────────────────────────────────── │
│                                              │
│  ── 科技趨勢 ──                              │
│                                              │
│  ┌─ 🟣 ──────────────────────────────────┐  │
│  │ Claude                                 │  │
│  │ AI 晶片需求在 2026 Q2 將持續攀升，      │  │
│  │ 主要驅動力來自...                       │  │
│  └────────────────────────────────────────┘  │
│                                              │
│              ┌──────────────────────── 🟢 ─┐ │
│              │                      Codex  │ │
│              │ 同意 Claude 的觀點，但需     │ │
│              │ 補充供應鏈瓶頸風險...         │ │
│              └─────────────────────────────┘ │
│                                              │
│  ┌─ 🟠 ──────────────────────────────────┐  │
│  │ Gemini                                 │  │
│  │ 我持不同看法。根據最新財報數據，         │  │
│  │ 庫存水位已達...                         │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ── 金融市場 ──                              │
│  ...                                         │
└──────────────────────────────────────────────┘
```

### 6.3 Settings — 雙 Tab 管理

```
┌────────────────────────────────────────────────┐
│  Briefing Settings                              │
│                                                 │
│  [主題管理]  [分析師管理]                         │
│  ─────────────────────────────────────────────  │
│                                                 │
│  [主題管理 Tab]                                  │
│  ┌─ 科技趨勢 ──── daily ──── ON ─── Edit Del ─┐│
│  │  ├── AI / 半導體         ON   Edit Del      ││
│  │  ├── 加密貨幣             ON   Edit Del      ││
│  │  └── + 新增子分類                            ││
│  ├─ 天氣預報 ──── daily ──── ON ─── Edit Del ─┤│
│  │  ├── 土城  (metric)      ON   Edit Del      ││
│  │  ├── 高雄  (metric)      ON   Edit Del      ││
│  │  ├── 東京  (metric)      ON   Edit Del      ││
│  │  └── + 新增子分類                            ││
│  └── + 新增主題                                 │
│                                                 │
│  [分析師管理 Tab]                                │
│  ┌─ 🟣 Claude ──── claude-opus-4 ── ON ────┐   │
│  │  System prompt: 你是一位資深分析師...      │   │
│  ├─ 🟢 Codex ───── o3 ──────────── ON ────┤   │
│  ├─ 🟠 Gemini ──── gemini-2.5 ──── ON ────┤   │
│  └── + 新增分析師                            │   │
└────────────────────────────────────────────────┘
```

## 7. Pipeline Flow

```
┌─────────────────────────────────────────────────────────┐
│                    Daily Cron (6:00 AM)                  │
│                                                         │
│  foreach enabled BriefingTopic:                         │
│    status = "searching"                                 │
│    ┌─────────────────────────────────────┐              │
│    │ Phase 1: Raw Collection             │              │
│    │ foreach subtopic:                   │              │
│    │   search(keywords, region) → entry  │              │
│    │   phase=raw, key=subtopic.name      │              │
│    └──────────────┬──────────────────────┘              │
│                   │                                     │
│    status = "analyzing"                                 │
│    ┌──────────────▼──────────────────────┐              │
│    │ Phase 2: Independent Analysis       │              │
│    │ foreach enabled analyst:            │              │
│    │   analyze(raw_data, prompt)         │              │
│    │   phase=analysis, key=analyst.name  │              │
│    └──────────────┬──────────────────────┘              │
│                   │                                     │
│    status = "debating"                                  │
│    ┌──────────────▼──────────────────────┐              │
│    │ Phase 3: Cross-Debate               │              │
│    │ round-robin analyst responses       │              │
│    │ each analyst reviews others' work   │              │
│    │ phase=debate, key=analyst.name      │              │
│    │ metadata.round = 1, 2, ...          │              │
│    └──────────────┬──────────────────────┘              │
│                   │                                     │
│    status = "synthesizing"                              │
│    ┌──────────────▼──────────────────────┐              │
│    │ Phase 4: Conclusion Synthesis       │              │
│    │ merge all debate results            │              │
│    │ extract consensus + dissent         │              │
│    │ calculate confidence score          │              │
│    │ phase=conclusion, key="synthesis"   │              │
│    └──────────────┬──────────────────────┘              │
│                   │                                     │
│    status = "completed"                                 │
│    event: briefing.daily.completed                      │
└─────────────────────────────────────────────────────────┘

Follow-up Flow (User-triggered):
┌──────────────────────────────────────────────┐
│ User asks question on conclusion page        │
│  → POST /api/briefing/daily/{id}/follow-ups  │
│  → status = "pending"                        │
│  → async: re-query relevant sources          │
│  → analysts generate focused answer          │
│  → status = "completed"                      │
│  → SSE notification → UI updates             │
└──────────────────────────────────────────────┘
```

## 8. DB Migration Strategy

### 8.1 Alembic Migration Script

```python
"""Move briefing tables from intelflow to briefing schema."""

def upgrade():
    # 1. Create new schema
    op.execute("CREATE SCHEMA IF NOT EXISTS briefing")

    # 2. Move existing tables (preserves data + indexes)
    for table in [
        "briefing_topics", "briefing_subtopics",
        "briefings", "briefing_entries",
        "briefings_archive", "briefings_frozen",
    ]:
        op.execute(f"ALTER TABLE intelflow.{table} SET SCHEMA briefing")

    # 3. Update FK references (self-referencing FKs auto-follow)
    # 4. Create new tables in briefing schema
    #    - briefing_analysts
    #    - briefing_follow_ups

    # 5. Update ENTRY_PHASES check (if exists) to include 'conclusion'
    # 6. Update BRIEFING_STATUSES to include 'synthesizing'

def downgrade():
    # Move tables back to intelflow schema
    for table in [...]:
        op.execute(f"ALTER TABLE briefing.{table} SET SCHEMA intelflow")
    op.execute("DROP TABLE IF EXISTS briefing.briefing_analysts")
    op.execute("DROP TABLE IF EXISTS briefing.briefing_follow_ups")
    op.execute("DROP SCHEMA IF EXISTS briefing")
```

### 8.2 Migration Safety

- `ALTER TABLE ... SET SCHEMA` is metadata-only, instant, no data copy
- FK constraints between tables that ALL move together = no issue
- The only cross-schema FK was `briefings.topic_id → briefing_topics.id` — both move together
- No FK from intelflow to briefing tables (reports don't reference briefings)
- intelflow dashboard `total_briefings` counter → change to cross-module service call

## 9. Implementation Phases

### Phase A: Backend Module Extraction (Non-Breaking)
1. Create `core/src/modules/briefing/` with all 6 files
2. Move models from intelflow (change SCHEMA = "briefing")
3. Move services (BriefingService, BriefingTopicService)
4. Move routes (re-prefix to `/api/briefing/`)
5. Add new models: BriefingAnalyst, BriefingFollowUp
6. Add new services: AnalystService, FollowUpService
7. Add new endpoints: analysts CRUD, follow-ups, daily summary
8. Alembic migration: move tables + create new tables
9. Register briefing router in main.py
10. Update intelflow: remove briefing code, update dashboard
11. Update test_lifecycle_imports.py

### Phase B: Frontend Module (Zero Breaking Change)
1. Create `workbench/src/modules/briefing/`
2. BriefingLayout (independent, CSS vars)
3. TodayBriefing landing (merged conclusion)
4. BriefingDetail (3 tabs: conclusion/debate/raw)
5. DebateBubble component (chat bubble style)
6. FollowUpInput + FollowUpThread
7. BriefingConfig (topics + subtopics + analysts)
8. DateNavigator component
9. Register `/briefing` route in app router
10. Build + verify

### Phase C: Pipeline Enhancement
1. Extend briefing runner for Phase 4 (conclusion synthesis)
2. Follow-up generation pipeline
3. SSE for real-time follow-up status
4. Deprecate intelflow's `/intelflow/briefings` routes (keep temporarily)

### Phase D: Cleanup
1. Remove intelflow front-end briefing pages (after stable period)
2. Remove intelflow briefing API endpoints
3. Remove legacy JSONB fields from briefing model (after data migration)

## 10. Shared vs New

| 資源 | 策略 | 備註 |
|------|------|------|
| CSS variables | 新定義 `--bf-*` | 可 alias 到 `--if-*` 初期，後續獨立演化 |
| MarkdownBlock | 抽至 `shared/components/` | briefing + intelflow 共用 |
| DB schema | **完全獨立** `briefing` | 獨立演化，不影響 intelflow |
| API prefix | `/api/briefing/` | 符合慣例 `module name = API prefix` |
| Events | `briefing.*` namespace | `briefing.daily.completed`, `briefing.follow_up.answered` |
| Error codes | `briefing.*` | `briefing.not_found`, `briefing.analyst_not_found` |
| Layout | 全新 BriefingLayout | 獨立導航結構 |
| Store | 全新 Zustand store | `briefing-cache` |

## 11. Open Questions

- [ ] Follow-up 生成用哪個 analyst？全部重跑還是指定一個？
- [ ] 結論合併邏輯：simple concat 還是再跑一次 LLM 合成？
- [ ] Debate round 數量上限？（建議 2-3 rounds）
- [ ] Follow-up 是否有每日上限？（建議 10 次/天）
- [ ] 是否需要 SSE 即時更新，還是 polling 就夠？
- [ ] 舊 intelflow briefing 資料是否需要回填遷移？
- [ ] CSS 變數要直接 copy --if-* 還是建立 --bf-* alias？
