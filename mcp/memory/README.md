# Memory MCP Adapter

> KAS Memory 的 MCP Server 薄適配層 — 讓 Claude Code 直接操作 Memory Core API。

## 定位

將現有 KAS Memory MCP Server（`~/Claude/projects/kas-memory/mcp-server/`）的 9 個工具重構為 Core API 的薄適配器。工具名稱和行為保持一致，後端從直接讀寫檔案改為呼叫 Core API。

## MCP 工具清單

| 工具 | Core API 端點 | 說明 |
|------|--------------|------|
| `kas_recall` | `POST /api/memory/recall` | 混合搜尋（keyword + vector + RRF） |
| `kas_extract` | `POST /api/memory/extract` | 手動提煉 session transcript |
| `kas_search_tags` | `GET /api/memory/blocks?tags=...` | Tag 精確篩選 |
| `kas_memory_stats` | `GET /api/memory/stats` | 統計（block 數、tag 分佈、embedding 覆蓋率） |
| `kas_promote` | `POST /api/memory/domains/promote` | 高頻 tag → 知識域晉升 |
| `kas_memory_edit` | `PUT/DELETE /api/memory/blocks/:id` | 檢視/修改/刪除記憶區塊 |
| `kas_sync_embeddings` | `POST /api/memory/embeddings/sync` | 批量同步 embeddings |
| `kas_profile` | `GET /api/memory/profile` | 查看 KAS Profile |
| `kas_skill_search` | `GET /api/memory/skills/search` | 搜尋已安裝 skills |

## MCP Resources

| URI | Core API 端點 | 說明 |
|-----|--------------|------|
| `kas://memories/recent` | `GET /api/memory/blocks?days=14` | 最近 14 天記憶 |
| `kas://knowledge/domains` | `GET /api/memory/domains` | 所有知識域 |

## 架構

```
Claude Code / Claude Squad
    │
    ▼
mcp/memory/ (MCP Server, TypeScript)
    │  每個工具 = 一個 HTTP call to Core API
    ▼
core/src/modules/memory/ (FastAPI, Python)
    │
    ▼
PostgreSQL (schema: memory) + pgvector
```

## 目錄結構（規劃）

```
mcp/memory/
├── README.md           ← 本文件
├── package.json
├── tsconfig.json
└── src/
    ├── index.ts        ← MCP Server 入口
    └── tools/          ← 各工具實作（薄適配，直接 fetch Core API）
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

## 遷移注意事項

- **工具名稱不變**：`kas_recall` 等名稱保持一致，避免 Claude Code 的 settings/hooks 需要同步修改
- **漸進切換**：先在 Core 建立 API → MCP Server 切換端點 → 驗證 → 退役舊 MCP Server
- **Hook 相容**：SessionEnd hook（`extract-async.sh`）最終改為 `curl POST /api/memory/extract`
