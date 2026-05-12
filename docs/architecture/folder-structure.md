---
doc_version: 6
content_hash: pending
source_version: 6
target_lang: zh-TW
translated_at: 2026-03-28
---

# 目錄結構與命名規範

> 本文檔是**靜態規範**。各 service 當前的 Rust/Go 重寫進度、開源發行版同步狀態（動態快照）見 [rewrite-status.md](./rewrite-status.md)。開源下游發行版的設計模式見 [distribution-pattern.md](./distribution-pattern.md)。

## 四層分類法

Workshop 將所有功能組織成四個層級：

| 層級 | 描述 | 位置 | DB 依賴 |
|------|------|------|---------|
| **核心模組 (Core Modules)** | 由資料庫支援的業務領域（18 個模組） | `core/src/modules/` | ✅ Core PostgreSQL |
| **微服務 (Services)** | 從 Core 提取的獨立服務（共用 DB） | `services/` | ✅ Core PostgreSQL |
| **工作站 (Stations)** | 獨立的本地工具（不依賴核心資料庫） | `stations/` | ❌ |
| **橋接器 (Bridges)** | 外部平台連接器 | `bridges/` | ❌ |

### Core vs Services vs Stations 區分

```
core/              ─── monolith 內的模組，共用同一個 FastAPI process
services/          ─── 從 core 提取的獨立 FastAPI process，共用 Core PostgreSQL
stations/          ─── 完全獨立的本地工具，不碰 Core DB
```

微服務（`services/`）是漸進式拆分的產物：零跨模組依賴的 Core 模組可提取為獨立服務，部署到不同機器（如 Windows GPU 節點），但共用同一個 PostgreSQL（各自 schema 隔離）。

## 概覽

```
~/workshop/
├── core/                        # 模塊化單體 (Python/FastAPI, port 10000)
│   ├── cli/                     # Core Module CLI 包裝器
│   ├── src/
│   │   ├── events/              # 事件匯流排引擎
│   │   ├── hooks/               # 鉤子/插件引擎
│   │   ├── modules/             # 核心模組 (18 個領域)
│   │   │   ├── auth/            # 認證與授權
│   │   │   ├── finance/         # 會計與財務
│   │   │   ├── taskflow/        # 任務與調度
│   │   │   ├── ideagraph/       # 想法與知識圖譜
│   │   │   ├── intelflow/       # 情報研究
│   │   │   ├── memvault/        # LLM 記憶持久化
│   │   │   ├── skillpath/       # 技能樹與學習路徑
│   │   │   ├── workpool/        # 資源管理
│   │   │   ├── matchcore/       # 匹配引擎
│   │   │   ├── admin/           # 平台管理
│   │   │   ├── nodeflow/        # 工作流編排
│   │   │   ├── notification/    # 多通道通知
│   │   │   ├── invest/          # 投資追蹤
│   │   │   ├── briefing/        # 每日簡報
│   │   │   ├── capture/         # 模糊意圖捕捉
│   │   │   ├── dailyos/         # 每日規劃
│   │   │   ├── paper/           # 論文研究
│   │   │   └── assistant/       # AI 助理對話
│   │   ├── middleware/          # Auth, CORS, OTel 中間件
│   │   ├── shared/              # 共享類型、工具
│   │   └── routes/              # 路由聚合
│   ├── services/                # 熱路徑服務 (獨立部署, 目前僅 stub)
│   │   ├── realtime/            # LiveKit WebRTC 網關 (規劃中, 未部署)
│   │   └── media/               # STT/TTS/圖像處理 (規劃中, 未部署)
│   ├── plugins/                 # 已安裝插件
│   ├── migrations/              # 資料庫遷移 (所有 schema)
│   └── tests/
├── services/                    # 從 Core 提取的微服務
│   ├── paper/                   # 論文研究 (port 10010)
│   ├── intelflow/               # 情報研究 (port 10011)
│   └── invest/                  # 投資追蹤 (port 10012)
├── workbench/                   # 單個 React 應用程式 (port 3000)
│   ├── src/
│   │   ├── shell/               # 應用程式外殼 (佈局、導航、認證)
│   │   ├── modules/             # 領域 UI 模組 (對應核心模組)
│   │   ├── plugins/             # 插件 UI 運行時 + 插槽
│   │   └── shared/              # 共享組件、鉤子、工具
│   ├── public/
│   ├── rsbuild.config.ts
│   └── package.json
├── mcp/                         # MCP 適配層 (SDK-based, 23 servers)
├── stations/                    # 獨立本地工具 (19 個工作站)
│   ├── agent-metrics/           # 多 Agent 任務管理 + Maestro 調度中心
│   ├── agent-vista/             # Agent 虛擬辦公室視覺化
│   ├── anvil/                   # Skill 生命週期管理
│   ├── auto-survey/             # 自動填表
│   ├── capture-console/         # 捕捉控制台
│   ├── fleet/                   # 遠端運算節點調度
│   ├── hook-observatory/        # Hook 事件可觀測性
│   ├── ocr/                     # 文字辨識
│   ├── sentinel/                # 服務健康檢查與自動修復
│   ├── session-archiver/        # Session 歸檔與壓縮
│   ├── session-channel/         # 跨 Session 通訊
│   ├── stt/                     # 語音轉文字
│   ├── system-monitor/          # 硬體資源監控
│   ├── tmux-webui/              # tmux 瀏覽器控制介面
│   ├── translate/               # 翻譯服務
│   ├── tts/                     # 文字轉語音
│   ├── video-edit/              # 影片剪輯
│   ├── vision/                  # 視覺分析
│   └── voice-gateway/           # 語音閘道
├── vendor/                      # 第三方社群工具（不改造）
├── bridges/                     # 外部平台連接器
├── plugins/                     # 插件包 (基於 git)
├── libs/                        # 共享庫
│   ├── sdk-client/              # Python SDK: 38 API clients + utils
│   ├── audio-ops/               # 音訊操作 operators
│   ├── tmux-lib/                # tmux 互動庫
│   ├── svc-shared/              # 微服務共用 (database, errors, models, schemas, services)
│   ├── ai-assistant/            # TypeScript AI 助理
│   └── live2d-core/             # TypeScript Live2D 引擎
├── infra/
│   ├── docker/                  # docker-compose, Dockerfiles
│   ├── komodo/                  # Komodo Core + Periphery 部署設定
│   ├── nginx/                   # Nginx 配置, 路由規則
│   └── observability/           # OTel, Grafana, SigNoz
├── schedules/                   # Cronicle 排程任務定義
├── scripts/                     # 構建/部署/維運腳本
├── docs/                        # 系統架構 + 願景文檔 (繁體中文)
├── lab/                         # POC 實驗
├── pyproject.toml               # Python 工作區根目錄 (uv)
└── package.json                 # JS 工作區根目錄 (pnpm)
```

## 微服務 (`services/`)

從 Core Monolith 提取的獨立 FastAPI 服務。共用同一個 PostgreSQL，各自 schema 隔離。前端 UI 不動（仍在 workbench SPA 內）。

### 提取條件

- 零跨模組依賴（不 import 其他 Core 模組的 services/models）
- 移除 EventBus、@cached、audit trail、auth middleware
- Auth 在 Nginx gateway 層處理

### 目錄結構

```
services/<name>/
├── <name>/                  # Python package
│   ├── __init__.py
│   ├── models.py            # SQLAlchemy models
│   ├── schemas.py           # Pydantic schemas
│   ├── services.py          # 業務邏輯
│   └── routes.py            # FastAPI routes
├── main.py                  # FastAPI app, /health, error handler
├── config.py                # pydantic-settings (env prefix)
├── test_<name>.py           # 六鐵律測試
├── pyproject.toml           # 依賴 svc-shared
├── Dockerfile
└── .venv/
```

### 現有微服務

| 服務 | Port | Schema | Routes | Tests | 狀態 |
|------|------|--------|--------|-------|------|
| `paper` | 10010 | `paper` | 14 | 32 | ✅ prod |
| `intelflow` | 10011 | `intelflow` | 19 | 41 | ✅ prod |
| `invest` | 10012 | `invest` | 19 | 41 | ✅ prod |

### Nginx 路由

微服務的 `location ^~ /api/<name>/` block 必須放在通用 `/api/` block **之前**（Nginx 最長前綴匹配）。

```nginx
location ^~ /api/paper/     { proxy_pass http://127.0.0.1:10010; }
location ^~ /api/intelflow/ { proxy_pass http://127.0.0.1:10011; }
location ^~ /api/invest/    { proxy_pass http://127.0.0.1:10012; }
location ^~ /api/           { proxy_pass http://127.0.0.1:10000; }  # Core
```

## 命名規則

### 核心模組 (`core/src/modules/`)

| 規則 | 範例 | 反面模式 |
|------|---------|-------------|
| 小寫、蛇形命名法 (snake_case) | `auth`, `finance` | `Auth`, `userAuth` |
| 名詞或名詞短語 | `finance`, `taskflow` | `handle_payments` |
| 與資料庫 schema 名稱一致 | 模組 `finance` → schema `finance` | 不同的名稱 |

每個模組目錄：
```
core/src/modules/<name>/
├── __init__.py          # 模組註冊、路由導出
├── routes.py            # FastAPI 路由
├── models.py            # 資料庫模型 (模組範圍)
├── schemas.py           # Pydantic 請求/響應 schema
├── services.py          # 業務邏輯 (公開 API)
├── events.py            # 事件處理器
├── hooks.py             # 鉤子點
└── deps.py              # FastAPI 依賴項
```

### 18 個核心模組

| 模組 | 領域 | 階段 | 資料庫 Schema |
|--------|--------|-------|-----------|
| `auth` | 認證與授權 | 1 | `auth` |
| `finance` | 會計與財務 | 1 | `finance` |
| `taskflow` | 任務與調度 | 1 | `taskflow` |
| `ideagraph` | 想法與知識圖譜 | 1 | `ideagraph` |
| `admin` | 平台管理 | 1 | `admin` |
| `intelflow` | 情報研究 | 2 | `intelflow` |
| `memvault` | LLM 記憶持久化 | 2 | `memvault` |
| `skillpath` | 技能樹與學習路徑 | 2 | `skillpath` |
| `nodeflow` | 工作流編排、DAG 執行 | 2 | `nodeflow` |
| `notification` | 多通道通知 | 2 | `notification` |
| `invest` | 投資追蹤、組合分析 | 2 | `invest` |
| `briefing` | 每日簡報 | 2 | `briefing` |
| `capture` | 模糊意圖捕捉 | 2 | `capture` |
| `dailyos` | 每日規劃 | 2 | `dailyos` |
| `paper` | 論文研究 | 2 | `paper` |
| `assistant` | AI 助理對話 | 2 | `assistant` |
| `workpool` | 資源管理 | 3 | `workpool` |
| `matchcore` | 匹配引擎 | 3 | `matchcore` |

### 前端模組 (`workbench/src/modules/`)

| 規則 | 範例 | 反面模式 |
|------|---------|-------------|
| 小寫、短橫線命名法 (kebab-case) | `finance`, `taskflow` | `Finance`, `questModule` |
| 匹配後端模組 | `modules/finance` ↔ `core/src/modules/finance` | 不同名稱 |

每個前端模組：
```
workbench/src/modules/<name>/
├── components/          # 領域特定組件
├── pages/               # 路由層級組件
├── hooks/               # 領域特定鉤子
├── stores/              # Zustand 狀態庫
├── api/                 # API 客戶端函數
├── types/               # 領域特定類型
└── index.tsx            # 模組入口 (導出路由)
```

### 工作站 (`stations/`)

可獨立運行的本地工具。不依賴 Core PostgreSQL。

```
stations/<name>/
├── cli/                 # Station CLI（argparse + 匯入 SDK）
│   └── <cmd>.py
├── src/                 # 源碼
├── README.md
└── package.json / pyproject.toml
```

### 共享庫 (`libs/`)

被 **2 個以上模組或服務**使用的共享代碼。如果只有一個使用者，請保留在該使用者目錄中。

```
libs/
├── sdk-client/              # Python SDK: API clients + port_registry + utils
├── audio-ops/               # 音訊操作 operators
├── tmux-lib/                # tmux 互動庫 (patterns, primitives, cli_session)
├── svc-shared/              # 微服務共用基礎設施
│   └── svc_shared/
│       ├── database.py      # async engine + session factory
│       ├── errors.py        # WorkshopError hierarchy
│       ├── models.py        # Base, TimestampMixin, SoftDeleteMixin, SpaceScopedModel
│       ├── schemas.py       # PaginatedResponse, SpaceScopedResponse
│       └── services.py      # BaseCRUDService (Template Method)
├── ai-assistant/            # TypeScript AI 助理 (mascot, stream handler)
└── live2d-core/             # TypeScript Live2D 引擎
```

### 基礎設施 (`infra/`)

```
infra/
├── docker/                  # docker-compose 文件, 基礎 Dockerfile
├── komodo/                  # 多機器部署管理
│   ├── docker-compose.yml   # Core + MongoDB (Mac)
│   ├── periphery/           # Periphery Agent (Windows)
│   └── stacks/              # Komodo Stack 定義
├── nginx/                   # Nginx 配置, 路由規則
└── observability/           # OTel 收集器, Grafana, SigNoz
```

### MCP 適配器 (`mcp/`)

SDK-based protocol 適配層，透過 SDK 客戶端將核心服務與工作站公開為 MCP 工具。MCP 伺服器永遠不會直接接觸資料庫。

```
mcp/<server-name>/
├── server.py            # MCP 伺服器入口點
├── tools/               # 工具定義
└── README.md
```

### 橋接器 (`bridges/`)

外部平台連接器。每個橋接器封裝一個第三方 API。

```
bridges/<platform>/
├── __init__.py
├── client.py            # 平台 API 客戶端
├── webhook.py           # 進入的 webhook 處理器
├── events.py            # 橋接器特定事件
└── schemas.py           # 平台特定 schema
```

### 文檔 (`docs/`)

僅限跨領域文檔。領域特定文檔位於每個模組/服務的 `README.md` 中。

```
docs/
├── architecture/            # 系統架構, ADRs
├── blueprint/               # 實作藍圖
├── plans/                   # 功能規劃
├── reference/               # 參考資料
├── vision/                  # 平台願景文檔
└── guides/                  # 開發者指南
```

**翻譯工作流**：`docs/` 以繁體中文撰寫（source of truth）。`docs-en/` 為英文備份。

### 實驗室 (`lab/`)

POC 實驗與原型展示。**生命週期**：`lab/<name>-poc/` → 驗證 → 晉升至 `core/src/modules/` 或 `services/` → 封存或刪除。

## 領域映射

```
                  core/src/modules/finance/           ← 後端邏輯 (monolith)
Finance 領域 ──
                  workbench/src/modules/finance/      ← 前端 UI

                  services/paper/                     ← 後端邏輯 (微服務)
Paper 領域 ────
                  workbench/src/modules/paper/        ← 前端 UI (仍在 SPA 內)

                  core/services/media/                ← 獨立服務，無前端
Media 領域 ────
                  (無前端模組)
```

## Port 規範

單一真值源：`libs/sdk-client/sdk_client/port_registry.py`

| 範圍 | 用途 |
|------|------|
| 10000-10099 | Core + 微服務 |
| 10100-10199 | Stations — Infra & Ops |
| 10200-10299 | Stations — AI & Media |
| 10300-10399 | Stations — Business & Tools |
| 10500-10599 | Frontend |

## 核心原則

1. **四層分類法** —— Core / Services / Stations / Bridges
2. **模塊化單體優先** —— 在單個可部署單元內按業務領域組織，按需提取微服務
3. **模組邊界** —— 禁止跨模組模型導入；使用服務層或事件
4. **共享代碼是顯式的** —— 僅共享 `libs/` 的內容
5. **約定優於配置** —— 一致的命名意味著需要的文檔更少
6. **繁體中文為事實來源** —— `docs/` 以繁體中文撰寫
