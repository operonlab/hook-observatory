---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

# P7：ideagraph — 靈感孵化與知識圖譜

> [返回藍圖索引](./v2-priorities.md)

---

## 一句話定義

**AI 輔助的想法孵化系統**——忠實記錄零碎混亂的靈感，自動語意修正、推演連結，等待人類驗證後固化為知識圖譜。

---

## 為什麼需要 ideagraph

少爺的想法產出模式：零碎、高頻、跨領域、常在對話中冒出來。目前這些想法散落在：
- 對話記錄中（維恩的 session transcript）
- `docs/vision/` 的文件裡
- 腦中（最危險——會忘）

**痛點**：沒有一個系統能「先忠實收下混亂的想法，再幫忙整理和連結」。V1 Muse 太粗糙——只有 CRUD，沒有 AI 輔助的修正和推演能力。

---

## 核心工作流：想法孵化管線

```
少爺的零碎描述
    │
    ▼
┌─────────────────┐
│  1. Capture      │  忠實記錄原始輸入（不修改、不過濾）
│     原始捕捉     │  → raw_content 欄位保留原文
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. Refine       │  AI 根據語意上下文修正整理
│     語意精煉     │  → refined_content + summary + tags
│                  │  保留 raw ↔ refined 的對照關係
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. Connect      │  AI 推演可能的連結
│     推演連結     │  → 與已存在的 Spark 做語意比對
│                  │  → 產生 suggested_links（待驗證）
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. Verify       │  少爺驗證或修正方向
│     人類驗證     │  → 確認/拒絕/調整 suggested_links
│                  │  → 修正 refined_content 如有偏差
└─────────────────┘
```

**關鍵原則**：
- **永遠保留原文**：raw_content 是不可變的，refined 只是一個衍生版本
- **AI 建議，人類決定**：所有自動產生的連結都是 `suggested` 狀態，需人類 verify
- **漸進式清晰**：一個 Spark 可以從很模糊開始，隨時間和對話慢慢被精煉

---

## V1 現況分析

V1 `pulso-muse` MCP Server 有 8 個工具：

| 工具 | 功能 | V2 處置 |
|------|------|--------|
| `muse_upsert_spark` | 建立/更新 Spark | 拆分為 capture + refine |
| `muse_get_spark` | 取得 Spark 詳情 | 保留 |
| `muse_delete_spark` | 刪除 Spark | 保留 |
| `muse_upsert_link` | 建立/更新連結 | 保留，新增 verify 流程 |
| `muse_delete_link` | 刪除連結 | 保留 |
| `muse_get_graph` | 取得完整圖譜 | 保留，增加 filter/scope |
| `muse_search` | pgvector 語意搜尋 | 保留，強化 |
| `muse_list_inbox` | 跨服務事件收件匣 | 保留 |

**V1 問題**：
- 只有 CRUD，沒有 AI 輔助（capture 和 refine 是同一個動作）
- Spark 沒有 raw/refined 分層（丟失原始想法）
- Link 沒有 suggested/verified 狀態（全部直接固化）
- UI 只有基礎清單，沒有圖譜視覺化
- x, y 座標是手動的，沒有自動佈局

---

## 資料模型

### ideagraph.sparks（靈感節點）

```sql
CREATE TABLE ideagraph.sparks (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id    UUID NOT NULL REFERENCES auth.spaces(id),
    created_by  UUID NOT NULL REFERENCES auth.users(id),

    -- 原始捕捉
    raw_content     TEXT NOT NULL,           -- 少爺的原始描述（不可變）
    source_context  TEXT,                    -- 來源上下文（哪次對話、什麼情境）

    -- AI 精煉
    title           VARCHAR(200),            -- AI 或人工產生的標題
    refined_content TEXT,                    -- AI 精煉後的結構化描述
    summary         VARCHAR(500),            -- 一句話摘要
    type            VARCHAR(20) NOT NULL     -- concept / project / idea / question / resource / observation
                    DEFAULT 'idea',

    -- 分類與搜尋
    tags            TEXT[] DEFAULT '{}',     -- 自訂標籤
    embedding       vector(1536),            -- pgvector 語意向量

    -- 狀態
    status          VARCHAR(20) NOT NULL     -- draft / refined / archived
                    DEFAULT 'draft',
    refinement_count INT DEFAULT 0,          -- 被精煉過幾次

    -- 視覺化座標（Galaxy UI）
    x               FLOAT,                   -- 2D 佈局 x
    y               FLOAT,                   -- 2D 佈局 y

    -- 時間戳
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sparks_embedding ON ideagraph.sparks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_sparks_space ON ideagraph.sparks(space_id);
CREATE INDEX idx_sparks_tags ON ideagraph.sparks USING GIN(tags);
```

### ideagraph.links（連結邊）

```sql
CREATE TABLE ideagraph.links (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    source_id   UUID NOT NULL REFERENCES ideagraph.sparks(id) ON DELETE CASCADE,
    target_id   UUID NOT NULL REFERENCES ideagraph.sparks(id) ON DELETE CASCADE,

    -- 連結屬性
    type        VARCHAR(30) NOT NULL,        -- causes / enables / supports / contradicts / extends / inspires
    notes       TEXT,                        -- 連結說明
    weight      FLOAT DEFAULT 0.5           -- 0.0-1.0 強度
                CHECK (weight >= 0 AND weight <= 1),

    -- 驗證狀態（核心新增）
    status      VARCHAR(20) NOT NULL         -- suggested / verified / rejected
                DEFAULT 'suggested',
    suggested_by VARCHAR(20) DEFAULT 'ai',   -- ai / human
    verified_at TIMESTAMPTZ,
    verified_by UUID REFERENCES auth.users(id),

    -- 時間戳
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(source_id, target_id, type)
);

CREATE INDEX idx_links_source ON ideagraph.links(source_id);
CREATE INDEX idx_links_target ON ideagraph.links(target_id);
CREATE INDEX idx_links_status ON ideagraph.links(status);
```

### ideagraph.refinements（精煉歷史）

```sql
CREATE TABLE ideagraph.refinements (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    spark_id    UUID NOT NULL REFERENCES ideagraph.sparks(id) ON DELETE CASCADE,
    version     INT NOT NULL,                -- 第幾版精煉
    content     TEXT NOT NULL,               -- 該版本的 refined_content
    diff_note   TEXT,                        -- 這次修正了什麼
    refined_by  VARCHAR(20) DEFAULT 'ai',    -- ai / human
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(spark_id, version)
);
```

---

## Galaxy 風格 UI（參考 KAS Memory）

### 視覺化設計

參考 memvault 的 KAS Galaxy 星系圖，ideagraph 採用相同的互動範式：

| 元素 | Galaxy 對應 | ideagraph 實現 |
|------|------------|---------------|
| **星星** | KAS 知識點 | 每個 Spark = 一顆星 |
| **星星大小** | 知識深度 | 連結數量（越多越大） |
| **星星顏色** | K/A/S 維度 | Spark type（concept=藍、project=綠、idea=金、question=紫） |
| **星星亮度** | 成熟度 | status（draft=暗淡、refined=正常、verified links 多=明亮） |
| **星座線** | 關聯線 | Link 連結線 |
| **虛線** | — | suggested link（待驗證，脈動動畫） |
| **實線** | 確認關聯 | verified link |
| **拖曳** | 調整視角 | 拖曳 Spark 重新排列，座標寫回 DB |

### 互動功能

1. **Capture 快捷鍵**：任何時候按 `Ctrl+Shift+I` → 彈出輸入框 → 直接 capture raw idea
2. **點擊 Spark**：展開詳情面板（raw → refined 對照、連結清單、精煉歷史）
3. **Hover Link**：顯示連結類型、AI 建議理由
4. **右鍵 Spark**：Refine / Archive / Delete
5. **Verify 模式**：進入驗證模式，逐一審視 suggested links（Accept / Reject / Edit）
6. **Filter**：按 type、tags、status 過濾顯示
7. **時間軸**：拖曳時間滑桿，查看圖譜在不同時間點的演變

### 技術選型

| 層面 | 方案 |
|------|------|
| 圖譜渲染 | **D3.js force-directed graph**（2D，效能好、生態成熟） |
| 3D 備選 | Three.js（若未來需要 3D Galaxy 體驗） |
| 拖曳互動 | D3 drag behavior（原生支援） |
| 佈局演算法 | Force simulation（自動佈局）+ 手動座標覆蓋 |
| 響應式 | 圖譜 canvas 自適應容器，行動端支援 touch 拖曳 |

---

## MCP Server 設計

依 AD-2 規則（>10 tools 就拆），ideagraph 拆為 2 個 MCP Server：

### workshop-ideagraph（CRUD，~8 tools）

| Tool | 說明 |
|------|------|
| `ideagraph_capture` | 捕捉原始想法（raw_content），自動觸發 refine pipeline |
| `ideagraph_get_spark` | 取得 Spark 詳情（含 raw/refined 對照） |
| `ideagraph_update_spark` | 手動更新 Spark（修正 title、tags、type 等） |
| `ideagraph_delete_spark` | 刪除 Spark |
| `ideagraph_link` | 手動建立連結（status=verified） |
| `ideagraph_unlink` | 刪除連結 |
| `ideagraph_get_graph` | 取得圖譜（支援 filter: type, tags, status） |
| `ideagraph_search` | pgvector 語意搜尋 |

### workshop-ideagraph-ai（AI 輔助，~5 tools）

| Tool | 說明 |
|------|------|
| `ideagraph_refine` | AI 精煉指定 Spark（產生 refined_content + summary + tags） |
| `ideagraph_suggest_links` | AI 為指定 Spark 推演潛在連結 |
| `ideagraph_verify_link` | 驗證/拒絕一條 suggested link |
| `ideagraph_batch_verify` | 批量驗證（列出所有 pending suggested links） |
| `ideagraph_inbox` | 跨模組事件收件匣（finance/taskflow 等事件可轉為 Spark） |

**工作流整合**：`ideagraph_capture` 被呼叫後，自動：
1. 儲存 raw_content → sparks 表
2. 呼叫 LLM 產生 refined_content + summary + tags
3. 產生 embedding
4. 跑語意比對 → 產生 suggested_links
5. 回傳 Spark + suggested links 給使用者

---

## 事件設計

| 事件 | 觸發時機 | 用途 |
|------|---------|------|
| `ideagraph.spark.captured` | 新 Spark 被捕捉 | 通知 UI 更新圖譜 |
| `ideagraph.spark.refined` | Spark 被精煉 | 更新 UI 顯示精煉結果 |
| `ideagraph.link.suggested` | AI 建議新連結 | 通知 Verify 面板有新待審 |
| `ideagraph.link.verified` | 連結被確認 | 圖譜中虛線→實線 |
| `ideagraph.link.rejected` | 連結被拒絕 | 圖譜中移除虛線 |

**跨模組事件消費**：
- `finance.transaction.created` → 可選轉為 Spark（「這筆花費跟某個 project idea 有關」）
- `taskflow.task.completed` → 可選轉為 Spark（「完成這個任務時想到的新點子」）
- `memvault.block.created` → 可選轉為 Spark（「記憶中提到的想法值得獨立追蹤」）

---

## 增長路徑

```
階段 1: Capture + Refine + 基礎 Graph UI（D3 force-directed）
         → 替代散落的想法記錄，讓每個靈感都有地方住

階段 2: + AI Suggest Links + Verify 流程
         → 想法開始自動連結，形成知識網絡

階段 3: + Galaxy 3D 視覺化 + 時間軸回放
         → KAS Memory 等級的視覺體驗

階段 4: + 跨模組事件轉 Spark + Inbox
         → 全平台的想法匯流中心

階段 5: + 協作（Space 共享）+ 匯出（Markdown / Obsidian）
         → 從個人工具到協作平台
```

---

## 與 memvault 的關係

| 面向 | memvault | ideagraph |
|------|----------|-----------|
| **存什麼** | AI 對話記憶（自動提取） | 人類想法（主動捕捉） |
| **誰寫入** | AI（SessionEnd hook） | 人類（少爺口述/打字） |
| **結構** | Block（獨立記憶區塊） | Spark + Link（圖譜結構） |
| **搜尋** | 語意召回（自動） | 語意搜尋（主動） |
| **視覺化** | KAS Galaxy（K/A/S 維度） | Idea Galaxy（概念關聯維度） |
| **交互** | memvault block → ideagraph spark | 記憶中的想法值得獨立追蹤時轉入 |

**不是競爭，是互補**：memvault 記住「我們討論過什麼」，ideagraph 追蹤「我想做什麼」。

---

## 相關文件

| 文件 | 用途 |
|------|------|
| [v2-priorities.md](./v2-priorities.md) | 藍圖索引 |
| [domain-catalog.md](../vision/domain-catalog.md) | ideagraph 服務定義 |
| [p1-memvault.md](./p1-memvault.md) | memvault Galaxy UI 參考 |
| [composition-model.md](../vision/composition-model.md) | 組合配方中 ideagraph 的角色 |
| [shared-layer-patterns.md](../architecture/shared-layer-patterns.md) | 共享層模式（EmbeddingService §8.1、Tags §5.4、StateMachine §3.4、LLMService §8.2、ForceGraph §9.1、BulkOps §8.6、SemanticSearch §8.3） |

> 下一步：Auth 完成後接入 → 實作階段 1（Capture + Refine + 基礎 Graph UI）
