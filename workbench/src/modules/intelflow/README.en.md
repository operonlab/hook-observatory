---
source_hash: b493fccc
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Intelflow Module (Frontend)

> Research Hub + Daily Briefing — The Workbench UI for the Intelflow module.

## Page Planning

| Route | Page | Description |
|------|------|-------------|
| `/intelflow` | Intelligence Overview | Latest reports + Trend chart + Topic graph entry point |
| `/intelflow/reports` | Report List | Full-text search + Semantic search + tag/topic filtering |
| `/intelflow/reports/:id` | Report Details | Markdown rendering + Source links + Related reports |
| `/intelflow/topics` | Topic Graph | Force-directed graph visualization + Topic drill-down |
| `/intelflow/briefings` | Daily Briefings | Briefing list (date selection) |
| `/intelflow/briefings/:date` | Briefing Details | Three-analyst analysis + Debate conclusion |

## Workbench Widgets

| Widget | Size | Description |
|--------|------|-------------|
| Latest Reports | 2x1 | Titles of the last 5 reports + Date |
| Trend Chart | 2x1 | Time-series chart of report volume |
| Daily Briefing | 2x2 | Today's briefing summary (five domains) |

## Designs Retained from V1

### Three-Analyst Debate Interface

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

### Topic Graph

- Node: Report topic (size = number of reports)
- Edge: Topic co-occurrence relationship (thickness = strength of association)
- Clicking a node → Expands the list of related reports

## Technology Stack

- **Topic Graph**: D3.js force-directed graph (recreating `/topics/graph` from V1 research_report)
- **Markdown Rendering**: react-markdown + remark-gfm
- **Search**: Toggle between full-text search and semantic search
- **State Management**: Zustand (module-scoped store)

## Directory Structure (Planned)

```
workbench/src/modules/intelflow/
├── README.md             ← This document
├── index.tsx             ← Module entry point (exports routes)
├── pages/
│   ├── Overview.tsx      ← /intelflow
│   ├── ReportList.tsx    ← /intelflow/reports
│   ├── ReportDetail.tsx  ← /intelflow/reports/:id
│   ├── TopicGraph.tsx    ← /intelflow/topics
│   ├── BriefingList.tsx  ← /intelflow/briefings
│   └── BriefingDetail.tsx ← /intelflow/briefings/:date
├── components/
│   ├── ReportCard.tsx    ← Report card
│   ├── TopicMap.tsx      ← Topic graph visualization
│   ├── AnalystPanel.tsx  ← Three-analyst comparison panel
│   ├── SearchBar.tsx     ← Full-text + semantic search toggle
│   └── SourceList.tsx    ← Source link list
├── widgets/
│   ├── LatestReportsWidget.tsx
│   ├── TrendChartWidget.tsx
│   └── DailyBriefingWidget.tsx
├── hooks/
│   └── useIntelflow.ts   ← Intelflow API hooks
├── stores/
│   └── intelflowStore.ts ← Zustand store
├── api/
│   └── client.ts         ← Intelflow API client
└── types/
    └── index.ts          ← Intelflow types
```
