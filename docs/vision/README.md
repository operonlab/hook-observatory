---
doc_version: 4
content_hash: 1dafee87
source_version: 4
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
| [architecture-decisions.md](./architecture-decisions.md) | 7 項 ADR：Monolith、MCP Adapter、Space Model、Widget、Resource、Event、Progressive |
| [roadmap.md](./roadmap.md) | 四階段路線圖：個人 → 知識 → 團隊 → 商業 |

## 翻譯

英文是唯一真實來源（本目錄）。翻譯由 `scripts/translate-docs.py` 自動產生至 `docs-<lang>/`（例如 `docs-zh-TW/`、`docs-ja/`）。

## 快速參考

### LEGO 組合模型

「專案」與「模組」之間沒有區別 — 一切都是可組合的服務：

```
Bottom-Up: Build service blocks (auth, finance, quest, muse, ...)
Top-Down:  Analyze requirements, design blueprints
Meeting:   Compose services into solutions (Legal Advisor, ERP, ...)
```

### 服務類型

| 類型 | 範例 | 資料駐留位置 |
|------|----------|---------------|
| **基礎 (Foundation)** | auth, admin | PostgreSQL |
| **領域 (Domain)** | finance, quest, muse, intel, memory, skill, workforce, matching | PostgreSQL (schema-per-module) |
| **橋接 (Bridge)** | social-hooks, notification | 外部 + Event Bus |
| **工作站 (Station)** | 磁碟分析、LLM 用量、本地工具 | 本地 / 可選 DB |
| **組合 (Composition)** | Legal Advisor、Church Music、Virtual CS、ERP/POS | 上述服務的組裝 |

### 架構模式
```
Claude Code → MCP Server (adapter) → FastAPI Core (monolith) → PostgreSQL
                                          ↕
Web Dashboard (widgets) ──────────► FastAPI Core
                                          ↕
Social Bridges (LINE/TG/DC) ─────► FastAPI Core
```

### 階段摘要
1. **Phase 1**：auth + finance + quest + muse + LINE bot + Widget Dashboard
2. **Phase 2**：memory v2 + skill + intel + church music
3. **Phase 3**：workforce + task dispatch + multi-platform social
4. **Phase 4**：商業化 (ERP/POS/legal/virtual CS)
