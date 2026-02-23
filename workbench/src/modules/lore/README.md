# Lore 模組（前端）

> KAS Galaxy 視覺化 + 記憶瀏覽器 — Lore 模組的 Workbench UI。

## 頁面規劃

| 路由 | 頁面 | 說明 |
|------|------|------|
| `/lore` | 記憶總覽 | KAS Profile 四維雷達圖 + 最近記憶 |
| `/lore/galaxy` | KS Galaxy | Knowledge-Skill 星系圖（互動式 3D / 2D 視覺化） |
| `/lore/blocks` | 記憶瀏覽器 | 記憶區塊列表（搜尋 + tag 過濾 + 時間線） |
| `/lore/blocks/:id` | 記憶詳情 | 單筆記憶區塊 + 相關記憶推薦 |
| `/lore/domains` | 知識域 | 知識域列表 + 深度分析 |

## Workbench Widgets

| Widget | 尺寸 | 說明 |
|--------|------|------|
| KAS Profile | 2x2 | 四維雷達圖（K/A/S/M） |
| 最近記憶 | 2x1 | 最近 5 筆記憶區塊摘要 |
| Galaxy Mini | 2x2 | 星系圖縮影（僅顯示核心節點） |

## 技術選型

- **Galaxy 視覺化**：Three.js（3D）或 D3.js force-directed（2D），視效能需求選擇
- **狀態管理**：Zustand（module-scoped store）
- **API 通訊**：`/api/lore/*`，使用共用 `useApi` hook

## 目錄結構（規劃）

```
workbench/src/modules/lore/
├── README.md             ← 本文件
├── index.tsx             ← 模組入口（導出路由）
├── pages/
│   ├── Overview.tsx      ← /lore
│   ├── Galaxy.tsx        ← /lore/galaxy
│   ├── BlockList.tsx     ← /lore/blocks
│   ├── BlockDetail.tsx   ← /lore/blocks/:id
│   └── Domains.tsx       ← /lore/domains
├── components/
│   ├── KASRadar.tsx      ← 四維雷達圖
│   ├── GalaxyView.tsx    ← 星系圖視覺化
│   ├── BlockCard.tsx     ← 記憶區塊卡片
│   └── TagCloud.tsx      ← Tag 雲
├── widgets/
│   ├── KASProfileWidget.tsx
│   ├── RecentBlocksWidget.tsx
│   └── GalaxyMiniWidget.tsx
├── hooks/
│   └── useLore.ts        ← Lore API hooks
├── stores/
│   └── loreStore.ts      ← Zustand store
├── api/
│   └── client.ts         ← Lore API client
└── types/
    └── index.ts          ← Lore types
```
