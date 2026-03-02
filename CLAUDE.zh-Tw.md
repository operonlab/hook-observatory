---
doc_version: 6
content_hash: aff21e36
---

# Workshop

模組化單體 + 事件驅動工作區。

## 技術棧
- **後端**: Python 3.12 / FastAPI / uv（模組化單體）
- **前端**: React 19 / TypeScript / Rsbuild / pnpm（單一應用）
- **資料庫**: PostgreSQL（各模組 schema 隔離）
- **快取/事件**: Redis（快取 + 事件匯流排）
- **物件儲存**: RustFS（MinIO fork，S3 相容）
- **即時通訊**: LiveKit（WebRTC 語音/視訊）、SSE（串流）
- **可觀測性**: OpenTelemetry + LGTM（開發）/ SigNoz（正式）

## 目錄結構
- `core/` — 模組化單體（10 個核心模組 + 熱路徑服務）
  - `core/src/modules/` — 業務域模組（auth, finance, quest, muse, scout, lore, dojo, roster, nexus, admin）
  - `core/services/realtime/` — LiveKit WebRTC 閘道
  - `core/services/media/` — STT/TTS/影像處理
- `workbench/` — 單一 React 應用
- `mcp/` — MCP 適配層（Core API 的薄封裝）
- `stations/` — 獨立本地工具（system-monitor, llm-usage, envkit, tmux-webui, session-redactor, sandbox-executor）
- `vendor/` — 第三方社群工具（可觀測性）
- `bridges/` — 外部平台連接器（LINE, Telegram, Discord）
- `plugins/` — 插件套件
- `libs/` — 共用函式庫（Python + TypeScript）
- `infra/` — Docker、Nginx、可觀測性設定
- `scripts/` — 建置/翻譯/部署腳本
- `lab/` — POC 實驗
- `docs/` — 架構 + 願景文件（繁體中文，source of truth）
  - `docs/vision/` — 平台願景（宣言、領域目錄、ADRs、路線圖）
  - `docs/architecture/` — 系統架構、ADRs、設計原則
- `docs-en/` — 英文備份（原始英文版本）

## 服務分類
- **基礎層**: auth, admin
- **業務域服務**（有 DB）: finance, quest, muse, scout, lore, dojo, roster, nexus
- **橋接層**: 外部連接器（social-hooks, notification）
- **熱路徑服務**: media（STT/TTS/影像）、realtime（LiveKit）
- **工作站**: 獨立本地工具（system-monitor, llm-usage, envkit, tmux-webui, session-redactor, sandbox-executor）
- **第三方**: 社群工具（可觀測性）
- **組合應用**: 特定場景的服務組裝（法律顧問、教會音樂、虛擬客服、ERP/POS）

## 核心概念
- **LEGO 組合**: 服務是可重用的積木。專案 = 擴展服務 + 組合服務，不區分「專案」與「模組」。
- **事件驅動**: 所有狀態變更皆為事件，流經 EventBus
- **RBAC+ABAC**: 角色型 + 屬性型權限混合機制
- **Hook/Plugin**: 透過插件清單 + Hook 匯流排進行擴展
- **模組邊界**: 模組間透過事件通訊（寫入）或服務匯入（讀取）
