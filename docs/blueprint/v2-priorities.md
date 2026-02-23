---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

# V2 優先開發藍圖

> 不按 Phase 1-4 線性推進，而是以**實際需求痛點**為驅動力，優先打造最有價值的模組。

---

## 優先順序

| 順位 | 模組 | 目標 | 為什麼優先 |
|------|------|------|-----------|
| **P1** | lore (KAS Memory V2) | Claude Code 持久化記憶 | 每天都在用，改善記憶品質 = 改善所有工作品質 |
| **P2** | scout (Smart Search V2) | 搜尋報告結構化儲存 + UI | 搜尋是高頻操作，散落 .md 檔已造成痛點 |

---

## P1：Lore 模組 — KAS Memory V2

### 現況分析

KAS Memory 目前是獨立專案（`~/Claude/projects/kas-memory/`），採用檔案系統架構：

| 層級 | 儲存 | 問題 |
|------|------|------|
| Layer A | `MEMORY.md`（always-loaded, 200 行上限） | 空間有限，需精挑細選 |
| Layer B | `memories/YYYY-MM/*.md` + `tags.idx` | 純文字，併發寫入風險，無 ACID |
| Layer C | `embeddings.json`（Ollama 768d） | 單檔 JSON，隨記憶增長效能下降 |

**MCP Server**：9 個工具（kas_recall, kas_extract, kas_promote 等），TypeScript 實作
**SessionEnd Hook**：`extract-async.sh` → Gemini Flash + Haiku 雙 LLM 提煉 → Galaxy 重建
**Galaxy 視覺化**：`galaxy-data.json` → `galaxy-explorer.html`（K/A/S 三維星系圖）

### V2 目標

將 KAS Memory 從「檔案系統工具」重構為「Workshop Core 模組」，同時保持 MCP 介面。

#### 1. 資料層遷移：File → PostgreSQL + pgvector

```
現況：memories/*.md + tags.idx + embeddings.json
  ↓
目標：PostgreSQL (schema: lore)
  ├── lore_blocks       — 記憶區塊（取代 .md 檔案）
  ├── lore_tags         — 標籤索引（取代 tags.idx）
  ├── lore_embeddings   — 向量欄位（取代 embeddings.json，pgvector）
  ├── knowledge_domains — 知識域（取代 knowledge/domains/*.md）
  └── kas_profiles      — KAS 四維 Profile（取代 profile.json）
```

**優勢**：
- ACID 保證（解決併發寫入問題）
- pgvector 原生向量搜尋（取代自製 JSON cosine similarity）
- SQL 查詢彈性（時間範圍、tag 組合、跨表 JOIN）
- 與 Workshop 其他模組共享 PostgreSQL 基礎設施

#### 2. KS 星系（Knowledge-Skill Galaxy）

從提煉的記憶中自動發展知識域與技能圖譜：

```
Session 對話
    │
    ▼
SessionEnd Hook 提煉
    │
    ├── 知識碎片 → Knowledge Domain 聚合
    │     「學到了 pgvector 的 HNSW 索引」→ 累積到 Database 知識域
    │
    ├── 技能驗證 → Skill Tree 成長
    │     「成功用 playwright 自動化測試」→ Browser Automation 技能 +1
    │
    └── 態度記錄 → Attitude Profile 演化
          「決定採用漸進式重構而非全面重寫」→ 決策風格更新
```

**Galaxy 視覺化升級**：從靜態 HTML 升級為 Workbench Widget，即時反映最新狀態。

#### 3. 多 Agent 態度系統（Attitude Dimension）

KAS 的 A（Attitude）不只是記錄少爺的決策風格，更是多 Agent 協作的基礎：

```
┌──────────────────────────────────────────┐
│           Memory Core (共享記憶池)         │
├──────────┬──────────┬────────────────────┤
│ Agent A  │ Agent B  │ Agent C            │
│ 樂觀派   │ 悲觀派   │ 務實派              │
│ 探索新方向│ 質疑風險  │ 權衡成本效益         │
└──────────┴──────────┴────────────────────┘
         │         │         │
         └─────────┼─────────┘
                   ▼
            共識記憶 → 寫回 Memory
```

- 每個 Agent 可以帶有不同的 Attitude Profile（立場偏好）
- 多 Agent 並發討論後，結論寫回共享記憶池
- Attitude 維度追蹤：risk_preference, decision_style, communication_style

#### 4. Recall 整合

兩個「Recall」工具互補共存：

| 工具 | 用途 | 整合方式 |
|------|------|---------|
| `kas_recall`（MCP） | 結構化記憶搜尋（tags + vector） | UserPromptSubmit hook 自動注入 |
| `zippoxer/recall`（CLI TUI） | 歷史 session 全文搜尋 | 手動查詢；kas_recall miss 時建議使用 |

**整合流程**：
1. `kas_recall` 先搜結構化記憶
2. 若命中率低 → 建議：「記憶中未找到相關內容，可用 `recall` 搜尋歷史 session 原文」
3. 從 `recall` 找到的原文 → 可手動觸發 `kas_extract` 回填為結構化記憶

### 技術架構

```
workbench/src/modules/lore/       ← Lore UI（Galaxy Widget、記憶瀏覽器）
core/src/modules/lore/            ← Lore 後端（API + DB + 提煉引擎）
mcp/lore/                         ← MCP Adapter（保持現有 9 個工具介面）
```

### 遷移策略

1. **Phase A**：在 Core 中建立 lore schema + API，匯入現有 .md 記憶
2. **Phase B**：切換 MCP Server 為 Core API 的薄適配器（而非直接讀檔案）
3. **Phase C**：升級 SessionEnd Hook 寫入 DB 而非 .md
4. **Phase D**：Workbench Widget（Galaxy + 記憶瀏覽器）

---

## P2：Scout 模組 — Smart Search V2

### 現況分析

Smart Search 已有兩個元件：

| 元件 | 位置 | 狀態 |
|------|------|------|
| `smart-search` Skill | `~/.claude/skills/smart-search/` | 運作中，v0.3.3 |
| `research_report` Service | `~/Claude/services/research_report/` | 運作中，port 8830 |

**已有的好東西**：
- PostgreSQL + pgvector（schema `pulso_research`，768d Ollama embedding）
- 完整 REST API（CRUD + semantic search + topic graph + dashboard）
- 前端 Research Hub（port 3005）
- 52 個 .md fallback 檔案待回填

**V1 Daily Briefing 的優秀設計**（值得保留）：
- 三 AI 分析師互相辯論（Claude + Codex + Gemini）
- 五領域分類（finance / ai / tech / geopolitics / weather）
- raw → analysis → debate 三層管線
- 極端立場判定 + 被忽略角度挖掘

### V2 目標

將散落的搜尋/情報能力整合為 Workshop Core 的 `scout` 模組。

#### 1. 資料層整合：獨立 Service → Core Module

```
現況：
  ~/Claude/services/research_report/  (獨立 FastAPI, port 8830)
  ~/Claude/skills/smart-search/*.md   (52 個 fallback 檔案)
  ~/Claude/skills/daily-briefing/     (靜態 HTML)
  ↓
目標：
  core/src/modules/scout/             (Core Module)
  ├── schema: scout                   (PostgreSQL)
  │   ├── reports          — 搜尋/研究報告
  │   ├── report_embeddings — pgvector 向量（768d / 1536d）
  │   ├── topics           — 主題分類
  │   ├── topic_relations  — 主題關聯圖
  │   ├── briefings        — 每日情報彙整
  │   └── search_sessions  — 搜尋紀錄
  │
  └── API: /api/scout/
      ├── reports/         — CRUD + 語意搜尋
      ├── topics/          — 主題管理 + 關聯圖
      ├── briefings/       — 每日情報
      ├── search/          — 語意搜尋端點
      └── dashboard/       — 統計 + 時序圖
```

#### 2. Smart Search Skill 對接

```
smart-search Skill (Claude Code)
    │
    ├── Pre-Search: POST /api/scout/search/check  ← 查重（pgvector 相似度）
    │
    ├── 執行搜尋（DeepWiki / Context7 / Perplexity / 9 平台社群）
    │
    └── Post-Search: POST /api/scout/reports      ← 寫入報告 + 自動 embedding
                                                     不再 fallback 到 .md
```

#### 3. UI 升級：Research Hub → Workbench Module

保留 V1 的好設計，以 Workbench 模組形式重建：

| 頁面 | 功能 |
|------|------|
| `/scout` | 情報總覽（最新報告、趨勢圖、主題圖譜） |
| `/scout/reports` | 報告列表（全文搜尋 + 語意搜尋 + tag 過濾） |
| `/scout/reports/:id` | 報告詳情（Markdown 渲染 + 來源連結） |
| `/scout/topics` | 主題圖譜（Force-directed graph 視覺化） |
| `/scout/briefings` | 每日情報（三分析師辯論格式） |
| Widget | Workbench 首頁摘要 Widget（最新 5 篇 + 趨勢） |

#### 4. Daily Briefing 整合

V1 的三 AI 辯論模式整合到 scout 模組：

```
每日觸發（cron 或手動）
    │
    ├── 資料收集：RSS + 社群 + WebSearch
    │
    ├── 三分析師獨立分析：
    │   ├── Claude  → analysis/claude.md
    │   ├── Codex   → analysis/codex.md
    │   └── Gemini  → analysis/gemini.md
    │
    ├── 交叉辯論：debate/synthesis.md
    │
    └── 寫入 DB：POST /api/scout/briefings
        （含 embedding，可語意搜尋歷史情報）
```

### 技術架構

```
workbench/src/modules/scout/      ← Scout UI（報告瀏覽、主題圖譜、情報總覽）
core/src/modules/scout/           ← Scout 後端（API + DB + pgvector + 提煉）
mcp/scout/                        ← MCP Adapter（供 Claude Code 直接操作）
```

### 遷移策略

1. **Phase A**：在 Core 中建立 scout schema，匯入 research_report DB 資料 + 52 個 .md 回填
2. **Phase B**：切換 smart-search Skill 端點從 `localhost:8830` → Core API
3. **Phase C**：Workbench 模組（報告瀏覽器 + 主題圖譜）
4. **Phase D**：Daily Briefing 整合（三分析師管線）

---

## 與現有藍圖的關係

| 現有文件 | 處置 |
|---------|------|
| `v2-blueprint.md` | 保留作為長期願景參考，但實際執行順序以本文件為準 |
| `v2-worktree-todos.md` | 保留，待 P1/P2 完成後再回頭處理 |
| `v1-feature-inventory.md` | 保留作為 V1 資產盤點參考 |

## Skill → Module 對應表

> 現有 Claude Code Skills 中哪些會併入 Workshop 模組，作為 Phase 3+ 規劃參考。

### scout — 搜尋與情報

P2 優先模組。以下 Skills 產出的研究報告、分析結果都應持久化到 scout DB：

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **smart-search** | 搜尋報告 (.md) | P2 主力。報告寫入 `scout.reports`，啟用 pgvector 語意搜尋 |
| **daily-briefing** | 三分析師情報 (HTML) | P2 併入。寫入 `scout.briefings`，保留辯論格式 |
| **company-intel** | 公司調查報告 | 報告結構相同，統一存入 `scout.reports`（tag: company-intel） |
| **competitive-intel** | 競品分析報告 | 同上（tag: competitive-intel） |
| **content-writer** | 有引用來源的文章 | 同上（tag: content-article），來源連結存入 `sources` JSONB |

**合併效益**：所有研究成果可跨 skill 語意搜尋，避免「用 smart-search 查不到 company-intel 的產出」。

### lore — 記憶與知識

P1 優先模組。以下 Skills 產出可作為記憶來源：

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **kas-memory** (MCP) | 結構化記憶區塊 | P1 主力。遷移到 `lore.blocks` + pgvector |
| **meeting-insights** | 溝通模式分析 | 分析結果作為 lore block 寫入，追蹤溝通風格演變 |

### dojo — 技能與學習

Phase 2 模組。以下 Skills 產出可作為 dojo 資料源：

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **skill-catalog** | 80+ skill 清冊 | → `dojo.skill_registry`（已安裝 skill 清單） |
| **skill-graph** | skill 聯動圖 | → `dojo.skill_relations`（技能之間的關聯） |
| **skill-optimizer** | 優化建議 | → `dojo.optimization_logs`（優化歷史追蹤） |
| **model-mentor** | 模型推薦 | → `dojo.tool_proficiency`（工具熟練度記錄） |

**願景**：追蹤「少爺和維恩一起磨練了哪些技能、各到什麼程度」，從 Galaxy 視覺化觀察成長軌跡。

### roster — 資源管理

Phase 3 模組。以下 Skills 對應 agent/resource 調度：

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **maestro** | 三 CLI 調度紀錄 | → `roster.agent_sessions`（agent 執行歷史） |
| **team-tasks** | 多 agent 協調 | → `roster.task_allocations`（任務分配記錄） |
| **scheduler** | 排程任務 | → `roster.schedules`（週期性任務管理） |

### nexus — 媒合引擎

Phase 3 模組。目前無直接對應 Skill，純新建。未來可整合：
- quest 的任務分派 → nexus 評分引擎
- dojo 的技能落差 → nexus 學習資源推薦

### media — 媒體處理（`core/services/media/`）

已規劃為 hot-path service，以下 Skills 對應媒體處理能力：

| Skill | 功能 | 對應 API |
|-------|------|---------|
| **tts** | 文字轉語音 | `/api/media/tts` |
| **stt** | 語音轉文字 | `/api/media/stt` |
| **video-core/edit/mix/audio** | 影音處理 | `/api/media/video/*` |
| **image-gen/edit** | 圖像生成與編輯 | `/api/media/image/*` |
| **ocr**, **ocr-claude-api** | 文字辨識 | `/api/media/ocr` |

**注意**：media 是 hot-path service（無狀態處理），不同於 domain modules（有 DB）。

### 不併入模組的 Skills

以下 Skills 保持獨立運作，不需要 API/UI/MCP：

| 類別 | Skills | 理由 |
|------|--------|------|
| 開發流程 | blueprint, executor, forge, spec-kit, tdd-enforcer | 開發工具，不產出持久化資料 |
| 程式碼品質 | code-review-interceptor, verification-before-completion, four-step-debug | 即時驗證，無需儲存 |
| 內容格式 | pdf, pptx, xlsx, docx, diagram-gen | 檔案生成工具，產出已存檔 |
| CLI 調度 | claude-code-headless, codex-cli-headless, gemini-cli-headless | 底層調度機制 |
| 設定管理 | create-skill, create-agent, create-command, sync-config | 維護工具 |

---

## 設計原則（貫穿 P1/P2）

1. **文件先行**：每個模組先有 README.md + API spec，再動手寫程式碼
2. **整個重構，非搬運**：不是把 V1 程式碼搬到新目錄，而是根據 V2 架構原則重新設計
3. **保留好設計**：V1 中驗證有效的設計（三分析師辯論、pgvector 語意搜尋）保留核心概念
4. **MCP 介面不中斷**：重構後端不影響 Claude Code 的日常使用（MCP 工具名稱和行為保持一致）
5. **漸進切換**：新舊系統並存過渡期，逐步切換端點，確保零停機
