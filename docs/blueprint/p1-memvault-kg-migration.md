---
doc_version: 1
content_hash: pending
target_lang: zh-TW
created: 2026-02-25
status: ready-to-execute
---

> [← 返回 P1：Memvault](./p1-memvault.md)

# P1-KG：Knowledge Graph 遷移至 Memvault V2

## 0. 背景

V1 KAS Memory 已在 `~/Claude/projects/kas-memory/` 完成三層 Knowledge Graph 原型：

| 層級 | V1 現況 | 數據量 |
|------|---------|--------|
| L0 Raw Triples | SQLite `triple` 表 + `triples/*.jsonl` | 1,461 rows |
| L1 Clusters | SQLite `cluster` + `cluster_triple` 表 | 13 clusters |
| L2 Wisdom | SQLite `wisdom_node` 表 | 9 nodes (7 HIGH) |
| Attitude | SQLite `attitude_fact` 表 | 207 facts |
| Skill | SQLite `skill_invocation` + `skill_proficiency` 表 | hook 剛啟用 |

V2 Memvault（`core/src/modules/memvault/`）已有 4 表：blocks, tags, knowledge_domains, profile_scores。
本計劃將 V1 KG 概念**適配**進 V2 架構，而非單純搬移。

---

## 1. 架構設計決策

### 1.1 遵循 V2 慣例

| V1 做法 | V2 適配 |
|---------|---------|
| SQLite + auto-increment ID | PostgreSQL + `String(32)` hex UUID (SpaceScopedModel) |
| 無 space_id | 所有表繼承 SpaceScopedModel，預設 `"default"` |
| 直接 sqlite3 操作 | SQLAlchemy ORM + BaseCRUDService |
| 獨立 scripts 直寫 DB | Pipeline scripts → Core API (HTTP) |
| 無事件系統 | EventBus publish（`memvault.triple.*`, `memvault.cluster.*`） |
| JSON string 欄位 | PostgreSQL `ARRAY(Text)` / `JSONB` 原生型別 |

### 1.2 檔案組織

KG 功能作為 memvault 模組的**擴展**，使用 `kg_` 前綴檔案避免現有檔案膨脹：

```
core/src/modules/memvault/
├── models.py           # 現有（不動）
├── schemas.py          # 現有（不動）
├── services.py         # 現有（不動）+ 新增 cascade_recall 方法
├── routes.py           # 現有（不動）
├── kg_models.py        # NEW — Triple, Cluster, ClusterTriple, WisdomNode, AttitudeFact, SkillInvocation
├── kg_schemas.py       # NEW — KG 相關 Pydantic schemas
├── kg_services.py      # NEW — TripleService, ClusterService, WisdomService, AttitudeService, SkillTrackingService
├── kg_routes.py        # NEW — /api/memvault/kg/* 端點
├── kg_config.py        # NEW — Predicate vocabulary, constants
├── embedding.py        # 現有（共用，不動）
├── events.py           # 現有（擴展 KG 事件）
├── deps.py             # 現有（不動）
└── __init__.py         # 更新：掛載 kg_routes router
```

MCP 層和 Pipeline 腳本：

```
mcp/memvault/
├── server.py           # 現有（擴展 KG MCP 工具）
├── scripts/
│   ├── extract-v2.sh          # 現有 SessionEnd hook（不動）
│   ├── extract-triples.sh     # V1 搬入 + 適配：output → POST Core API
│   ├── validate-triples.py    # V1 搬入（可原樣保留，作為 pre-processing）
│   └── prompts/
│       └── triple-extraction.txt  # V1 搬入（Gemini Flash prompt）
└── pipelines/
    ├── cluster_pipeline.py    # V1 cluster-triples.py 適配：SQLAlchemy + Core API
    ├── wisdom_pipeline.py     # V1 generate-wisdom.py 適配
    └── attitude_pipeline.py   # NEW — Mem0 pattern ADD/UPDATE/NOOP
```

### 1.3 不需要的（YAGNI）

- ~~`kg_models.py` 中的 `SkillProficiency` materialized view~~ → 用 SQL aggregation query 代替
- ~~獨立的 `ingest-triples.py` / `ingest-corrections.py`~~ → 直接透過 API 端點 ingest
- ~~`init-kg-db.py`~~ → 由 Alembic migration 取代
- ~~JSONL 中繼儲存~~ → Pipeline 直接寫入 PostgreSQL

---

## 2. 資料庫設計

### 2.1 新增表（memvault schema）

#### `triples`（Knowledge L0）

| 欄位 | 型別 | 說明 |
|------|------|------|
| (SpaceScopedModel 繼承欄位) | id, space_id, created_by, created_at, updated_at | |
| source_session | String(64), nullable | 來源 session |
| timestamp | DateTime(tz), nullable | 原始 session 時間 |
| subject | String(500), not null | Triple 主詞 |
| predicate | String(100), not null | 從 20-predicate vocabulary |
| object | Text, not null | Triple 受詞 |
| topic | String(500), nullable | Session 主題 |
| embedding | Vector(768), nullable | nomic-embed-text embedding |

索引：
- `idx_triples_session` — source_session
- `idx_triples_predicate` — predicate
- `idx_triples_subject` — subject
- `idx_triples_embedding` — HNSW (cosine, m=16, ef=64)
- UNIQUE: `(space_id, source_session, subject, predicate, object)`

#### `clusters`（Knowledge L1）

| 欄位 | 型別 | 說明 |
|------|------|------|
| (SpaceScopedModel) | | |
| name | String(200), not null | 聚類名稱 |
| size | Integer, not null | 包含 triple 數 |
| top_subjects | ARRAY(Text) | 高頻主詞 |
| top_predicates | ARRAY(Text) | 高頻述詞 |
| top_objects | ARRAY(Text) | 高頻受詞 |
| summary | Text, nullable | 「情境→判斷→結果」摘要 |
| verdict | String(20), default 'UNVERIFIED' | UNVERIFIED / VERIFIED / OUTDATED |
| generation_batch | String(32), nullable | 同批次生成的標記 |

#### `cluster_triples`（多對多關聯）

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | String(32), PK | UUID |
| cluster_id | String(32), FK → clusters.id | |
| triple_id | String(32), FK → triples.id | |
| confidence | Float, nullable | GMM 後驗概率 |
| space_id | String(32) | 隔離用 |

#### `wisdom_nodes`（Knowledge L2）

| 欄位 | 型別 | 說明 |
|------|------|------|
| (SpaceScopedModel) | | |
| wisdom | Text, not null | 合成的經驗法則（繁體中文） |
| confidence | String(20), not null | HIGH / MEDIUM / LOW |
| bridge_entity | String(200), not null | 跨聚類連接實體 |
| cluster_ids | ARRAY(Text), not null | 關聯的 cluster ID 列表 |
| evidence_count | Integer, nullable | 支撐證據數 |
| tags | ARRAY(Text) | 標籤 |
| verified | Boolean, default False | 人工驗證標記 |

#### `attitude_facts`（Attitude Layer）

| 欄位 | 型別 | 說明 |
|------|------|------|
| (SpaceScopedModel) | | |
| fact | Text, not null | 態度事實描述 |
| category | String(100), not null | workflow / tool_behavior / config / architecture / preference / ... |
| operation | String(20), not null | ADD / UPDATE / NOOP |
| confidence | Float, default 0.5 | 信心分數 |
| source_sessions | ARRAY(Text) | 來源 session ID 列表 |
| superseded_by | String(32), FK → self, nullable | NULL = 當前有效 |
| previous_version | String(32), FK → self, nullable | UPDATE 時指向前版本 |
| embedding | Vector(768), nullable | 用於語意比對去重 |

索引：
- `idx_af_category` — category
- `idx_af_current` — WHERE superseded_by IS NULL（partial index）
- `idx_af_embedding` — HNSW (cosine)

#### `skill_invocations`（Skill Layer）

| 欄位 | 型別 | 說明 |
|------|------|------|
| (SpaceScopedModel) | | |
| skill_name | String(200), not null | |
| source_session | String(64), not null | |
| cwd | String(500), nullable | |
| invoked_at | DateTime(tz), not null | |
| outcome | String(20), default 'unknown' | success / failure / partial / unknown |
| duration_ms | Integer, nullable | |

索引：
- `idx_si_skill` — skill_name
- `idx_si_session` — source_session
- UNIQUE: `(space_id, skill_name, source_session, invoked_at)`

### 2.2 Alembic Migration

新增一個 migration file: `xxxx_add_memvault_kg_tables.py`
- 6 個新表
- 保留現有 4 表不動
- pgvector extension 已在先前 migration 建立

---

## 3. Core 模組實作

### 3.1 kg_config.py — 常數與配置

```python
# 20 predicates in 7 categories
PREDICATE_VOCABULARY = {
    "dependency": ["uses", "requires", "depends_on"],
    "config":     ["configured_with", "format_is", "default_is"],
    "causation":  ["causes", "prevents", "fixes", "enables"],
    "normative":  ["should", "should_NOT"],
    "pattern":    ["pattern_is", "flow_is", "implemented_as"],
    "decision":   ["chosen_over", "reason_for"],
    "effect":     ["improves", "degrades"],
    "mapping":    ["maps_to"],
}

# 40+ alias → canonical predicate mapping
PREDICATE_ALIASES = {
    "depends on": "depends_on", "needs": "requires",
    "is configured with": "configured_with", ...
}

ATTITUDE_CATEGORIES = [
    "workflow", "tool_behavior", "config", "architecture",
    "preference", "testing_philosophy", "autonomy_level",
    "safety", "design_preference",
]

CLUSTER_VERDICTS = ["UNVERIFIED", "VERIFIED", "OUTDATED"]
WISDOM_CONFIDENCE = ["HIGH", "MEDIUM", "LOW"]
SKILL_OUTCOMES = ["success", "failure", "partial", "unknown"]
```

### 3.2 kg_models.py — SQLAlchemy Models

6 個 model，全部繼承 `SpaceScopedModel`，schema = `"memvault"`。

### 3.3 kg_schemas.py — Pydantic Schemas

| Schema | 用途 |
|--------|------|
| TripleCreate / TripleResponse | Triple CRUD |
| TripleBatchCreate | 批次 ingest（從 extract-triples.sh） |
| ClusterResponse / ClusterDetail | 聚類查看 |
| WisdomNodeResponse | Wisdom 查看 |
| AttitudeFactCreate / Update / Response | Attitude CRUD |
| AttitudeEvolution | Mem0 pattern（input: fact → output: operation + result） |
| SkillInvocationCreate / Response | Skill tracking |
| SkillProficiencyResponse | 聚合統計（非 DB 表，而是 SQL 計算） |
| CascadeRecallResult | 多層 recall 結果 |

### 3.4 kg_services.py — Business Logic

| Service | 繼承 | 核心方法 |
|---------|------|---------|
| `TripleService(BaseCRUDService)` | BaseCRUD | `batch_ingest()`, `search_by_predicate()`, `semantic_search()` |
| `ClusterService` | standalone | `get_all_clusters()`, `get_cluster_detail()`, `regenerate()` (觸發 pipeline) |
| `WisdomService` | standalone | `list_wisdoms()`, `regenerate()` (觸發 pipeline) |
| `AttitudeService(BaseCRUDService)` | BaseCRUD | `evolve()` (ADD/UPDATE/NOOP), `get_current()` (WHERE superseded_by IS NULL) |
| `SkillTrackingService` | standalone | `record_invocation()`, `get_proficiency()` (SQL aggregation) |
| `CascadeRecallService` | standalone | `recall(query, mode)` — L2→L1→L0→blocks 分層 |

**CascadeRecallService.recall() 邏輯**：

```
1. Embed query via embedding.py
2. Search wisdom_nodes (L2) — if match (cosine > 0.7), return
3. Search clusters (L1) — match cluster summaries
4. Search triples (L0) — semantic search
5. Search blocks (existing) — fallback
6. Merge & deduplicate, return ranked results
```

### 3.5 kg_routes.py — API 端點

掛載在 `/api/memvault/kg/`，由 `__init__.py` include：

| 方法 | 路由 | 功能 |
|------|------|------|
| **Triples** | | |
| POST | `/kg/triples` | 建立單一 triple |
| POST | `/kg/triples/batch` | 批次 ingest（from pipeline） |
| GET  | `/kg/triples` | 查詢（predicate, subject, object 過濾） |
| GET  | `/kg/triples/search` | 語意搜尋 |
| **Clusters** | | |
| GET  | `/kg/clusters` | 所有聚類 summaries |
| GET  | `/kg/clusters/{id}` | 聚類詳情（含 triples） |
| POST | `/kg/clusters/regenerate` | 觸發重新聚類 |
| **Wisdom** | | |
| GET  | `/kg/wisdom` | 所有 wisdom nodes |
| POST | `/kg/wisdom/regenerate` | 觸發 wisdom 合成 |
| **Attitude** | | |
| GET  | `/kg/attitudes` | 當前有效態度（WHERE superseded_by IS NULL） |
| POST | `/kg/attitudes` | 新增態度事實 |
| POST | `/kg/attitudes/evolve` | Mem0 pattern 演化（input: fact → detect ADD/UPDATE/NOOP） |
| GET  | `/kg/attitudes/history/{id}` | 單一態度的演化歷程 |
| **Skill Tracking** | | |
| POST | `/kg/skills/invoke` | 記錄 skill invocation |
| GET  | `/kg/skills/proficiency` | 所有 skill proficiency（SQL 聚合） |
| GET  | `/kg/skills/{name}/history` | 單一 skill 歷史 |
| **Cascade Recall** | | |
| GET  | `/kg/recall` | L2→L1→L0→blocks 分層檢索 |

### 3.6 events.py 擴展

新增事件常數到 `MemvaultEvents`：

```python
# KG events
TRIPLE_INGESTED = "memvault.triple.ingested"
TRIPLE_BATCH_INGESTED = "memvault.triple.batch_ingested"
CLUSTER_REGENERATED = "memvault.cluster.regenerated"
WISDOM_REGENERATED = "memvault.wisdom.regenerated"
ATTITUDE_EVOLVED = "memvault.attitude.evolved"
SKILL_INVOKED = "memvault.skill.invoked"
```

---

## 4. MCP 工具擴展

在 `mcp/memvault/server.py` 新增工具：

| 工具名 | Core API 端點 | 說明 |
|--------|-------------|------|
| `memvault_kg_search` | `GET /kg/triples/search` | Triple 語意搜尋 |
| `memvault_kg_clusters` | `GET /kg/clusters` | 聚類列表 |
| `memvault_kg_wisdom` | `GET /kg/wisdom` | Wisdom nodes |
| `memvault_kg_cascade_recall` | `GET /kg/recall` | L2→L1→L0→blocks 分層檢索 |
| `memvault_attitude_current` | `GET /kg/attitudes` | 當前有效態度 |
| `memvault_attitude_evolve` | `POST /kg/attitudes/evolve` | 態度演化 |
| `memvault_skill_proficiency` | `GET /kg/skills/proficiency` | Skill 熟練度 |

現有 `memvault_recall` 新增 `mode` 參數：`mode="cascade"` 時走 KG recall 端點。

---

## 5. Pipeline 適配

### 5.1 extract-triples.sh（每 Session）

V1 行為：Gemini Flash 提煉 → 寫入 JSONL
V2 適配：Gemini Flash 提煉 → `validate-triples.py` → POST `/api/memvault/kg/triples/batch`

保留 JSONL 作為 fallback（Core API 不可用時），與 `extract-v2.sh` 的 V1 fallback 策略一致。

### 5.2 cluster_pipeline.py（週期批次）

V1 行為：直接讀寫 SQLite + Ollama embed + scikit-learn GMM
V2 適配：
1. `GET /api/memvault/kg/triples` → 取得所有 triples
2. Ollama embed（可複用 `embedding.py`）
3. scikit-learn GMM clustering（PCA 50d + diag covariance）
4. `POST /api/memvault/kg/clusters/regenerate` → 寫入結果

依賴：`scikit-learn`, `numpy`（pipeline 獨立環境，不影響 Core）

### 5.3 wisdom_pipeline.py（週期批次）

V1 行為：偵測跨聚類橋樑 → Gemini Flash 合成
V2 適配：
1. `GET /api/memvault/kg/clusters` → 取得聚類
2. 偵測 bridge entities（出現在 2+ clusters 的 subjects/objects）
3. Gemini Flash 合成 wisdom
4. `POST /api/memvault/kg/wisdom/regenerate` → 寫入結果

### 5.4 attitude_pipeline.py（每 Session，隨 corrections 觸發）

全新 pipeline，實作 Mem0 pattern：
1. 接收新 correction fact
2. `GET /api/memvault/kg/attitudes` → 取得現有態度
3. Embed 新 fact + 現有 facts
4. Cosine similarity 比對：
   - `> 0.9` → NOOP（bump confidence）
   - `> 0.8` → UPDATE（supersede old, create new）
   - `< 0.8` → ADD（新增）
5. `POST /api/memvault/kg/attitudes/evolve` → 寫入結果

---

## 6. V1 資料遷移

### 6.1 一次性遷移腳本

`mcp/memvault/scripts/migrate-v1-kg.py`：

1. 讀取 V1 `kas-kg.db` SQLite
2. 轉換 ID：auto-increment → UUID hex
3. 加入 `space_id = "default"`
4. 寫入 V2 PostgreSQL via Core API

| V1 表 | V2 表 | 遷移量 |
|-------|-------|--------|
| triple (1461) | triples | 全量 |
| cluster (13) | clusters | 全量 |
| cluster_triple | cluster_triples | 全量（ID 映射） |
| wisdom_node (9) | wisdom_nodes | 全量 |
| attitude_fact (207) | attitude_facts | 全量 |
| skill_invocation | skill_invocations | 全量 |

### 6.2 遷移驗證

- Row count 比對
- 隨機抽樣 10 rows 比對內容
- Cascade recall 測試：同一 query 在 V1 和 V2 應回傳相似結果

---

## 7. 設計文件處理

| V1 文件 | 處理方式 |
|---------|---------|
| `docs/v2-schema.md` | 本文件取代（V2 schema 已在 §2 定義） |
| `docs/three-layer-redesign.md` | 歸檔至 `~/workshop/docs/reference/memvault-kg-research.md`（研究基礎，保留參考價值） |

---

## 8. 執行計劃

### Phase 1：資料庫 + Models（基礎層）

| # | 任務 | 產出檔案 | 可並行 |
|---|------|---------|--------|
| 1.1 | 建立 kg_config.py | `core/src/modules/memvault/kg_config.py` | Yes |
| 1.2 | 建立 kg_models.py | `core/src/modules/memvault/kg_models.py` | Yes |
| 1.3 | 建立 kg_schemas.py | `core/src/modules/memvault/kg_schemas.py` | Yes |
| 1.4 | 建立 Alembic migration | `core/migrations/versions/xxxx_add_memvault_kg_tables.py` | After 1.2 |
| 1.5 | 擴展 events.py | `core/src/events/types.py` | Yes |

### Phase 2：Services + Routes（業務層）

| # | 任務 | 產出檔案 | 可並行 |
|---|------|---------|--------|
| 2.1 | 建立 kg_services.py | `core/src/modules/memvault/kg_services.py` | After Phase 1 |
| 2.2 | 建立 kg_routes.py | `core/src/modules/memvault/kg_routes.py` | After 2.1 |
| 2.3 | 更新 __init__.py | `core/src/modules/memvault/__init__.py` | After 2.2 |
| 2.4 | CascadeRecallService | 包含在 2.1 | |

### Phase 3：Pipeline + MCP（整合層）

| # | 任務 | 產出檔案 | 可並行 |
|---|------|---------|--------|
| 3.1 | 搬入 + 適配 extract-triples.sh | `mcp/memvault/scripts/extract-triples.sh` | Yes |
| 3.2 | 搬入 validate-triples.py + prompt | `mcp/memvault/scripts/validate-triples.py` + `prompts/` | Yes |
| 3.3 | 適配 cluster_pipeline.py | `mcp/memvault/pipelines/cluster_pipeline.py` | Yes |
| 3.4 | 適配 wisdom_pipeline.py | `mcp/memvault/pipelines/wisdom_pipeline.py` | Yes |
| 3.5 | 新建 attitude_pipeline.py | `mcp/memvault/pipelines/attitude_pipeline.py` | Yes |
| 3.6 | 擴展 MCP server.py | `mcp/memvault/server.py` | After Phase 2 |

### Phase 4：遷移 + 驗證

| # | 任務 | 產出 | 可並行 |
|---|------|------|--------|
| 4.1 | V1 資料遷移腳本 | `mcp/memvault/scripts/migrate-v1-kg.py` | After Phase 2 |
| 4.2 | 執行遷移 + 驗證 | Row count + 抽樣比對 | After 4.1 |
| 4.3 | Cascade recall E2E 測試 | 真實 query 驗證 | After 4.2 |
| 4.4 | 歸檔 V1 設計文件 | `docs/reference/memvault-kg-research.md` | Yes |

### Phase 5：V1 未完成項目 ✅ 完成（2026-02-26）

| # | 任務 | 狀態 | 產出 |
|---|------|------|------|
| 5.1 | Cascade recall 實作 | ✅ | `CascadeRecallService` — L2→L1→L0→blocks 分層檢索 |
| 5.2 | Attitude evolution pipeline | ✅ | `pipelines/attitude_pipeline.py` |
| 5.3 | extract-triples.sh → auto-ingest | ✅ | POST `/api/memvault/kg/triples/batch` + JSONL fallback |
| 5.4 | 新 MCP tools 上線 | ✅ | 7 KG tools + `memvault_recall mode=cascade` |
| 5.5 | SessionEnd hook 串接 | ✅ | `extract-v2-async.sh` 並行 extract-v2 + extract-triples |
| 5.6 | Skill invocation hook 連接 | ✅ | `skill-tracker-v2.sh` → POST Core API + JSONL fallback |

Hook 更新：三個 V1 路徑已從 `settings.json` 切換至 V2：
- SessionEnd: `kas-memory/extract-async.sh` → `workshop/mcp/memvault/scripts/extract-v2-async.sh`
- PostToolUse (Skill): `kas-memory/skill-tracker.sh` → `workshop/mcp/memvault/scripts/skill-tracker-v2.sh`
- UserPromptSubmit: `kas-memory/recall.sh` → `workshop/mcp/memvault/scripts/recall-v2.sh`

### Phase 6：進階功能（Growth Loops）

| # | 任務 | 狀態 | 優先級 | 產出 |
|---|------|------|--------|------|
| 6.1 | Knowledge Flywheel | ✅ | HIGH | `skill-tracker-v2.sh` 擴展：知識 skill 產出自動存為 `skill_knowledge` block |
| 6.2 | Skill Proficiency L2 | 🔲 | MEDIUM | 待後續迭代（需偏好分析邏輯） |
| 6.3 | Attitude Calibration | 🔲 | LOW | 待後續迭代（需行為數據積累） |
| 6.4 | Confidence decay | ✅ | MEDIUM | `ConfidenceDecayService` + `/kg/decay` API + pipeline 腳本 |
| 6.5 | Galaxy Widget | 🔲 | LOW | 待前端開發 |

---

## 9. 並行執行策略

Phase 1（5 個檔案）→ 全部可並行，3 個 sub-agent 同時產出 ✅
Phase 2（3 個檔案）→ 1 個 agent 順序執行 ✅
Phase 3（6 個任務）→ Pipeline 搬入/適配可並行（3.1-3.5），MCP 擴展需等 Phase 2 ✅
Phase 4（4 個任務）→ 需順序執行 ✅
Phase 4.5（rename）→ kas → memvault 全面重命名 ✅
Phase 5（6 個任務）→ Hook 串接 + 整合 ✅
Phase 6（2/5 完成）→ Knowledge Flywheel + Confidence Decay ✅, 其餘待後續

**預估 Phase 1-4 可一次完成，Phase 5-6 為後續迭代。**

---

## 10. 風險與開放問題

| 風險 | 緩解 |
|------|------|
| Pipeline 依賴 scikit-learn/numpy | Pipeline 獨立 venv，不影響 Core |
| Ollama 離線 | 已有 graceful degradation（ILIKE fallback） |
| V1 資料遷移 ID 映射 | 建立 old_id → new_id 映射表，cluster_triples FK 同步更新 |
| Cluster/Wisdom regeneration 耗時 | 設為 async background task，非同步回覆 |
| Attitude cosine 閾值不精確 | 初期 0.8，可配置化後調整 |

---

**本文件即為執行藍圖，Phase 1-4 可直接開始。**
