# Intel MCP Adapter

> Smart Search / Daily Briefing 的 MCP Server 薄適配層 — 讓 Claude Code 直接操作 Intel Core API。

## 定位

為 Intel 模組提供 MCP 介面，讓 Claude Code 可以直接搜尋報告、查看主題圖譜、觸發每日情報。

## MCP 工具清單

| 工具 | Core API 端點 | 說明 |
|------|--------------|------|
| `intel_search` | `POST /api/intel/search` | 語意搜尋（pgvector） |
| `intel_check` | `POST /api/intel/search/check` | 查重（搜尋前檢查已有相似報告） |
| `intel_save_report` | `POST /api/intel/reports` | 儲存搜尋報告 |
| `intel_get_report` | `GET /api/intel/reports/:id` | 取得報告全文 |
| `intel_list_reports` | `GET /api/intel/reports` | 報告列表（過濾 + 分頁） |
| `intel_ask` | `POST /api/intel/ask` | NL Q&A（向量搜尋輔助） |
| `intel_topics` | `GET /api/intel/topics/graph` | 主題關聯圖 |
| `intel_briefing` | `GET /api/intel/briefings/:date` | 取得指定日期情報 |
| `intel_trigger_briefing` | `POST /api/intel/briefings` | 觸發每日情報產生 |

## 與 smart-search Skill 的關係

```
smart-search Skill (Claude Code)
    │
    ├── 搜尋前：呼叫 intel_check → 查重
    ├── 搜尋中：DeepWiki / Context7 / Perplexity / 社群平台
    └── 搜尋後：呼叫 intel_save_report → 寫入 DB
                                    ↓
                        MCP intel_save_report
                                    ↓
                        POST /api/intel/reports
                                    ↓
                        PostgreSQL + pgvector embedding
```

smart-search Skill 負責**執行搜尋邏輯**，Intel MCP 負責**資料持久化與檢索**。

## 目錄結構（規劃）

```
mcp/intel/
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
