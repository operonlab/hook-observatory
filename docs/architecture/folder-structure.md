---
doc_version: 4
content_hash: adfe14e5
source_version: 4
target_lang: zh-TW
translated_at: 2026-02-23
---

# 目錄結構與命名規範

## 三層分類法

Workshop 將所有功能組織成三個層級：

| 層級 | 描述 | 位置 |
|------|-------------|----------|
| **核心模組 (Core Modules)** | 由資料庫支援的業務領域（10 個模組） | `core/src/modules/` |
| **工作站 (Stations)** | 獨立的本地工具（不依賴核心資料庫） | `stations/` |
| **橋接器 (Bridges)** | 外部平台連接器 | `bridges/` |

## 概覽

```
~/workshop/
├── core/                        # 模塊化單體 (Python/FastAPI)
│   ├── src/
│   │   ├── events/              # 事件匯流排引擎
│   │   ├── hooks/               # 鉤子/插件引擎
│   │   ├── modules/             # 核心模組 (10 個領域)
│   │   │   ├── auth/            # 認證與授權
│   │   │   ├── finance/         # 會計與財務
│   │   │   ├── quest/           # 任務與調度
│   │   │   ├── muse/            # 想法與知識圖譜
│   │   │   ├── intel/           # 每日情報
│   │   │   ├── memory/          # LLM 記憶持久化
│   │   │   ├── skill/           # 技能樹與學習路徑
│   │   │   ├── workforce/       # 資源管理
│   │   │   ├── matching/        # 匹配引擎
│   │   │   └── admin/           # 平台管理
│   │   ├── middleware/          # Auth, CORS, OTel 中間件
│   │   ├── shared/              # 共享類型、工具
│   │   └── routes/              # 路由聚合
│   ├── services/                # 熱路徑服務 (獨立部署)
│   │   ├── realtime/            # LiveKit WebRTC 網關
│   │   └── media/               # STT/TTS/圖像處理
│   ├── plugins/                 # 已安裝插件
│   ├── migrations/              # 資料庫遷移 (所有 schema)
│   └── tests/
├── dashboard/                   # 單個 React 應用程式
│   ├── src/
│   │   ├── shell/               # 應用程式外殼 (佈局、導航、認證)
│   │   ├── modules/             # 領域 UI 模組 (對應核心模組)
│   │   │   ├── auth/
│   │   │   ├── finance/
│   │   │   ├── quest/
│   │   │   ├── muse/
│   │   │   ├── intel/
│   │   │   ├── memory/
│   │   │   ├── skill/
│   │   │   ├── workforce/
│   │   │   ├── matching/
│   │   │   └── admin/
│   │   ├── plugins/             # 插件 UI 運行時 + 插槽
│   │   └── shared/              # 共享組件、鉤子、工具
│   ├── public/
│   ├── rsbuild.config.ts
│   └── package.json
├── mcp/                         # MCP 適配層 (對核心 API 的薄封裝)
├── stations/                    # 獨立本地工具
│   └── sandbox-executor/        # 沙盒代碼執行 MCP 伺服器
├── bridges/                     # 外部平台連接器
│   └── (LINE, Telegram, Discord, Firebase — 計劃中)
├── plugins/                     # 插件包 (基於 git)
├── libs/
│   ├── python/                  # Python 共享庫
│   └── typescript/              # TypeScript 共享庫
├── infra/
│   ├── docker/                  # docker-compose, Dockerfiles
│   ├── nginx/                   # Nginx 配置, 路由規則
│   ├── observability/           # LGTM/SigNoz 配置, 儀表板
│   └── scripts/                 # 部署腳本, CI/CD 助手
├── docs/
│   ├── architecture/            # 系統架構文檔
│   ├── blueprint/               # 實作藍圖
│   ├── reference/               # 參考資料
│   ├── vision/                  # 平台願景 (宣言、領域、ADR、路線圖)
│   └── zh-TW/                   # 繁體中文翻譯 (自動生成)
│       ├── architecture/        # docs/architecture/ 的鏡像
│       ├── blueprint/           # docs/blueprint/ 的鏡像
│       ├── reference/           # docs/reference/ 的鏡像
│       ├── vision/              # docs/vision/ 的鏡像
│       └── CLAUDE.zh-TW.md     # 根目錄 CLAUDE.md 的鏡像
├── scripts/                     # 構建/翻譯/部署腳本
│   └── translate-docs.py       # 通過 Gemini CLI 自動將文檔翻譯成繁體中文 (zh-TW)
├── lab/                         # POC 實驗
├── pyproject.toml               # Python 工作區根目錄 (uv)
└── package.json                 # JS 工作區根目錄 (pnpm)
```

## 命名規則

### 核心模組 (`core/src/modules/`)

| 規則 | 範例 | 反面模式 |
|------|---------|-------------|
| 小寫、蛇形命名法 (snake_case) | `auth`, `finance` | `Auth`, `userAuth` |
| 名詞或名詞短語 | `finance`, `quest` | `handle_payments` |
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

### 10 個核心模組

| 模組 | 領域 | 階段 | 資料庫 Schema |
|--------|--------|-------|-----------|
| `auth` | 認證與授權 | 1 | `auth` |
| `finance` | 會計與財務 | 1 | `finance` |
| `quest` | 任務與調度 | 1 | `quest` |
| `muse` | 想法與知識圖譜 | 1 | `muse` |
| `intel` | 每日情報 | 2 | `intel` |
| `memory` | LLM 記憶持久化 | 2 | `memory` |
| `skill` | 技能樹與學習路徑 | 2 | `skill` |
| `workforce` | 資源管理 | 3 | `workforce` |
| `matching` | 匹配引擎 | 3 | `matching` |
| `admin` | 平台管理 | 1 | `admin` |

### 前端模組 (`dashboard/src/modules/`)

| 規則 | 範例 | 反面模式 |
|------|---------|-------------|
| 小寫、短橫線命名法 (kebab-case) | `finance`, `quest` | `Finance`, `questModule` |
| 匹配後端模組 | `modules/finance` ↔ `core/src/modules/finance` | 不同的名稱 |

每個前端模組：
```
dashboard/src/modules/<name>/
├── components/          # 領域特定組件
├── pages/               # 路由層級組件
├── hooks/               # 領域特定鉤子
├── stores/              # Zustand 狀態庫
├── api/                 # API 客戶端函數
├── types/               # 領域特定類型
└── index.tsx            # 模組入口 (導出路由)
```

### 熱路徑服務 (`core/services/`)

| 規則 | 範例 | 反面模式 |
|------|---------|-------------|
| 小寫、短橫線命名目錄 | `realtime`, `media` | `livekit-service` |
| Python 套件：蛇形命名法 (snake_case) | `src/realtime/` | `src/realtime-service/` |

每個熱路徑服務：
```
core/services/<name>/
├── src/<package>/
│   ├── __init__.py
│   ├── main.py          # FastAPI 應用程式入口點
│   ├── routes/
│   └── core/
├── tests/
├── Dockerfile
├── pyproject.toml
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

計劃中的橋接器：LINE, Telegram, Discord, Firebase。

### MCP 適配器 (`mcp/`)

薄封裝層，將核心 API 端點公開為 MCP 工具。MCP 伺服器永遠不會直接接觸資料庫。

```
mcp/<server-name>/
├── server.py            # MCP 伺服器入口點
├── tools/               # 工具定義
└── README.md
```

### 工作站 (`stations/`)

不依賴核心資料庫的獨立本地工具。每個工作站都是自成一體的。

```
stations/<name>/
├── src/                 # 源碼
├── README.md
└── package.json / pyproject.toml
```

### 插件 (`plugins/`)

```
plugins/
├── <plugin-name>/
│   ├── plugin.json      # 插件清單
│   ├── backend/         # Python 鉤子
│   │   └── hooks.py
│   ├── frontend/        # React 組件 (選填)
│   │   └── components/
│   └── README.md
```

### 共享庫 (`libs/`)

被 **2 個以上模組或服務**使用的共享代碼。如果只有一個使用者，請保留在該使用者目錄中。

```
libs/
├── python/                  # Python 共享庫
│   ├── src/corelib/         # 可作為 `from corelib import ...` 導入
│   ├── pyproject.toml
│   └── README.md
└── typescript/              # TypeScript 共享庫
    ├── src/
    │   ├── components/      # 共享 UI 組件
    │   ├── hooks/           # 共享 React 鉤子
    │   ├── types/           # 共享 TypeScript 類型
    │   └── utils/           # 共享工具
    ├── package.json
    └── README.md
```

### 基礎設施 (`infra/`)

```
infra/
├── docker/                  # docker-compose 文件, 基礎 Dockerfile
├── nginx/                   # Nginx 配置, 路由規則
├── observability/           # OTel 收集器配置, Grafana 儀表板, SigNoz 設置
└── scripts/                 # 部署腳本, CI/CD 助手
```

### 文檔 (`docs/`)

僅限跨領域文檔。領域特定文檔位於每個模組/服務的 `README.md` 中。

```
docs/
├── architecture/            # 系統架構, ADRs
├── blueprint/               # 實作藍圖
├── reference/               # 參考資料
├── vision/                  # 平台願景文檔
│   ├── workshop-manifesto.md    # 何謂 Workshop
│   ├── domain-catalog.md        # 10 個核心模組 + 5 個專案構想
│   ├── architecture-decisions.md # 腦力激盪產出的 7 個 ADR
│   └── roadmap.md               # 四階段路線圖
├── zh-TW/                   # 繁體中文翻譯
│   ├── architecture/        # *.zh-TW.md 文件
│   ├── blueprint/
│   ├── reference/
│   ├── vision/
│   └── CLAUDE.zh-TW.md
├── api/                     # API 設計標準
├── runbooks/                # 運作程序
└── guides/                  # 開發者入職指南
```

**翻譯工作流**：英文文檔為單一事實來源。運行 `python3 scripts/translate-docs.py` 以自動翻譯至繁體中文 (zh-TW)。版本追蹤通過 YAML frontmatter (`doc_version` + `content_hash`) 進行。

### 腳本 (`scripts/`)

```
scripts/
└── translate-docs.py        # 自動將文檔翻譯成繁體中文 (Gemini CLI)
```

### 實驗室 (`lab/`)

POC 實驗與原型展示。這裡的任何內容都不會被生產代碼導入。

| 規則 | 範例 | 反面模式 |
|------|---------|-------------|
| `<name>-poc` 後綴 | `finance-poc/` | `finance/` (與模組衝突) |
| 每個 POC 都有 README.md | 記錄目標、假設、結論 | 沒有文檔，孤立的輸出 |

每個實驗目錄：
```
lab/<name>-poc/
├── README.md              # 目標、假設、結論 (即使失敗了)
├── outputs/               # 技能 / 腳本輸出 (.md, .json 等)
└── scripts/               # 快速驗證腳本
```

**生命週期**：`lab/<name>-poc/` → 驗證 → 晉升至 `core/src/modules/` + `dashboard/src/modules/` → 封存或刪除實驗項目。

## 領域映射

領域在後端模組與前端模組之間垂直映射：

```
                  core/src/modules/finance/           ← 後端邏輯
Finance 領域 ──
                  dashboard/src/modules/finance/      ← 前端 UI

                  core/src/modules/auth/              ← 後端邏輯
Auth 領域 ─────
                  dashboard/src/modules/auth/         ← 前端 UI (登入、註冊)

                  core/services/media/                ← 獨立服務，無前端
Media 領域 ────
                  (無前端模組)
```

## 核心原則

1. **三層分類法** —— 核心模組 (資料庫支援) / 工作站 (本地工具) / 橋接器 (連接器)
2. **模塊化單體** —— 在單個可部署單元內按業務領域組織
3. **模組邊界** —— 禁止跨模組模型導入；使用服務層或事件
4. **共享代碼是顯式的** —— 僅共享 `libs/` 與 `shared/` 的內容
5. **約定優於配置** —— 一致的命名意味著需要的文檔更少
6. **每個單元一個 README.md** —— 每個服務和重要的模組都有自己的 README
7. **繁體中文為事實來源** —— `docs/` 以繁體中文撰寫（source of truth），`docs-en/` 為英文備份
