---
doc_version: 3
content_hash: d08da8ad
source_version: 3
translated_at: 2026-02-23
---

# 前端架構指南

## 設計原則

### 1. 單一應用程式，領域模組化

採用單一 React 應用程式，並以領域（Domain）為基礎進行模組組織。不使用模組聯邦（Module Federation），不使用微前端（micro-frontends）——僅透過 `React.lazy` 進行乾淨的程式碼拆分（code splitting）。

```
dashboard/                    單一 React 應用程式
├── src/
│   ├── shell/                應用程式外殼 (佈局, 導航, 認證)
│   ├── modules/              領域 UI 模組 (10 個核心模組)
│   │   ├── auth/
│   │   ├── finance/
│   │   ├── quest/
│   │   ├── muse/
│   │   ├── intel/
│   │   ├── memory/
│   │   ├── skill/
│   │   ├── workforce/
│   │   ├── matching/
│   │   └── admin/
│   ├── plugins/              外掛 UI 運行時
│   └── shared/               共用組件, hooks, 工具函數
```

**為何選擇單一應用程式而非微前端：**
- 更簡單的建置與部署流水線（一次建置，一個產物）
- 無需面對模組聯邦的複雜性或版本衝突問題
- 共用狀態與路由處理非常簡單（位於同一個 React 樹中）
- 透過 `React.lazy` 進行程式碼拆分，可提供同等的延遲載入效果
- 與後端的模組化單體（modular monolith）哲學保持一致

### 2. 領域模組結構

`src/modules/<domain>/` 下的每個模組都遵循一致的佈局：

```
src/modules/<domain>/
├── components/              領域特定組件
│   └── <Component>.tsx
├── pages/                   路由層級組件
│   └── <Page>.tsx
├── hooks/                   領域特定 hooks
├── stores/                  Zustand 商店 (領域作用域)
├── api/                     API 客戶端函數
│   └── client.ts
├── types/                   領域特定型別
└── index.tsx                模組入口 (匯出路由)
```

### 3. 模組邊界規則

- 模組**可以**從 `src/shared/` 導入內容
- 模組**嚴禁**直接從其他模組導入內容
- 跨模組互動必須透過：
  - **Router** (透過 URL 進行導航)
  - **自定義事件** (透過 EventEmitter 進行跨模組通知)
  - **共用商店** 位於 `src/shared/stores/` (如認證上下文、使用者狀態)

## 技術棧

| 層級 | 選擇 | 理由 |
|-------|--------|-----------|
| 建置 (Build) | Rsbuild | 基於 Rspack，建置速度極快 |
| 框架 (Framework) | React 19 | 組件模型、生態系統、並行特性 |
| 路由 (Routing) | React Router 7 | 支援延遲載入、巢狀路由 |
| 樣式 (Styling) | Tailwind CSS 4 | Utility-first，一致的設計標記 (design tokens) |
| 狀態 (State) | Zustand 5 | 輕量化，支援模組化作用域 |
| 型別 (Types) | TypeScript 5 | 嚴格模式，透過 `src/shared/types/` 共用型別 |

## 應用程式外殼 (`src/shell/`)

外殼（Shell）提供應用程式的框架：

```
src/shell/
├── App.tsx                  根組件
├── Layout.tsx               頁首、側邊欄、內容區域
├── Router.tsx               頂層路由，支援延遲載入
├── AuthProvider.tsx         認證上下文、會話管理
└── ThemeProvider.tsx         深色/淺色模式、CSS 變數
```

### 路由與程式碼拆分

```typescript
// src/shell/Router.tsx
import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";

// 第一階段 (Phase 1)
const Finance = lazy(() => import("../modules/finance"));
const Quest = lazy(() => import("../modules/quest"));
const Muse = lazy(() => import("../modules/muse"));
const Admin = lazy(() => import("../modules/admin"));
// 第二階段 (Phase 2)
const Intel = lazy(() => import("../modules/intel"));
const Memory = lazy(() => import("../modules/memory"));
const Skill = lazy(() => import("../modules/skill"));
// 第三階段 (Phase 3)
const Workforce = lazy(() => import("../modules/workforce"));
const Matching = lazy(() => import("../modules/matching"));

export function Router() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        {/* 第一階段 */}
        <Route path="/finance/*" element={<Finance />} />
        <Route path="/quest/*" element={<Quest />} />
        <Route path="/muse/*" element={<Muse />} />
        <Route path="/admin/*" element={<Admin />} />
        {/* 第二階段 */}
        <Route path="/intel/*" element={<Intel />} />
        <Route path="/memory/*" element={<Memory />} />
        <Route path="/skill/*" element={<Skill />} />
        {/* 第三階段 */}
        <Route path="/workforce/*" element={<Workforce />} />
        <Route path="/matching/*" element={<Matching />} />
        <Route path="/settings/*" element={<Settings />} />
      </Routes>
    </Suspense>
  );
}
```

每個模組在內部處理自己的子路由。

## 路由慣例

| 模式 | 擁有者 | 階段 |
|---------|-------|-------|
| `/` | Shell (儀表板) | 1 |
| `/finance/*` | Finance 模組 | 1 |
| `/quest/*` | Quest 模組 | 1 |
| `/muse/*` | Muse 模組 | 1 |
| `/admin/*` | Admin 模組 | 1 |
| `/intel/*` | Intel 模組 | 2 |
| `/memory/*` | Memory 模組 | 2 |
| `/skill/*` | Skill 模組 | 2 |
| `/workforce/*` | Workforce 模組 | 3 |
| `/matching/*` | Matching 模組 | 3 |
| `/settings/*` | Shell (全域設定) | 1 |

## API 通訊

所有模組都與同一個後端通訊（位於 8800 端口的核心單體）：

```
dashboard/  →  core/  (port 8800)
```

在生產環境中，API 調用會透過網關 (Nginx) 進行路由：

```
生產環境:  https://domain.com/api/finance/  → nginx → 核心單體
開發環境: http://localhost:8800/api/finance/ → 直接通訊
```

每個模組都有自己的 `api/client.ts`，用於封裝其領域端點的 fetch 調用。

## 外掛 UI 插槽

外掛可以將 UI 組件注入到應用程式中預定義的插槽（Slots）中：

```typescript
// src/plugins/PluginSlot.tsx
interface PluginSlotProps {
  name: string;       // 例如: "finance.dashboard.sidebar"
  context?: unknown;  // 傳遞給外掛組件的數據
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

可用的插槽遵循 `{module}.{page}.{position}` 模式：

| 插槽 | 位置 |
|------|----------|
| `finance.dashboard.sidebar` | Finance 儀表板側邊欄 |
| `quest.detail.actions` | Quest 詳情頁操作按鈕 |
| `shell.header.right` | 全域頁首右側區域 |
| `shell.sidebar.bottom` | 全域側邊欄底部區域 |

詳情請參閱 [外掛系統](./plugin-system.md)。

## 共用組件 (`src/shared/`)

```
src/shared/
├── components/              可複用 UI 組件
│   ├── Button.tsx
│   ├── Modal.tsx
│   ├── DataTable.tsx
│   └── ...
├── hooks/                   共用 React hooks
│   ├── useAuth.ts
│   ├── useApi.ts
│   └── ...
├── stores/                  全域商店 (認證, 主題)
│   ├── authStore.ts
│   └── themeStore.ts
├── types/                   共用 TypeScript 型別
│   ├── user.ts
│   └── api.ts
└── utils/                   工具函數
```

在任何模組中導入：
```typescript
import { Button } from " @/shared/components/Button";
import { useAuth } from " @/shared/hooks/useAuth";
```

## 建置與部署

單次建置，單一產物：

```bash
cd dashboard && pnpm build   # → 產生包含 index.html + chunks 的 dist/ 目錄
```

生產環境：Nginx 託管 `dist/index.html`。程式碼拆分後的區塊（chunks）會根據路由按需載入。

開發環境：
```bash
cd dashboard && pnpm dev     # → http://localhost:3000
```

Rsbuild 配置會在開發期間將 `/api/*` 代理到核心單體（Core Monolith）。
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
