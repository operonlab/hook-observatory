---
doc_version: 1
content_hash: 13aa3c09
source_version: 1
target_lang: zh-TW
translated_at: 2026-02-23
---

# Workshop 宣言

> Workshop 是一個統一的工作站，從個人工具出發，並成長為消費級的平台生態系統。

## 什麼是 Workshop？

Workshop 不僅僅是一個專案資料夾——它是 Jones 的**數位工作站**，涵蓋了從磁碟分析到企業級 ERP 的所有內容。
從 LLM 使用追蹤和硬體監控等小型工具，到全規模的會計、任務調度、人才媒合和 POS 系統——
一切都存在於同一個架構下，共享身份驗證、事件串流和資料交換。

### 核心哲學

1. **個人 → 平台**：每個功能首先為個人（+ 家人/朋友）服務，驗證後再作為平台服務開放
2. **靈活但有界**：為擴張留出空間，但防止不受控制的蔓延——透過領域邊界管理複雜性
3. **文件先行**：思考清楚，書寫清楚，然後再動手實作（教訓：T1/T2 過早的衝刺導致了全面回滾）
4. **真實驗證**：無需 Mock 測試或冒煙測試——使用真實任務和真實結果進行驗證
5. **MCP 作為一等介面**：Claude Code Skills + MCP Servers 是頭等公民；UI 次之

---

## 三層分類法：Core / Stations / Bridges

所有 Workshop 功能根據**資料駐留 (data residency)** 分為三個層級：

### Core 模組

> 資料存放在 Workshop 自有的資料庫 (PostgreSQL) 中，由 FastAPI Core Monolith 管理。

這些是 Workshop 的骨幹——具有持久化資料、業務邏輯和多使用者共享的需求。

| 模組 | 描述 |
|--------|-------------|
| **auth** | 身份驗證 + 基於空間的權限 (所有功能的先決條件) |
| **finance** | 會計、訂閱管理、財務洞察 |
| **taskflow** | 待辦事項 → 量化任務 → 調度 → 訂單 (漸進式複雜度) |
| **ideagraph** | 靈感筆記、知識圖譜、收件匣 |
| **intelflow** | 每日情報、自動摘要、RSS/社交監測 |
| **memvault** | KAS Memory v2 (LLM 記憶持久化) |
| **skillpath** | 技能樹、學習路徑、能力驗證 |
| **workpool** | 資源管理 (人力/機器/服務/AI agent 的統一抽象) |
| **matchcore** | 媒合引擎 (人才×工作，能力×任務) |
| **admin** | 平台管理、系統監控、配置 |

### Stations (站點)

> 不一定需要資料庫的獨立在地工具。可能是 CLI、桌面工具或分析腳本。

- **system-monitor** — 磁碟分析 + 硬體資源壓力監控
- **llm-usage** — LLM Token/Cost 統一追蹤（含 LiteLLM Proxy）
- **envkit** — 環境快照 + 一鍵移植工具
- **tmux-webui** — tmux 瀏覽器控制 + 系統指標
- **session-redactor** — 轉錄檔敏感資料清理（SessionEnd hook）
- **sandbox-executor** — 批次程式碼執行引擎（MCP Server）

Stations 可以獨立運行而無需 FastAPI Core，但可以選擇將資料推送到 Core。

### Vendor (第三方)

> 不改造成 V2 架構的第三方社群工具。直接使用，upstream 更新靠 `git pull`。

- **observability** — Claude Code hooks 即時多 Agent 監控儀表板（[@disler](https://github.com/disler)）

### Bridges (橋樑)

> 連接外部生態系統的適配器。它們不擁有資料——僅處理雙向同步。

- **Social Hooks**: LINE, Telegram, Discord, Facebook
- **通知平台**: Firebase Cloud Messaging / PWA Push
- **外部 API**: OpenAI, Google Calendar, GitHub 等
- **OCR / AI 服務**: 外部 AI 模型的包裝器

Bridge 的輸出通常流向 Core 模組 (例如：LINE 訊息 → taskflow 建立一個待辦事項)。

---

## 設計原則

### 1. 領域邊界至上 (Domain Boundary is King)

每個 Core 模組都有自己的：
- 資料庫模式 (每個模組一個 schema，而非每個模組一個 DB)
- 事件定義 (發布/訂閱)
- MCP Server (薄適配器)
- API 路由 (`/api/{module}/...`)

跨模組通訊僅透過：事件匯流排 (Event Bus) 或公開 API。禁止模組之間的直接導入 (Direct imports)。

### 2. 從第一天起就支援多使用者

這不是事後才補上的。基於空間 (Space-based) 的共享模型從第一天起就設計在資料模型中：
- `space_id` 出現在所有資料表中
- Space = 共享範圍 (個人 / 家庭 / 朋友 / 組織)
- 每個 Space 可以啟用/禁用不同的模組

### 3. 漸進式複雜度

功能從簡單開始，並根據需求增加複雜度：
- taskflow：勾選框 → 故事點 (story points) → 技能需求 → 任務池 → 商業訂單
- finance：個人記帳 → 家庭共享帳本 → 庫存 → POS
- matchcore：手動配對 → 條件過濾 → AI 推薦

### 4. MCP 優先，UI 次之

每個 Core 模組首先獲得一個 MCP Server (以便 Claude Code 可以直接操作它)，
然後才是模組頁面 UI 和 Dashboard Widget。
MCP Servers 是 Core API 的薄適配器——它們永遠不會直接觸碰資料庫。

### 5. 三層前端架構

Workshop 的前端由三層共存組成：

```
┌─────────────────────────────────────────────┐
│  Layer 3: LLM Chat 浮層                      │ ← 跨全域，隨時可對話
│  （類似 Google Gemini 嵌入 Chrome）            │
├─────────────────────────────────────────────┤
│  Layer 2: Dashboard Widget 視圖              │ ← 各模組 Widget 拖放組合
├─────────────────────────────────────────────┤
│  Layer 1: 模組 SPA 頁面                      │ ← /finance/*, /taskflow/* ...
│  每個模組有完整的路由與 UI                     │
└─────────────────────────────────────────────┘
```

- **Layer 1 — 模組頁面**：每個模組擁有完整的路由式 SPA 頁面（記帳、任務管理等）
- **Layer 2 — Dashboard Widgets**：額外的儀表板視圖，從各模組抽取 Widget 自由拖放組合
- **Layer 3 — LLM Chat 浮層**：橫跨所有頁面的對話介面，不離開當前頁面即可與 LLM 互動

Widget Dashboard 是模組頁面的**補充**，而非取代。LLM Chat 則是全域浮層，無論在哪個頁面都能呼叫。

---

## Workshop 不是什麼

- **不是微服務**：它是一個模組化單體架構 (Modular Monolith)——單一佈署單元
- **不是單一使用者工具**：從第一天起就是多使用者支援
- **不是企業級 SaaS**：它是個人工作站，但架構允許成長為平台
- **不是代碼優先**：文件先行，驗證後再實作
