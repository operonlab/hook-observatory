---
doc_version: 2
content_hash: pending
target_lang: zh-TW
---

# V2 優先開發藍圖

> 不按 Phase 1-4 線性推進，而是以**實際需求痛點**為驅動力，優先打造最有價值的模組。

---

## 優先順序總覽

| 順位 | 模組 | 目標 | 為什麼優先 | 狀態 | 詳細文件 |
|------|------|------|-----------|------|---------|
| **P1** | memvault | Claude Code 持久化記憶 + Knowledge Graph | 每天都在用，改善記憶品質 = 改善所有工作品質 | ✅ 完成 | [p1-memvault.md](./p1-memvault.md) |
| **P2** | intelflow (Smart Search V2) | 搜尋報告結構化儲存 + UI | 搜尋是高頻操作，散落 .md 檔已造成痛點 | ✅ 完成 | [p2-intelflow.md](./p2-intelflow.md) |
| **P3** | stations 整合 | 系統工具現代化 | 散落 V1 工具需統一管理 + tmux-webui 手機體驗 | ✅ 完成 | [p3-stations.md](./p3-stations.md) |
| **P4** | auth + admin | Google/GitHub OAuth + 管理系統 | 所有模組的前提基礎，V1 缺口多 | ✅ 完成 | [p4-auth.md](./p4-auth.md) |
| **P5** | finance | 完整個人財務管理 | 記帳是每日剛需，V1 MCP-only 缺 UI/分析/預算 | ✅ 完成 | [p5-finance.md](./p5-finance.md) |
| **P6** | taskflow | 排程 + 日曆 + 任務追蹤 + 報告 | 多來源任務管理 + 自動產出日誌/週報/月報 | 🏗 骨架 | [p6-taskflow.md](./p6-taskflow.md) |
| **P7** | ideagraph | AI 輔助靈感孵化 + 知識圖譜 | 想法散落各處，需要系統化捕捉→精煉→連結→驗證 | 🏗 骨架 | [p7-ideagraph.md](./p7-ideagraph.md) |
| **P8** | notification + bridges | 通知推播 + 社群平台橋接 | 所有模組都需要通知使用者；LINE/Telegram 雙向互動是剛需 | ✅ 完成 | [p8-notification.md](./p8-notification.md) |

### 依賴關係

```
P4 (auth) ──────► P5 (finance) ──────► P6 (taskflow)
    │                                      ↑
    ├──► P1 (memvault) ──► P2 (intelflow)  │
    │                                      │
    ├──► P7 (ideagraph) ◄── memvault 可轉入 Spark
    │
    └──► P8 (notification + bridges) ◄── 消費所有模組事件
                                           │
         P3 (stations) ───────────── 獨立，可並行
```

> **注意**：P4 Auth 是所有 Domain 模組的前提，但 P1/P2/P7 因為已有 MCP 介面可先行開發後端邏輯，Auth 完成後再接入。P8 依賴 Auth（偏好儲存在 auth schema），但 PWA Push 可在 Auth 完成後立即啟用。

---

## Skill → Module 對應表

> 現有 Claude Code Skills 中哪些會併入 Workshop 模組，作為規劃參考。

### intelflow — 搜尋與情報（P2）

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **smart-search** | 搜尋報告 (.md) | 主力。報告寫入 `intelflow.reports`，啟用 Qdrant 語意搜尋 |
| **daily-briefing** | 三分析師情報 (HTML) | 併入。寫入 `intelflow.briefings`，保留辯論格式 |
| **company-intel** | 公司調查報告 | 統一存入 `intelflow.reports`（tag: company-intel） |
| **competitive-intel** | 競品分析報告 | 同上（tag: competitive-intel） |
| **content-writer** | 有引用來源的文章 | 同上（tag: content-article），來源連結存入 `sources` JSONB |

**合併效益**：所有研究成果可跨 skill 語意搜尋，避免「用 smart-search 查不到 company-intel 的產出」。

### memvault — 記憶與知識（P1）

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **memvault** (MCP) | 結構化記憶區塊 | 已遷移到 `memvault.blocks` + Qdrant |
| **meeting-insights** | 溝通模式分析 | 分析結果作為 memvault block 寫入，追蹤溝通風格演變 |

### finance — 會計與財務（P5）

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **workshop-finance** (MCP) | 交易 CRUD + 訂閱 + 洞察 | V1 10 tools → V2 拆 2 MCP（CRUD + Analytics） |

### taskflow — 任務與排程（P6）

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **workshop-quest** (MCP) | 任務 CRUD + 技能樹 | V1 10 tools → V2 拆 2 MCP（CRUD + Reports） |
| **scheduler** | cron 排程 | 週期性任務整合到 taskflow.tasks.recurrence |

### ideagraph — 靈感孵化與知識圖譜（P7）

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **workshop-muse** (MCP) | Spark CRUD + 連結 + 語意搜尋 | V1 8 tools → V2 拆 2 MCP（CRUD + AI 輔助） |

**合併效益**：從純 CRUD 升級為 Capture→Refine→Connect→Verify 管線，AI 自動精煉想法 + 推演連結，人類驗證後固化為知識圖譜。

### skillpath — 技能與學習（未來）

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **skill-catalog** | 80+ skill 清冊 | → `skillpath.skill_registry` |
| **skill-graph** | skill 聯動圖 | → `skillpath.skill_relations` |
| **skill-optimizer** | 優化建議 | → `skillpath.optimization_logs` |
| **model-mentor** | 模型推薦 | → `skillpath.tool_proficiency` |

**願景**：追蹤「少爺和維恩一起磨練了哪些技能、各到什麼程度」，從 Galaxy 視覺化觀察成長軌跡。

### workpool — 資源管理（未來）

| Skill | 目前產出 | 整合方式 |
|-------|---------|---------|
| **maestro** | 三 CLI 調度紀錄 | → `workpool.agent_sessions` |
| **team-tasks** | 多 agent 協調 | → `workpool.task_allocations` |

### matchcore — 媒合引擎（未來）

目前無直接對應 Skill，純新建。未來可整合：
- taskflow 的任務分派 → matchcore 評分引擎
- skillpath 的技能落差 → matchcore 學習資源推薦

### media — 媒體處理（`core/services/media/`）

已規劃為 hot-path service：

| Skill | 功能 | 對應 API |
|-------|------|---------|
| **tts** | 文字轉語音 | `/api/media/tts` |
| **stt** | 語音轉文字 | `/api/media/stt` |
| **video-core/edit/mix/audio** | 影音處理 | `/api/media/video/*` |
| **image-gen/edit** | 圖像生成與編輯 | `/api/media/image/*` |
| **ocr**, **ocr-claude-api** | 文字辨識 | `/api/media/ocr` |

**注意**：media 是 hot-path service（無狀態處理），不同於 domain modules（有 DB）。

### 不併入模組的 Skills

| 類別 | Skills | 理由 |
|------|--------|------|
| 開發流程 | blueprint, executor, forge, spec-kit, tdd-enforcer | 開發工具，不產出持久化資料 |
| 程式碼品質 | code-review-interceptor, verification-before-completion, four-step-debug | 即時驗證，無需儲存 |
| 內容格式 | pdf, pptx, xlsx, docx, diagram-gen | 檔案生成工具，產出已存檔 |
| CLI 調度 | claude-code-headless, codex-cli-headless, gemini-cli-headless | 底層調度機制 |
| 設定管理 | create-skill, create-agent, create-command, sync-config | 維護工具 |

---

## MCP Server 盤點

| MCP Server | 模組 | Tools 數 | 狀態 |
|------------|------|---------|------|
| `memvault` | memvault | 16 | V2 Core API adapter（含 KG 9 tools） |
| `workshop-intelflow` | intelflow | 待定 | V2 新建 |
| `workshop-auth` | auth | 待定 | V2 新建 |
| `workshop-finance` | finance | ~10 | V1 運作中 → V2 拆分 |
| `workshop-finance-analytics` | finance | ~8 | V2 新建（分析 + 預算） |
| `workshop-taskflow` | taskflow | ~10 | V1 運作中 → V2 拆分 |
| `workshop-taskflow-reports` | taskflow | ~5 | V2 新建（報告 + 分析） |
| `workshop-admin` | admin | 待定 | V2 新建 |
| `workshop-ideagraph` | ideagraph | ~8 | V1 workshop-muse → V2 重構（CRUD） |
| `workshop-ideagraph-ai` | ideagraph | ~5 | V2 新建（AI 輔助：精煉 + 推演 + 驗證） |

---

## 設計原則（貫穿所有優先層級）

1. **文件先行**：每個模組先有 README.md + API spec，再動手寫程式碼
2. **整個重構，非搬運**：不是把 V1 程式碼搬到新目錄，而是根據 V2 架構原則重新設計
3. **保留好設計**：V1 中驗證有效的設計（authlib OAuth、MCP 10 tools、Qdrant）保留核心概念
4. **MCP 介面不中斷**：重構後端不影響 Claude Code 的日常使用（MCP 工具名稱和行為保持一致）
5. **漸進切換**：新舊系統並存過渡期，逐步切換端點，確保零停機
6. **超過 10 tools 就拆 MCP**：遵循 AD-2 切分規則，保持單一 MCP Server 的 context 負擔合理
7. **照片存 RustFS、關聯存 DB**：二進位檔案不進 PostgreSQL，靠 storage_key 關聯

---

## 相關文件

| 文件 | 用途 |
|------|------|
| [v1-feature-inventory.md](./v1-feature-inventory.md) | V1 功能清單，供重構參考 |
| [domain-catalog.md](../vision/domain-catalog.md) | 服務目錄（所有模組總覽） |
| [architecture-decisions.md](../architecture/architecture-decisions.md) | ADR 決策紀錄 |
| [auth.md](../architecture/auth.md) | Auth 架構設計文件 |
| [notification.md](../architecture/notification.md) | 通知與橋接架構設計 |
| [shared-layer-patterns.md](../architecture/shared-layer-patterns.md) | 共享層 OOP 模式目錄（跨模組共用設計） |
