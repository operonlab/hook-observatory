---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

> [← 返回優先藍圖總覽](./v2-priorities.md)

# P2：Intelflow 模組 — Smart Search V2

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

將散落的搜尋/情報能力整合為 Workshop Core 的 `intelflow` 模組。

#### 1. 資料層整合：獨立 Service → Core Module

```
現況：
  ~/Claude/services/research_report/  (獨立 FastAPI, port 8830)
  ~/Claude/skills/smart-search/*.md   (52 個 fallback 檔案)
  ~/Claude/skills/daily-briefing/     (靜態 HTML)
  ↓
目標：
  core/src/modules/intelflow/             (Core Module)
  ├── schema: intelflow                   (PostgreSQL)
  │   ├── reports          — 搜尋/研究報告
  │   ├── report_embeddings — pgvector 向量（768d / 1536d）
  │   ├── topics           — 主題分類
  │   ├── topic_relations  — 主題關聯圖
  │   ├── briefings        — 每日情報彙整
  │   └── search_sessions  — 搜尋紀錄
  │
  └── API: /api/intelflow/
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
    ├── Pre-Search: POST /api/intelflow/search/check  ← 查重（pgvector 相似度）
    │
    ├── 執行搜尋（DeepWiki / Context7 / Perplexity / 9 平台社群）
    │
    └── Post-Search: POST /api/intelflow/reports      ← 寫入報告 + 自動 embedding
                                                         不再 fallback 到 .md
```

#### 3. UI 升級：Research Hub → Workbench Module

保留 V1 的好設計，以 Workbench 模組形式重建：

| 頁面 | 功能 |
|------|------|
| `/intelflow` | 情報總覽（最新報告、趨勢圖、主題圖譜） |
| `/intelflow/reports` | 報告列表（全文搜尋 + 語意搜尋 + tag 過濾） |
| `/intelflow/reports/:id` | 報告詳情（Markdown 渲染 + 來源連結） |
| `/intelflow/topics` | 主題圖譜（Force-directed graph 視覺化） |
| `/intelflow/briefings` | 每日情報（三分析師辯論格式） |
| Widget | Workbench 首頁摘要 Widget（最新 5 篇 + 趨勢） |

#### 4. Daily Briefing 整合

V1 的三 AI 辯論模式整合到 intelflow 模組：

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
    └── 寫入 DB：POST /api/intelflow/briefings
        （含 embedding，可語意搜尋歷史情報）
```

### 技術架構

```
workbench/src/modules/intelflow/      ← Intelflow UI（報告瀏覽、主題圖譜、情報總覽）
core/src/modules/intelflow/           ← Intelflow 後端（API + DB + pgvector + 提煉）
mcp/intelflow/                        ← MCP Adapter（供 Claude Code 直接操作）
```

### 遷移策略

1. **Phase A**：在 Core 中建立 intelflow schema，匯入 research_report DB 資料 + 52 個 .md 回填
2. **Phase B**：切換 smart-search Skill 端點從 `localhost:8830` → Core API
3. **Phase C**：Workbench 模組（報告瀏覽器 + 主題圖譜）
4. **Phase D**：Daily Briefing 整合（三分析師管線）

### 相關文件

| 文件 | 用途 |
|------|------|
| [v2-priorities.md](./v2-priorities.md) | 藍圖索引 |
| [shared-layer-patterns.md](../architecture/shared-layer-patterns.md) | 共享層模式（EmbeddingService §8.1、SemanticSearchService §8.3、ForceGraph §9.1、Tags §5.4） |

---

**下一步** → [P3：Station 整合](./p3-stations.md)
