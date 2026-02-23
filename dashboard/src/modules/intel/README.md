# Intel 模組（前端）

> Research Hub + Daily Briefing — Intel 模組的 Dashboard UI。

## 頁面規劃

| 路由 | 頁面 | 說明 |
|------|------|------|
| `/intel` | 情報總覽 | 最新報告 + 趨勢圖 + 主題圖譜入口 |
| `/intel/reports` | 報告列表 | 全文搜尋 + 語意搜尋 + tag/topic 過濾 |
| `/intel/reports/:id` | 報告詳情 | Markdown 渲染 + 來源連結 + 相關報告 |
| `/intel/topics` | 主題圖譜 | Force-directed graph 視覺化 + 主題鑽取 |
| `/intel/briefings` | 每日情報 | 情報列表（日期選擇） |
| `/intel/briefings/:date` | 情報詳情 | 三分析師分析 + 辯論結論 |

## Dashboard Widgets

| Widget | 尺寸 | 說明 |
|--------|------|------|
| 最新報告 | 2x1 | 最近 5 篇報告標題 + 日期 |
| 趨勢圖 | 2x1 | 報告數量時序圖 |
| 每日情報 | 2x2 | 今日情報摘要（五領域） |

## 從 V1 保留的設計

### 三分析師辯論介面

```
┌─────────────────────────────────────────────────┐
│  每日情報 — 2026-02-23 — Finance                 │
├────────────┬────────────┬───────────────────────┤
│  Claude    │  Codex     │  Gemini               │
│  ────────  │  ────────  │  ────────             │
│  Top 5     │  Top 5     │  Top 5                │
│  趨勢排序   │  趨勢排序   │  趨勢排序              │
│            │            │                       │
│  推薦報導   │  推薦報導   │  推薦報導              │
│  Top 10    │  Top 10    │  Top 10               │
│            │            │                       │
│  極端判定 ⚠ │  極端判定 ✓ │  極端判定 ⚠            │
│  被忽略角度  │  被忽略角度  │  被忽略角度             │
├────────────┴────────────┴───────────────────────┤
│  交叉辯論結論                                     │
│  ──────────                                      │
│  Claude 質疑 Gemini 過度樂觀...                    │
│  Codex 認為 Claude 低估了...                       │
│  共識：...                                        │
└─────────────────────────────────────────────────┘
```

### 主題圖譜

- 節點：報告主題（大小 = 報告數量）
- 邊：主題共現關係（粗細 = 關聯強度）
- 點擊節點 → 展開相關報告列表

## 技術選型

- **主題圖譜**：D3.js force-directed graph（復刻 V1 research_report 的 `/topics/graph`）
- **Markdown 渲染**：react-markdown + remark-gfm
- **搜尋**：全文搜尋 + 語意搜尋雙模式切換
- **狀態管理**：Zustand（module-scoped store）

## 目錄結構（規劃）

```
dashboard/src/modules/intel/
├── README.md             ← 本文件
├── index.tsx             ← 模組入口（導出路由）
├── pages/
│   ├── Overview.tsx      ← /intel
│   ├── ReportList.tsx    ← /intel/reports
│   ├── ReportDetail.tsx  ← /intel/reports/:id
│   ├── TopicGraph.tsx    ← /intel/topics
│   ├── BriefingList.tsx  ← /intel/briefings
│   └── BriefingDetail.tsx ← /intel/briefings/:date
├── components/
│   ├── ReportCard.tsx    ← 報告卡片
│   ├── TopicMap.tsx      ← 主題圖譜視覺化
│   ├── AnalystPanel.tsx  ← 三分析師對比面板
│   ├── SearchBar.tsx     ← 全文 + 語意搜尋切換
│   └── SourceList.tsx    ← 來源連結列表
├── widgets/
│   ├── LatestReportsWidget.tsx
│   ├── TrendChartWidget.tsx
│   └── DailyBriefingWidget.tsx
├── hooks/
│   └── useIntel.ts       ← Intel API hooks
├── stores/
│   └── intelStore.ts     ← Zustand store
├── api/
│   └── client.ts         ← Intel API client
└── types/
    └── index.ts          ← Intel types
```
