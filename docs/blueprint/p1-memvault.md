---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

> [← 返回優先藍圖總覽](./v2-priorities.md)

# P1：Memvault 模組 — KAS Memory V2

### 現況分析

KAS Memory 原為獨立專案（V1: `~/Claude/projects/kas-memory/`，已遷移至 `core/src/modules/memvault/`），V1 採用檔案系統架構：

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
目標：PostgreSQL (schema: memvault)
  ├── memvault_blocks       — 記憶區塊（取代 .md 檔案）
  ├── memvault_tags         — 標籤索引（取代 tags.idx）
  ├── memvault_embeddings   — 向量欄位（取代 embeddings.json，pgvector）
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
workbench/src/modules/memvault/       ← Memvault UI（Galaxy Widget、記憶瀏覽器）
core/src/modules/memvault/            ← Memvault 後端（API + DB + 提煉引擎）
mcp/memvault/                         ← MCP Adapter（保持現有 9 個工具介面）
```

### 遷移策略

1. **Phase A**：在 Core 中建立 memvault schema + API，匯入現有 .md 記憶
2. **Phase B**：切換 MCP Server 為 Core API 的薄適配器（而非直接讀檔案）
3. **Phase C**：升級 SessionEnd Hook 寫入 DB 而非 .md
4. **Phase D**：Workbench Widget（Galaxy + 記憶瀏覽器）

### 相關文件

| 文件 | 用途 |
|------|------|
| [v2-priorities.md](./v2-priorities.md) | 藍圖索引 |
| [shared-layer-patterns.md](../architecture/shared-layer-patterns.md) | 共享層模式（EmbeddingService §8.1、SemanticSearchService §8.3、ForceGraph §9.1） |

---

**下一步** → [P2：Intelflow 模組](./p2-intelflow.md)
