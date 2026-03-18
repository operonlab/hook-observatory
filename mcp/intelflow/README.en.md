---
source_hash: 477c6a07
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Intelflow MCP Adapter

> A thin MCP Server adapter layer for Smart Search / Daily Briefing — allowing Claude Code to directly operate on the Intelflow Core API.

## Role

Provides an MCP interface for the Intelflow module, allowing Claude Code to directly search reports, view the topic graph, and trigger daily briefings.

## MCP Tool List

| Tool | Core API Endpoint | Description |
|------|--------------|------|
| `intelflow_search` | `POST /api/intelflow/search` | Semantic search (Qdrant) |
| `intelflow_check` | `POST /api/intelflow/search/check` | Deduplication (check for existing similar reports before searching) |
| `intelflow_save_report` | `POST /api/intelflow/reports` | Save search report |
| `intelflow_get_report` | `GET /api/intelflow/reports/:id` | Get full report text |
| `intelflow_list_reports` | `GET /api/intelflow/reports` | Report list (filtering + pagination) |
| `intelflow_ask` | `POST /api/intelflow/ask` | NL Q&A (vector search assisted) |
| `intelflow_topics` | `GET /api/intelflow/topics/graph` | Topic relationship graph |
| `intelflow_briefing` | `GET /api/intelflow/briefings/:date` | Get briefing for a specific date |
| `intelflow_trigger_briefing` | `POST /api/intelflow/briefings` | Trigger daily briefing generation |

## Relationship with smart-search Skill

```
smart-search Skill (Claude Code)
    │
    ├── Before search: call intelflow_check → Deduplication
    ├── During search: DeepWiki / Context7 / Perplexity / Social platforms
    └── After search: call intelflow_save_report → Write to DB
                                    ↓
                        MCP intelflow_save_report
                                    ↓
                        POST /api/intelflow/reports
                                    ↓
                        PostgreSQL + Qdrant embedding
```

The smart-search Skill is responsible for **executing the search logic**, while the Intelflow MCP is responsible for **data persistence and retrieval**.

## Directory Structure (Plan)

```
mcp/intelflow/
├── README.md           ← This document
├── package.json
├── tsconfig.json
└── src/
    ├── index.ts        ← MCP Server entry point
    └── tools/
        ├── search.ts
        ├── check.ts
        ├── reports.ts
        ├── ask.ts
        ├── topics.ts
        └── briefing.ts
```
