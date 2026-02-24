---
source_hash: f8622eb9
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Memvault MCP Adapter

> A thin adapter layer for the KAS Memvault MCP Server — allowing Claude Code to directly operate the Memvault Core API.

## Positioning

Refactor the 9 tools of the existing KAS Memory MCP Server (`~/Claude/projects/kas-memory/mcp-server/`) into thin adapters for the Core API. Tool names and behaviors will remain consistent, and the backend will switch from direct file reading/writing to calling the Core API.

## MCP Tool List

| Tool | Core API Endpoint | Description |
|------|--------------|------|
| `kas_recall` | `POST /api/memvault/recall` | Hybrid search (keyword + vector + RRF) |
| `kas_extract` | `POST /api/memvault/extract` | Manually extract session transcript |
| `kas_search_tags` | `GET /api/memvault/blocks?tags=...` | Precise filtering by tags |
| `kas_memory_stats` | `GET /api/memvault/stats` | Statistics (block count, tag distribution, embedding coverage) |
| `kas_promote` | `POST /api/memvault/domains/promote` | High-frequency tags → Promotion to knowledge domain |
| `kas_memory_edit` | `PUT/DELETE /api/memvault/blocks/:id` | View/modify/delete memory blocks |
| `kas_sync_embeddings` | `POST /api/memvault/embeddings/sync` | Batch sync embeddings |
| `kas_profile` | `GET /api/memvault/profile` | View KAS Profile |
| `kas_skill_search` | `GET /api/memvault/skills/search` | Search installed skills |

## MCP Resources

| URI | Core API Endpoint | Description |
|-----|--------------|------|
| `kas://memories/recent` | `GET /api/memvault/blocks?days=14` | Memories from the last 14 days |
| `kas://knowledge/domains` | `GET /api/memvault/domains` | All knowledge domains |

## Architecture

```
Claude Code / Claude Squad
    │
    ▼
mcp/memvault/ (MCP Server, TypeScript)
    │  Each tool = one HTTP call to Core API
    ▼
core/src/modules/memvault/ (FastAPI, Python)
    │
    ▼
PostgreSQL (schema: memvault) + pgvector
```

## Directory Structure (Plan)

```
mcp/memvault/
├── README.md           ← This document
├── package.json
├── tsconfig.json
└── src/
    ├── index.ts        ← MCP Server entry point
    └── tools/          ← Implementation of each tool (thin adapter, directly fetches Core API)
        ├── recall.ts
        ├── extract.ts
        ├── search-tags.ts
        ├── stats.ts
        ├── promote.ts
        ├── edit.ts
        ├── sync-embeddings.ts
        ├── profile.ts
        └── skill-search.ts
```

## Migration Notes

- **Tool names remain unchanged**: Names like `kas_recall` will remain consistent to avoid requiring simultaneous changes to Claude Code's settings/hooks.
- **Gradual switchover**: First, create the API in Core, then switch the MCP Server endpoint, verify, and finally decommission the old MCP Server.
- **Hook compatibility**: The SessionEnd hook (`extract-async.sh`) will eventually be changed to `curl POST /api/memvault/extract`.
