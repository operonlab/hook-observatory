# Scout MCP Adapter

> Smart Search / Daily Briefing 的 MCP Server 薄適配層 — 讓 Claude Code 直接操作 Scout Core API。

## 定位

為 Scout 模組提供 MCP 介面，讓 Claude Code 可以直接搜尋報告、查看主題圖譜、觸發每日情報。

## MCP 工具清單

| 工具 | Core API 端點 | 說明 |
|------|--------------|------|
| `scout_search` | `POST /api/scout/search` | 語意搜尋（pgvector） |
| `scout_check` | `POST /api/scout/search/check` | 查重（搜尋前檢查已有相似報告） |
| `scout_save_report` | `POST /api/scout/reports` | 儲存搜尋報告 |
| `scout_get_report` | `GET /api/scout/reports/:id` | 取得報告全文 |
| `scout_list_reports` | `GET /api/scout/reports` | 報告列表（過濾 + 分頁） |
| `scout_ask` | `POST /api/scout/ask` | NL Q&A（向量搜尋輔助） |
| `scout_topics` | `GET /api/scout/topics/graph` | 主題關聯圖 |
| `scout_briefing` | `GET /api/scout/briefings/:date` | 取得指定日期情報 |
| `scout_trigger_briefing` | `POST /api/scout/briefings` | 觸發每日情報產生 |

## 與 smart-search Skill 的關係

```
smart-search Skill (Claude Code)
    │
    ├── 搜尋前：呼叫 scout_check → 查重
    ├── 搜尋中：DeepWiki / Context7 / Perplexity / 社群平台
    └── 搜尋後：呼叫 scout_save_report → 寫入 DB
                                    ↓
                        MCP scout_save_report
                                    ↓
                        POST /api/scout/reports
                                    ↓
                        PostgreSQL + pgvector embedding
```

smart-search Skill 負責**執行搜尋邏輯**，Scout MCP 負責**資料持久化與檢索**。

## 目錄結構（規劃）

```
mcp/scout/
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
