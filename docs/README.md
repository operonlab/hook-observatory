---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

# Workshop 文件中心

> 所有技術文件的頂層入口。繁體中文為 source of truth，英文備份在 `docs-en/`。

---

## 目錄結構

| 資料夾 | 用途 | 導航 |
|--------|------|------|
| **[vision/](./vision/)** | 平台願景：Workshop 是什麼、為什麼、服務如何組合 | [README](./vision/README.md) |
| **[architecture/](./architecture/)** | 系統架構：ADR、設計模式、技術選型、前後端架構 | [README](./architecture/README.md) |
| **[blueprint/](./blueprint/)** | 建設藍圖：V2 各模組的實作規格與優先級 | [v2-priorities.md](./blueprint/v2-priorities.md) |
| **[plans/](./plans/)** | 戰略計劃：跨模組的演進計劃與路線圖 | 見下方 |
| **[guides/](./guides/)** | 開發者指南：文件管理、功能生命週期 | — |
| **[lessons/](./lessons/)** | 實戰教訓：從專案中提煉的經驗與模式 | [README](./lessons/README.md) |
| **[reference/](./reference/)** | 參考資料：模組研究、工具規格 | — |

---

## 快速導覽

### 我想了解 Workshop 的整體概念
→ [workshop-manifesto.md](./vision/workshop-manifesto.md)（LEGO 組合哲學）
→ [domain-catalog.md](./vision/domain-catalog.md)（統一服務目錄）

### 我想了解系統怎麼設計的
→ [architecture-decisions.md](./architecture/architecture-decisions.md)（11 項 ADR）
→ [modular-monolith.md](./architecture/modular-monolith.md)（後端架構）
→ [composite-architecture.md](./architecture/composite-architecture.md)（SDK→CLI→MCP→Skill 四層）

### 我想了解下一步要做什麼
→ [roadmap.md](./vision/roadmap.md)（四階段路線圖）
→ [v2-priorities.md](./blueprint/v2-priorities.md)（V2 藍圖優先級）

### 我想了解特定模組的實作規格
→ `blueprint/p{N}-{module}.md`（例如 [p5-finance.md](./blueprint/p5-finance.md)）

### 我想了解跨模組的演進策略
→ [plans/composite-architecture-roadmap.md](./plans/composite-architecture-roadmap.md)（四層架構推進）
→ [plans/four-tier-data-lifecycle.md](./plans/four-tier-data-lifecycle.md)（熱暖冷冰資料策略）
→ [plans/skill-ecosystem-hardening.md](./plans/skill-ecosystem-hardening.md)（Skill 生態加固）

---

## 文件管理規範

- 詳見 [docs-management.md](./guides/docs-management.md)
- **集中式**（`docs/`）：跨領域、系統級文件
- **分散式**（各 `README.md`）：模組/服務專屬設置
- 翻譯腳本：`python3 scripts/translate-docs.py`
