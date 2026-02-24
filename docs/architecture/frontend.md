---
doc_version: 3
content_hash: d08da8ad
source_version: 3
target_lang: zh-TW
translated_at: 2026-02-23
---

# 前端架構指南

## 三層前端架構

Workshop 前端是一個 Single React App，由三層共存組成：

| 層級 | 名稱 | 說明 |
|------|------|------|
| **Layer 1** | 模組 SPA 頁面 | 每個模組有完整的路由與 UI（`/finance/*`, `/taskflow/*` 等） |
| **Layer 2** | Dashboard Widgets | 首頁儀表板，從各模組抽取 Widget 拖放組合（`/`） |
| **Layer 3** | LLM Chat 浮層 | 跨全域的對話介面，浮在最上層，類似 Google Gemini 嵌入 Chrome |

Layer 2 是 Layer 1 的**補充**（不取代模組頁面）。Layer 3 橫跨所有頁面。

## 設計原則

### 1. 單一應用程式，領域模組

一個以領域為中心組織模組的 React 應用程式。不使用 Module Federation，也不使用微前端 —— 僅透過 `React.lazy` 進行乾淨的程式碼分割（code splitting）。

```
workbench/                    單一 React App
├── src/
│   ├── shell/                應用程式外殼 (佈局、導覽、認證、LLM Chat 浮層)
│   ├── modules/              領域 UI 模組 (10 個核心模組)
│   │   ├── auth/
│   │   ├── finance/
│   │   ├── taskflow/
│   │   ├── ideagraph/
│   │   ├── intelflow/
│   │   ├── memvault/
│   │   ├── skillpath/
│   │   ├── workpool/
│   │   ├── matchcore/
│   │   └── admin/
│   ├── chat/                 LLM Chat 浮層 (Layer 3)
│   ├── widgets/              Workbench Widget 元件庫 (Layer 2)
│   ├── plugins/              插件 UI 運行時
│   └── shared/               共用組件、Hooks、工具函式
```

**為何選擇單一應用程式而非微前端：**
- 更簡單的建置與部署流水線（一次建置，一個產出物）
- 沒有 Module Federation 的複雜度或版本衝突問題
- 共用狀態與路由非常簡單（位於同一個 React 樹中）
- 透過 `React.lazy` 進行程式碼分割可提供等效的延遲載入效果
- 與後端的模組化單體（modular monolith）哲學保持一致

### 2. 領域模組結構

位於 `src/modules/<domain>/` 的每個模組都遵循一致的佈局：

```
src/modules/<domain>/
├── components/              領域特定組件
│   └── <Component>.tsx
├── pages/                   路由層級組件
│   └── <Page>.tsx
├── hooks/                   領域特定 hooks
├── stores/                  Zustand stores（領域作用域）
├── api/                     API 客戶端函式
│   └── client.ts
├── types/                   領域特定型別
└── index.tsx                模組入口（導出路由）
```

### 3. 模組邊界規則

- 模組**可以**從 `src/shared/` 導入
- 模組**絕不可**直接從其他模組導入
- 跨模組互動需經由：
  - **Router**（透過 URL 導覽）
  - **自定義事件**（透過 EventEmitter 進行跨模組通知）
  - **共用 stores** 於 `src/shared/stores/`（認證上下文、使用者狀態）

## 技術棧

詳見 [tech-stack.md](./tech-stack.md#前端)。

## 應用程式外殼 (`src/shell/`)

外殼（Shell）提供應用程式框架：

```
src/shell/
├── App.tsx                  根組件
├── Layout.tsx               頁首、側邊欄、內容區域
├── Router.tsx               具延遲載入的最上層路由
├── AuthProvider.tsx         認證上下文、會話管理
└── ThemeProvider.tsx         深色/淺色模式、CSS 變數
```

### 具程式碼分割的路由

```typescript
// src/shell/Router.tsx
import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";

// 階段 1
const Finance = lazy(() => import("../modules/finance"));
const Quest = lazy(() => import("../modules/taskflow"));
const Muse = lazy(() => import("../modules/ideagraph"));
const Admin = lazy(() => import("../modules/admin"));
// 階段 2
const Scout = lazy(() => import("../modules/intelflow"));
const Lore = lazy(() => import("../modules/memvault"));
const Dojo = lazy(() => import("../modules/skillpath"));
// 階段 3
const Roster = lazy(() => import("../modules/workpool"));
const Nexus = lazy(() => import("../modules/matchcore"));

export function Router() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        {/* 階段 1 */}
        <Route path="/finance/*" element={<Finance />} />
        <Route path="/taskflow/*" element={<Quest />} />
        <Route path="/ideagraph/*" element={<Muse />} />
        <Route path="/admin/*" element={<Admin />} />
        {/* 階段 2 */}
        <Route path="/intelflow/*" element={<Scout />} />
        <Route path="/memvault/*" element={<Lore />} />
        <Route path="/skillpath/*" element={<Dojo />} />
        {/* 階段 3 */}
        <Route path="/workpool/*" element={<Roster />} />
        <Route path="/matchcore/*" element={<Nexus />} />
        <Route path="/settings/*" element={<Settings />} />
      </Routes>
    </Suspense>
  );
}
```

每個模組內部自行處理其子路由。

> **`/` (Dashboard)** 是 Widget 儀表板視圖，從各模組抽取摘要 Widget 組合顯示。各模組的完整 UI 則在 `/finance/*`、`/taskflow/*` 等路由下。

## 路由慣例

| 路徑模式 | 負責者 | 階段 |
|---------|-------|-------|
| `/` | 外殼 (儀表板) | 1 |
| `/finance/*` | Finance 模組 | 1 |
| `/taskflow/*` | Quest 模組 | 1 |
| `/ideagraph/*` | Muse 模組 | 1 |
| `/admin/*` | Admin 模組 | 1 |
| `/intelflow/*` | Scout 模組 | 2 |
| `/memvault/*` | Lore 模組 | 2 |
| `/skillpath/*` | Dojo 模組 | 2 |
| `/workpool/*` | Roster 模組 | 3 |
| `/matchcore/*` | Nexus 模組 | 3 |
| `/settings/*` | 外殼 (全域設定) | 1 |

## API 通訊

所有模組都與同一個後端通訊（位於連接埠 8800 的核心單體 Core Monolith）：

```
workbench/  →  core/  (port 8800)
```

在生產環境中，API 呼叫會經由閘道器（Nginx）進行路由：

```
生產環境：  https://domain.com/api/finance/  → nginx → core monolith
開發環境：  http://localhost:8800/api/finance/ → 直接呼叫
```

每個模組都有自己的 `api/client.ts`，用於封裝其領域端點的 fetch 呼叫。

## 插件 UI 插槽

插件可以將 UI 組件注入到應用程式中預定義的插槽：

```typescript
// src/plugins/PluginSlot.tsx
interface PluginSlotProps {
  name: string;       // 例如："finance.dashboard.sidebar"
  context?: unknown;  // 傳遞給插件組件的資料
}

export function PluginSlot({ name, context }: PluginSlotProps) {
  const plugins = usePluginSlot(name);
  return (
    <>
      {plugins.map((plugin) => (
        <plugin.Component key={plugin.id} context={context} />
      ))}
    </>
  );
}
```

完整插槽清單詳見 [Plugin System](./plugin-system.md#ui-插槽)。

## 共用組件 (`src/shared/`)

```
src/shared/
├── components/              可重複使用的 UI 組件
│   ├── Button.tsx
│   ├── Modal.tsx
│   ├── DataTable.tsx
│   └── ...
├── hooks/                   共用 React hooks
│   ├── useAuth.ts
│   ├── useApi.ts
│   └── ...
├── stores/                  全域 stores (認證、主題)
│   ├── authStore.ts
│   └── themeStore.ts
├── types/                   共用 TypeScript 型別
│   ├── user.ts
│   └── api.ts
└── utils/                   工具函式
```

在任何模組中導入：
```typescript
import { Button } from " @/shared/components/Button";
import { useAuth } from " @/shared/hooks/useAuth";
```

## 建置與部署

單一建置，單一產出物：

```bash
cd workbench && pnpm build   # → 包含 index.html 與 chunks 的 dist/ 目錄
```

生產環境：由 Nginx 提供 `dist/index.html`。程式碼分割後的區塊會根據路由需求進行載入。

開發環境：
```bash
cd workbench && pnpm dev     # → http://localhost:3000
```

Rsbuild 設定會在開發期間將 `/api/*` 代理到核心單體（Core Monolith）。

## LLM Chat 浮層 (Layer 3)

全域 LLM 對話介面，浮在所有頁面最上層，類似 Google 將 Gemini Chat 嵌入 Chrome 的體驗。

```
┌──────────────────────────────────────┐
│  任何頁面 (/finance, /taskflow, ...)     │
│                                      │
│                  ┌───────────────────┐│
│                  │  LLM Chat Panel  ││ ← 浮層，可收合/展開
│                  │  ─────────────── ││
│                  │  使用者: 上個月...││
│                  │  LLM: 根據記錄...││
│                  │  [輸入框]        ││
│                  └───────────────────┘│
└──────────────────────────────────────┘
```

**特性**：
- 不離開當前頁面即可與 LLM 對話
- 可感知當前頁面上下文（例如在 finance 頁面時可直接詢問帳務問題）
- 透過 SSE 串流 LLM 回應
- 可收合/展開，不干擾主要操作
