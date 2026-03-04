---
doc_version: 5
content_hash: pending
source_version: 5
target_lang: zh-TW
translated_at: 2026-02-23
---

# Workshop 願景文件

> Workshop 平台願景 — 定義我們建造什麼、為什麼，以及服務如何組合。

## 文件列表

| 檔案 | 內容 |
|------|----------|
| [workshop-manifesto.md](./workshop-manifesto.md) | Workshop 是什麼、LEGO 組合哲學、服務分類、設計原則 |
| [domain-catalog.md](./domain-catalog.md) | 統一服務目錄 + 組合配方 + 依賴關係圖 |
| [architecture-decisions.md](../architecture/architecture-decisions.md) | 11 項 ADR：Monolith、SDK Adapter、Space Model、Widget、Resource、Event、Progressive、Plugin、Python-First、Event Resilience、FSM |
| [composition-model.md](./composition-model.md) | 樂高組合模型：雙線夾擊、組合配方、決策流程 |
| [roadmap.md](./roadmap.md) | 四階段路線圖：個人 → 知識 → 團隊 → 商業 |

## 相關架構文件

| 檔案 | 內容 |
|------|----------|
| [composite-architecture.md](../architecture/composite-architecture.md) | SDK→CLI→MCP→Skill 四層複合架構 |
| [event-resilience-patterns.md](../architecture/event-resilience-patterns.md) | 6 個事件韌性模式（P1-P6） |
| [ux-shell-redesign.md](../architecture/ux-shell-redesign.md) | App Launcher + Full-Screen Module 架構 |
| [widget-manifest-spec.md](../architecture/widget-manifest-spec.md) | Dashboard Widget 系統規格 |
| [scheduling.md](../architecture/scheduling.md) | 系統排程管理策略 |

## 翻譯

`docs/` 以繁體中文撰寫（source of truth）。`docs-en/` 為英文備份（原始英文版本）。

## 快速參考

### LEGO 組合模型

「專案」與「模組」之間沒有區別 — 一切都是可組合的服務：

```
Bottom-Up: Build service blocks (auth, finance, taskflow, ideagraph, ...)
Top-Down:  Analyze requirements, design blueprints
Meeting:   Compose services into solutions (Legal Advisor, ERP, ...)
```

### 服務類型

| 類型 | 範例 | 資料駐留位置 |
|------|----------|---------------|
| **基礎 (Foundation)** | auth, admin | PostgreSQL |
| **領域 (Domain)** | finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore | PostgreSQL (schema-per-module) |
| **橋接 (Bridge)** | social-hooks, notification | 外部 + Event Bus |
| **工作站 (Station)** | system-monitor, envkit, tmux-webui, session-redactor, sandbox-executor | 本地 / 可選 DB |
| **第三方 (Vendor)** | observability (@disler) | 獨立運行 |
| **組合 (Composition)** | Legal Advisor、Church Music、Virtual CS、ERP/POS | 上述服務的組裝 |

### 架構模式
```
Claude Code → MCP Server (adapter) → FastAPI Core (monolith) → PostgreSQL
                                          ↕
Single React App ─────────────────► FastAPI Core
  ├── Layer 1: 模組 SPA 頁面           (HTTP REST)
  ├── Layer 2: Dashboard Widgets        (HTTP REST)
  └── Layer 3: LLM Chat 浮層           (SSE streaming)
                                          ↕
Social Bridges (LINE/TG/DC) ─────► FastAPI Core
```

### 階段摘要
1. **Phase 1**：auth + finance + taskflow + ideagraph + LINE bot + Widget Dashboard
2. **Phase 2**：memvault v2 + skillpath + intelflow + church music
3. **Phase 3**：workpool + task dispatch + multi-platform social
4. **Phase 4**：商業化 (ERP/POS/legal/virtual CS)
