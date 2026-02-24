# Intelflow MCP Adapter

> Smart Search / Daily Briefing 的 MCP Server 薄適配層 — 讓 Claude Code 直接操作 Intelflow Core API。

## 定位

為 Intelflow 模組提供 MCP 介面，讓 Claude Code 可以直接搜尋報告、查看主題圖譜、觸發每日情報。

## MCP 工具清單

| 工具 | Core API 端點 | 說明 |
|------|--------------|------|
| `intelflow_search` | `POST /api/intelflow/search` | 語意搜尋（pgvector） |
| `intelflow_check` | `POST /api/intelflow/search/check` | 查重（搜尋前檢查已有相似報告） |
| `intelflow_save_report` | `POST /api/intelflow/reports` | 儲存搜尋報告 |
| `intelflow_get_report` | `GET /api/intelflow/reports/:id` | 取得報告全文 |
| `intelflow_list_reports` | `GET /api/intelflow/reports` | 報告列表（過濾 + 分頁） |
| `intelflow_ask` | `POST /api/intelflow/ask` | NL Q&A（向量搜尋輔助） |
| `intelflow_topics` | `GET /api/intelflow/topics/graph` | 主題關聯圖 |
| `intelflow_briefing` | `GET /api/intelflow/briefings/:date` | 取得指定日期情報 |
| `intelflow_trigger_briefing` | `POST /api/intelflow/briefings` | 觸發每日情報產生 |

## 與 smart-search Skill 的關係

```
smart-search Skill (Claude Code)
    │
    ├── 搜尋前：呼叫 intelflow_check → 查重
    ├── 搜尋中：DeepWiki / Context7 / Perplexity / 社群平台
    └── 搜尋後：呼叫 intelflow_save_report → 寫入 DB
                                    ↓
                        MCP intelflow_save_report
                                    ↓
                        POST /api/intelflow/reports
                                    ↓
                        PostgreSQL + pgvector embedding
```

smart-search Skill 負責**執行搜尋邏輯**，Intelflow MCP 負責**資料持久化與檢索**。

## 目錄結構（規劃）

```
mcp/intelflow/
├── README.md           ← 本文件
├── package.json
├── tsconfig.json
└── src/
    ├── index.ts        ← MCP Server 入口
    └── tools/
        ├── search.ts
        ├── check.ts
        ├── reports.ts
        ├── ask.ts
        ├── topics.ts
        └── briefing.ts
```
