# Widget Manifest 規格

> AD-4 延伸：Dashboard Widget 系統設計規格

## 概述

Dashboard Canvas 採用 **Widget Manifest + Registry** 模式，讓內部模組和外部系統都能以統一介面註冊 widget。

## WidgetManifest 型別

```typescript
interface WidgetManifest {
  id: string;              // 唯一識別碼，如 "clock", "finance-summary"
  name: string;            // 顯示名稱
  description: string;     // 簡短描述
  icon: string;            // Emoji 或圖示字串
  defaultSize: WidgetSize; // "small" | "medium" | "large" | "wide" | "tall"
  defaultLayout: { w: number; h: number };  // 預設格線尺寸
  minLayout?: { w: number; h: number };     // 最小尺寸
  maxLayout?: { w: number; h: number };     // 最大尺寸
  component: () => Promise<{ default: React.ComponentType<WidgetProps> }>;
  modules?: string[];      // 關聯模組
  tags?: string[];         // 分類標籤
}
```

## WidgetProps 契約

每個 widget 都會收到以下 props：

```typescript
interface WidgetProps {
  containerWidth: number;   // WidgetShell 提供的實際容器寬度 (px)
  containerHeight: number;  // WidgetShell 提供的實際容器高度 (px)
  instanceId: string;       // 唯一實例 ID，用於 localStorage 等
}
```

## 尺寸類別對照

| Size | Grid (w × h) | 適用場景 |
|------|--------------|---------|
| small | 2 × 2 | 時鐘、天氣、計數器 |
| medium | 3 × 3 | 筆記、圖表摘要 |
| large | 4 × 4 | 完整圖表、列表 |
| wide | 4 × 2 | 快捷連結、進度條 |
| tall | 2 × 4 | 時間線、日程 |

## 格線系統

使用 react-grid-layout ResponsiveGridLayout：

| Breakpoint | Columns | 說明 |
|-----------|---------|------|
| lg (≥1200px) | 12 | 桌面 |
| md (≥996px) | 8 | 小桌面 |
| sm (≥768px) | 4 | 平板 |
| xs (<768px) | 2 | 手機 |

Row height: 80px, Margin: 12px

## 註冊方式

### 模組內部 Widget

```typescript
// src/modules/finance/widgets/index.ts
import { registerWidget } from "@/modules/dashboard/registry";

registerWidget({
  id: "finance-summary",
  name: "財務摘要",
  description: "本月收支概覽",
  icon: "💰",
  defaultSize: "medium",
  defaultLayout: { w: 3, h: 3 },
  component: () => import("./FinanceSummaryWidget"),
  modules: ["finance"],
  tags: ["finance", "summary"],
});
```

### 註冊時機

Widget 必須在 app 啟動時透過 side-effect import 註冊：
```typescript
// src/modules/dashboard/registry.ts 底部
// Built-in widgets 在此檔案直接 registerWidget()
// 模組 widgets 由各模組的 widgets/index.ts 匯出
```

## 命名規則

- Widget ID: `{module}-{feature}` 或 `{utility-name}`
  - 模組 widget: `finance-summary`, `memvault-recent`, `taskflow-board`
  - 通用 widget: `clock`, `notes`, `quick-links`
- 禁止重複 ID（registerWidget 會覆蓋）

## WidgetShell 機制

每個 widget 被 WidgetShell 包裹，提供：

1. **ResizeObserver** — 即時追蹤容器尺寸，傳入 `containerWidth`/`containerHeight`
2. **ErrorBoundary** — 單一 widget 錯誤不影響整個 dashboard
3. **Lazy Loading** — 每個 widget 獨立 chunk，按需載入
4. **Header Bar** — 統一顯示 icon + name，編輯模式下顯示刪除按鈕

## 持久化

- Widget 佈局存入 `localStorage` key: `dashboard-widgets`
- 儲存格式: `WidgetInstance[]`（含 layout 座標和尺寸）
- 未來可遷移至 API 做跨裝置同步

## 未來擴展

1. **Widget Settings** — 每個 widget 可宣告 `settingsSchema`，WidgetShell 提供設定面板
2. **Data Fetching** — 標準化 widget 資料來源（API hook / EventBus 訂閱）
3. **Permissions** — Widget 可宣告所需權限，依使用者角色過濾可用 widgets
4. **External Widgets** — iframe 沙箱載入外部 widget（站點外系統）
5. **Widget Marketplace** — 從 plugin registry 安裝第三方 widgets
