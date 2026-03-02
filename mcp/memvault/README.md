# Memvault MCP Adapter

> Memvault 的 MCP Server 薄適配層 — 讓 Claude Code 直接操作 Memvault Core API。

## 定位

Memvault 的 9 個 MCP 工具，作為 Core API 的薄適配器。

## MCP 工具清單

| 工具 | Core API 端點 | 說明 |
|------|--------------|------|
| `memvault_recall` | `POST /api/memvault/recall` | 混合搜尋（keyword + vector + RRF） |
| `memvault_extract` | `POST /api/memvault/extract` | 手動提煉 session transcript |
| `memvault_search_tags` | `GET /api/memvault/blocks?tags=...` | Tag 精確篩選 |
| `memvault_memory_stats` | `GET /api/memvault/stats` | 統計（block 數、tag 分佈、embedding 覆蓋率） |
| `memvault_promote` | `POST /api/memvault/domains/promote` | 高頻 tag → 知識域晉升 |
| `memvault_memory_edit` | `PUT/DELETE /api/memvault/blocks/:id` | 檢視/修改/刪除記憶區塊 |
| `memvault_sync_embeddings` | `POST /api/memvault/embeddings/sync` | 批量同步 embeddings |
| `memvault_profile` | `GET /api/memvault/profile` | 查看 Profile Score |
| `memvault_skill_search` | `GET /api/memvault/skills/search` | 搜尋已安裝 skills |

## MCP Resources

| URI | Core API 端點 | 說明 |
|-----|--------------|------|
| `memvault://memories/recent` | `GET /api/memvault/blocks?days=14` | 最近 14 天記憶 |
| `memvault://knowledge/domains` | `GET /api/memvault/domains` | 所有知識域 |

## 架構

```
Claude Code / Claude Squad
    │
    ▼
mcp/memvault/ (MCP Server, TypeScript)
    │  每個工具 = 一個 HTTP call to Core API
    ▼
core/src/modules/memvault/ (FastAPI, Python)
    │
    ▼
PostgreSQL (schema: memvault) + pgvector
```

## 目錄結構（規劃）

```
mcp/memvault/
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

- **工具已重命名**：所有工具從 `kas_*` 重命名為 `memvault_*`，Claude Code 的 settings/hooks 需同步更新
- **漸進切換**：先在 Core 建立 API → MCP Server 切換端點 → 驗證 → 退役舊 MCP Server
- **Hook 相容**：SessionEnd hook（`extract-async.sh`）最終改為 `curl POST /api/memvault/extract`
