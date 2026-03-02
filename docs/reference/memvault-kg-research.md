---
archived_from: ~/Claude/projects/kas-memory/docs/three-layer-redesign.md
archived_at: 2026-02-25
status: reference (archived)
note: V1 原始研究文件。KG 實作已遷移至 V2 memvault 模組。
translated_at: 2026-02-26
---

# Memvault 三層記憶架構重設計

> 建立日期：2026-02-25
> 狀態：概念設計（腦力風暴輸出）
> 來源：Smart-search 分析 GraphRAG/LeanRAG/HiRAG + Mem0/Zep/Graphiti
> 報告 ID：rpt-b5ca1e9ca836

---

## 1. 問題陳述

現有的記憶提取只產出扁平的文字區塊，標記為 `technical`、`achievement`、`user-correction` 等。
這些全是**情節記憶**——它們無法自然地區分為 KAS 三個維度（Knowledge、Attitude、Skill）。

### 現有類型分佈（141 個已提取 session）
| 類型 | 數量 | 問題 |
|------|------|------|
| technical | 64 | 全標為「knowledge」但實際只是事件紀錄 |
| achievement | 33 | 應回饋到 Skill 熟練度 |
| decision | 30 | 應回饋到 Knowledge graph |
| user-correction | 14 | 應回饋到 Attitude 校準 |
| failed-approach | 5 | 價值高但佔比不足 |
| communication | 1 | 應回饋到 Attitude |

**核心洞察**：目前的提取是「記憶」（Memory），不是 K/A/S。每一層需要根本不同的**資料來源**、**資料結構**和**成長機制**。

---

## 2. 研究基礎

### 2.1 研究的關鍵架構

| 系統 | 核心創新 | 與 KAS 的相關性 |
|------|---------|---------------|
| **GraphRAG** (Microsoft 2024) | LLM 實體抽取 → KG → Leiden 聚類 → 社群摘要 | Knowledge 層結構 |
| **LeanRAG** (2025) | GMM 語意聚類 → 跨聚類關係 → 自下而上 LCA | Knowledge L1 聚合 |
| **HiRAG** (EMNLP 2025) | 多層遞歸 GMM → 摘要實體作為語意捷徑 | Knowledge L2 Wisdom |
| **Mem0** (2025) | 混合向量+圖譜；ADD/UPDATE/DELETE/NOOP 操作 | Attitude 演化模式 |
| **Zep/Graphiti** (2025) | 雙時態 KG（事件時線 + 交易時線）；實體解析 | Skill 成長曲線 |
| **arXiv:2602.05665** | 6 種認知記憶類型：語意、情節、程序、聯想、工作、情感 | 理論映射 |

### 2.2 認知記憶類型映射

```
程序記憶  → Skill（如何做事）
情感記憶  → Attitude（偏好、修正、人設校準）
語意記憶  → Knowledge（事實、關係、驗證過的理解）
情節記憶  → 現有的「記憶」層（事件紀錄——原料）
```

---

## 3. 三層設計

### 3.1 Skill = 程序記憶即熟練度圖譜

**資料來源**：Skill 調用紀錄（非 session 提取）
- 追蹤每個 `~/.claude/skills/*/` 的調用
- 記錄成功/失敗/部分成功的結果
- 觀察 skill 間的依賴關係

**資料結構**：加權 skill 聚類圖譜
```
節點：Skill（如 "smart-search"、"blueprint"、"forge"）
邊：  共同調用 / 依賴（依頻率加權）
權重：熟練度分數（調用次數 × 成功率 × 時間衰減）
```

**成長機制**（Zep 啟發的雙時態）：
```
時線 1 — 事件：每次調用帶時間戳記錄
時線 2 — 狀態：熟練度分數更新，永不刪除
         （舊分數保留為歷史，新分數附加）
```

**聚合**（LeanRAG 啟發）：
- 按領域聚類 skill（GMM on 調用上下文 embeddings）
- 自動生成聚類摘要：「少爺在 {domain} 領域常用 {skills}，熟練度 {level}」
- 實現「自我認知」：agent 知道自己擅長什麼、什麼還沒測試過

**範例輸出**：
```
Cluster: "Web Development"
  - frontend-design: ████████░░ 80% (47 次調用, 91% 成功)
  - playground: ██████░░░░ 60% (23 次調用, 87% 成功)
  - ui-audit: ██░░░░░░░░ 20% (3 次調用, 67% 成功)
  本月成長: +15%
  洞察: "UI audit 常在 frontend-design 之後使用 — 考慮自動建議"
```

### 3.2 Attitude = 情感記憶即人設校準

**資料來源**：使用者修正 + 人設調用結果
- `user-correction` 類型記憶 → 校準事件
- `communication` 類型記憶 → 互動風格資料
- （未來）多人設調用結果

**資料結構**：偏好演化日誌（Mem0 模式）
```
每條記錄：
  { fact: "少爺不喜歡 smoke test",
    operation: ADD | UPDATE | NOOP,
    timestamp: "2026-02-15",
    confidence: 0.95,
    source_sessions: ["abc123", "def456"] }
```

**成長機制**（Mem0 啟發的 ADD/UPDATE/NOOP）：
```
新修正到達時：
  1. 與現有偏好比較
  2. 若與現有矛盾 → UPDATE（提升新的信心值，衰減舊的）
  3. 若強化現有 → NOOP（提升信心值）
  4. 若全新 → ADD
  5. 永不 DELETE（舊偏好加上 end_date 歸檔，不刪除）
```

**要追蹤的關鍵態度**：
| 類別 | 範例 |
|------|------|
| 測試哲學 | 不要 mock test，偏好真實執行 |
| 溝通風格 | 稱呼少爺，阿福+賈維斯+奇異博士人設 |
| 決策自主性 | 執行藍圖不需核准，破壞性操作需確認 |
| 技術偏好 | 腳本用 Python 不用 JS，服務用 single binary |
| 品質標準 | 回報前自我檢查，完成前驗證 |

**為何不從 session 提取**：態度是**預設設計**（人設）+ **修正累積**（校準）。
在 session 中很稀疏（141 個中只有 14 個）。專用的修正捕獲管線比從 session 中挖掘更好。

### 3.3 Knowledge = 三層 KG 階層

**資料來源**：Session 提取（現有管線），但重構輸出

**資料結構**：三層階層

#### Layer 0 — 原始三元組（骨架）
```
從 session 中提取 (Subject, Predicate, Object)
範例：
  (pgvector, requires, HNSW index with m=16)
  (Gemini Flash, produces, markdown code fences in output)
  (nohup, loses, shell PATH environment)
```
- 枯燥但必要的基礎
- 由 LLM（Gemini Flash）以結構化 prompt 提取
- 以簡單三元組儲存，帶 source_session + timestamp

#### Layer 1 — 決策聚類（洞察）
```
對 Layer 0 三元組進行 GMM 語意聚類
→ 自動生成聚類摘要，格式為「情境→判斷→結果」

聚類範例: "Shell Script 可靠性"
  三元組: [(nohup, loses, PATH), (set -e, causes, immediate exit),
            (exec 2>, consumes, stdin), (jq, enables, safe JSON construction)]
  摘要: "Shell scripts in background (nohup/cron) 需要顯式設定 PATH，
        避免 set -e 搭配 complex pipelines，用 jq 而非 echo 構建 JSON"
  判定: VERIFIED（已在 batch-extract.sh 修復中成功應用）
```

- 知識在此變得**可操作**
- LeanRAG 風格的自下而上聚合
- 每個聚類有人類可讀的判定/經驗法則

#### Layer 2 — Wisdom 節點（跨聚類經驗法則）
```
跨多個 Layer 1 聚類的模式
→ 「Google 查不到的經驗法則」

範例：
  關聯聚類: [Shell Script 可靠性, MCP Tool 委派, Hook 安全性]
  Wisdom: "任何在 hook/background/nohup 環境下運行的腳本，
           都需要假設最小環境：顯式 PATH、顯式 tool verification、
           graceful degradation（不能用 set -e）"
  信心: HIGH（跨 3 個獨立事件驗證）
```

- 透過分析聚類間關係生成（HiRAG 啟發）
- 最稀有但最有價值——這是真正的專業經驗
- 需要多個 Layer 1 聚類匯聚

---

## 4. 資料流架構

```
                        Session JSONL
                             │
                    ┌────────┴────────┐
                    │   extract.sh    │ (Gemini Flash)
                    │  （重構輸出）     │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────┴─────┐ ┌─────┴─────┐ ┌─────┴─────┐
        │  三元組     │ │  修正      │ │  調用紀錄   │
        │  (S,P,O)   │ │(user-corr)│ │(skill log) │
        └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
              │              │              │
              ▼              ▼              ▼
        ┌───────────┐ ┌───────────┐ ┌───────────┐
        │ Knowledge  │ │ Attitude  │ │   Skill   │
        │  Layer 0   │ │   Store   │ │   Graph   │
        │ 原始三元組  │ │ Mem0 操作  │ │  熟練度    │
        └─────┬─────┘ └───────────┘ └───────────┘
              │ （週期批次）
              ▼
        ┌───────────┐
        │ Knowledge  │
        │  Layer 1   │
        │  聚類       │
        └─────┬─────┘
              │ （週期批次）
              ▼
        ┌───────────┐
        │ Knowledge  │
        │  Layer 2   │
        │   Wisdom   │
        └───────────┘
```

---

## 5. 實作考量

### 5.1 Embedding 基礎設施
- Mac Mini 上的 Ollama `nomic-embed-text`（已可用）
- 用途：三元組相似度、GMM 聚類輸入、skill 上下文 embedding
- 維度：768（nomic-embed-text）

### 5.2 與現有管線的差異

| 元件 | 現有 | 重設計 |
|------|------|--------|
| extract.sh 輸出 | 扁平 markdown 區塊 | 結構化 JSON：triples[] + corrections[] + metadata |
| V2 API schema | 單一 `MemoryBlock` | `Triple`、`Correction`、`SkillInvocation` 表 |
| recall.sh | 對 markdown 做文字搜尋 | KG 走訪 + 聚類查詢 |
| 索引 | tags.idx 扁平檔 | Embedding 向量 + KG 鄰接表 |
| 聚合 | 無 | 週期性 GMM 聚類 + 摘要生成 |

### 5.3 Mac Mini 上的可行性
- GMM 聚類：scikit-learn，<10K 三元組幾秒內完成
- Embedding：Ollama 本地，每個文字區塊約 100ms
- KG 儲存：PostgreSQL + pgvector（V2 memvault 已就位）
- 核心管線無雲端依賴

---

## 6. 開放問題

1. **三元組提取 prompt**：如何讓 Gemini Flash 穩定輸出乾淨的 (S,P,O) 三元組？
   需要 prompt 工程 + 輸出驗證。
2. **聚類頻率**：多久重新聚類一次？每 N 個新三元組後？每日批次？
3. **Layer 2 生成**：人工策展還是全自動？初期大概半自動加人工審核。
4. **與 MemVault 整合**：KG 應存在 PostgreSQL 中（已確認 V2 方案）。
5. **Recall 策略**：開新 session 時查哪一層？
   Layer 2（wisdom）優先 → Layer 1（聚類）→ Layer 0（三元組）降級？

---

## 7. Sandbox 模擬結果 (2026-02-25)

### 7.1 Knowledge 層 — 三元組提取 (Layer 0)

**輸入**：5 個真實記憶區塊，17 個要點
**輸出**：22 個三元組（1.3 倍展開比）

範例三元組：
```
(memvault,              uses,           PostgreSQL independent schema isolation)
(pgvector HNSW index,   configured_with, m=16, ef_construction=64)
(MCP adapter,           reason_for_python, unify Core API tech stack)
(hook scripts,          should_use,     jq for safe JSON construction)
(find $HOME,            causes,         17.16s scan time)
(sync-config,           should_NOT,     force copy-paste between CLIs)
```

**觀察**：
- technical 類型產出最多三元組（結構化事實密度高）
- user-correction 帶有 should/should_NOT — 天然適合 Attitude 分流
- Predicate 需要有限詞彙表：uses, causes, should, configured_with, pattern_is, ...

### 7.2 Knowledge 層 — 決策聚類 (Layer 1)

**輸入**：22 個三元組 → **輸出**：5 個聚類（4.4:1 壓縮）

| 聚類 | 三元組數 | 判定 | 模式 |
|------|---------|------|------|
| Hook & Script 可靠性 | 4 | VERIFIED | hook/background 環境 → 假設最小環境 → 穩定執行 |
| V2 架構決策 | 5 | ACTIVE | 多服務選型 → 技術棧統一 → 維護成本降低 |
| 快取 & 效能 | 4 | VERIFIED | 快取設計 → explicit trigger 取代 TTL → 回應改善 |
| 跨 CLI 配置 | 4 | VERIFIED | 多 CLI 同步 → 語意映射 → 正確同步 |
| 搜尋 & 索引設計 | 4 | ACTIVE | 混合搜尋 → 向量+關鍵字雙路 → 中英精準 |

**「情境→判斷→結果」模式是 recall 時最有用的格式。**

### 7.3 Knowledge 層 — Wisdom 節點 (Layer 2)

**跨聚類候選**（C1 + C3）：
> "背景/非交互式環境（hook, nohup, cron, background_scan）共同的生存法則：
> 假設最小環境、顯式依賴、graceful degradation、explicit trigger 取代 implicit timer"
>
> 信心：HIGH — 跨 3+ 個獨立事件驗證

**這是 Google 查不到的洞察。** 這是真正的個人經驗智慧。

### 7.4 Skill 層 — 熟練度圖譜

Top skills（模擬自 22 次調用，11 個獨立 skill）：
```
smart-search:     ███████░░░ 75%  (6 次調用, 83% 成功)
team-tasks:       ████░░░░░░ 45%  (3 次調用, 100% 成功)
blueprint:        ███░░░░░░░ 30%  (2 次調用, 100% 成功)
git-worktrees:    ███░░░░░░░ 30%  (2 次調用, 100% 成功)
frontend-design:  ███░░░░░░░ 30%  (2 次調用, 100% 成功)
forge:            █░░░░░░░░░ 15%  (2 次調用, 50% 成功)
```

共同調用聚類：
- **全端開發**：blueprint → git-worktrees → team-tasks → forge → frontend-design
- **研究分析**：smart-search → diagram-gen → spec-kit
- **配置維護**：sync-config, maestro（獨立）

### 7.5 Attitude 層 — 校準歷史

7 個事實跨 6 個類別：testing_philosophy, tool_behavior, autonomy_level,
safety, design_preference, system_feedback

**UPDATE 操作範例**（Mem0 模式）：
```
修改前: "技術選型偏好 TypeScript" (confidence=0.60, 2026-02-10)
事件:   V2 架構決策 — 明確選擇 Python
修改後: "技術選型偏好 Python/FastAPI 統一後端（曾考慮 TS）" (confidence=0.85)
        舊事實: SUPERSEDED（歸檔，未刪除）
```

### 7.6 正式批次結果 (2026-02-25)

**批次三元組提取**（2079 個 session 中 847 個可處理）：
| 指標 | 值 |
|------|------|
| 已處理 session | 847 |
| 成功提取三元組 | 99 sessions → **1107 個三元組** |
| 跳過（agent/過短）| 704 sessions |
| 失敗（驗證不過）| 44 sessions |
| 提取修正 | 147 |
| 每 session 平均三元組 | 11.2 |

**Predicate 分佈**（前 5）：
| Predicate | 數量 | 佔比 |
|-----------|------|------|
| implemented_as | 139 | 12.6% |
| should | 127 | 11.5% |
| requires | 99 | 8.9% |
| enables | 88 | 8.0% |
| causes | 82 | 7.4% |

**GMM 聚類**（BIC 最優 k=3）：
| 聚類 | 大小 | 聚焦 |
|------|------|------|
| C0: 前端 & 報告生成 | 474 | causes, should, implemented_as |
| C2: 搜尋 & 配置 | 381 | should, implemented_as, requires |
| C1: Skills & 編排 | 277 | implemented_as, pattern_is, enables |

**觀察**：
- k=3 太粗略——可能需要更多三元組或更精細的 embeddings 才能得到有意義的聚類
- 11.2 三元組/session 與 sandbox 估計一致（1.3 倍展開）
- 44 個失敗大多因 Gemini 發明了詞彙表外的 predicates（已透過 alias 映射修復）
- 147 個修正是豐富的 Attitude 層資料集

### 7.7 原始預估 vs 實際

| 層級 | 預估 | 實際 |
|------|------|------|
| Knowledge L0（三元組）| ~600-800 | **1461**（超出，重試後） |
| Knowledge L1（聚類）| ~40-60 | **13**（PCA 50d + diag GMM, BIC 最優） |
| Knowledge L2（Wisdom）| ~5-10 | **9**（7 HIGH, 1 MEDIUM 信心） |
| Attitude（事實/修正）| ~20-30 | **207**（超出） |
| Skill（調用紀錄）| ~200+ | Hook 已啟用，持續收集中 |

---

## 8. 模擬的關鍵洞察

1. **三元組提取是機械性的** — 1.3 倍展開可控，prompt 工程是主要挑戰（非量級）
2. **聚類是價值浮現之處** — 4.4:1 壓縮幾乎零資訊損失，
   「情境→判斷→結果」格式可立即操作
3. **Layer 2 稀有但珍貴** — 141 個 session 可能只產出 5-10 個 wisdom 節點，
   但每個都是 Google 搜不到的真正專業洞察
4. **Skill 熟練度容易收集** — 只需一個記錄 skill 名稱 + 結果的 hook
5. **Attitude 事實稀疏但穩定** — 總共約 20-30 個，透過 UPDATE 緩慢演化
6. **三層有不同的節奏**：
   - Skill：每個 session 更新（高頻，機械性）
   - Attitude：僅在修正時更新（低頻，高影響）
   - Knowledge：L0 每 session，L1 每週批次，L2 每月審核

---

## 9. 後續步驟

- [x] 設計 Gemini Flash 三元組提取 prompt → `scripts/prompts/triple-extraction.txt`
- [x] 定義 predicate 詞彙表（7 類 20 個 predicates）
- [x] 建立三元組驗證腳本 → `scripts/validate-triples.py`（含 40+ alias 正規化）
- [x] 原型 Skill 調用追蹤 hook → `scripts/skill-tracker.sh`（已註冊到 settings.json）
- [x] 在真實 session 上測試三元組提取 (49c8dbe1) → 12 個三元組，2 個修正，全部通過驗證
- [x] 將三元組提取整合到 extract.sh → step 10，背景啟動 `extract-triples.sh`
- [x] 批次重提取現有 sessions → 847 sessions：**99 OK / 704 SKIP / 44 FAIL**
- [x] 用 Ollama nomic-embed-text 測試 GMM 聚類 → **1132 三元組 → 3 聚類（BIC 最優）**
- [x] 調優聚類：PCA 50d + diag covariance → **k=13**（從 k=3）
- [x] 重提取 44 個失敗 sessions → **30 個恢復**，14 個永久失敗（Gemini 創意發揮）
- [x] 生成 Layer 2 Wisdom 節點 → **9 個節點**（7 HIGH, 1 MEDIUM）from 11 個跨聚類橋樑
- [x] 設計 V2 API schema → `docs/v2-schema.md`（5 表 + 8 新 MCP tools + cascade recall）
- [x] 初始化 SQLite KG 資料庫 → `kas-kg.db`（1461 三元組, 13 聚類, 9 wisdom, 207 態度）
- [x] 實作 cascade recall（Layer 2 → 1 → 0 → blocks 降級）→ V2 `CascadeRecallService`
- [x] 實作 Attitude 演化管線（ADD/UPDATE/NOOP + 語意比對）→ V2 `attitude_pipeline.py`
- [x] 連接 `extract-triples.sh` → 自動寫入 Core API → V2 POST `/kg/triples/batch`
- [x] 新增 MCP tools → V2 `memvault_kg_search`, `memvault_attitude_current`, `memvault_skill_proficiency` 等 7 個
