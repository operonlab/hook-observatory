# Four-Tier Data Lifecycle Architecture

> **Status**: 📐 DESIGN PROPOSAL（未實作）
> **Current state (2026-04)**:
> - ✅ Archive 表存在（Hot → Cold 二層）
> - ❌ tier_config.py 未建立
> - ❌ Frozen tier + S3 未實作
> - ❌ Lifecycle scripts Phase 0-3 未啟動

## Context

Workshop 現有 Hot-Cold 二層資料分層（主表 + archive 表 + S3）面臨中間灰色地帶：
資料要嘛在昂貴的 Hot tier（HNSW + GIN），要嘛在搜尋體驗極差的 Cold tier（ILIKE only）。
同時缺乏法律追溯保留（Frozen tier）的設計，未來 finance、compliance 等模組有明確需求。

**目標**：升級為 Hot-Warm-Cold-Frozen 四層架構，先設計完整、保留彈性，漸進實作。

## Decision

採用 **同表不同索引** 的 Warm 策略 + 獨立 Frozen 表，以最小侵入性升級現有架構。

### Four-Tier Definition

```
Hot ──────► Warm ──────► Cold ──────► Frozen
(主表+HNSW)  (主表-HNSW)  (archive表)  (frozen表+S3)
  最快搜尋     文字搜尋仍快   ID/日期查詢    法律追溯保留
```

### Per-Module Tier Boundaries

| Module | Hot | Warm | Cold | Frozen | 設計依據 |
|--------|-----|------|------|--------|---------|
| **memvault** | < 14d | 14d ~ 6m | 6m ~ 3y | 3y+ | 記憶衰減快，對齊 Mem0 的 7-30d session 窗口 |
| **intelflow** | < 180d | 180d ~ 2y | 2y ~ 5y | 5y+ | 情報報告有長期參考價值 |
| **finance** | < 90d | 90d ~ 1y | 1y ~ 5y | 5y+ | 台灣稅法核定期 5 年 |
| **taskflow** | < 30d | 30d ~ 1y | 1y ~ 5y | 5y+ | 任務完成後快速降溫 |
| **ideagraph** | < 90d | 90d ~ 2y | 2y ~ 5y | 5y+ | 知識圖譜有持久價值 |

### Index Strategy Per Tier

| Tier | Vector (HNSW) | Text (GIN) | Structured (B-tree) | Content 位置 |
|------|--------------|------------|---------------------|-------------|
| **Hot** | HNSW partial (窗口=Hot天數) | GIN tags + tsvector | B-tree type/date | PostgreSQL 主表 |
| **Warm** | 無（embedding sub-table 已清理） | GIN tags | B-tree type/date | PostgreSQL 主表 |
| **Cold** | 無 | GIN tags (archive) | B-tree date/archived | PostgreSQL archive 表（大 content → S3） |
| **Frozen** | 無 | GIN tags (frozen) | B-tree date/frozen | S3（全量）+ PG frozen 表（metadata only） |

## Alternatives Considered

### A. 獨立 Warm 表（Rejected）
- 需要新表 `blocks_warm`，資料從主表移至 warm 表
- 增加 query routing 複雜度（3 張表 vs 2 張表）
- 與現有 partial HNSW 模式斷裂，需要大量遷移邏輯

### B. PostgreSQL Partitioning（Rejected）
- Range partition by `created_at` 需要固定邊界（不適合 per-module 不同）
- Partition pruning 只在 WHERE clause 包含 partition key 時有效
- 現有 archive 表結構與 partition 不相容，改造成本太高

### C. DB Trigger 自動過渡（Rejected）
- 最自動但最難 debug
- Frozen tier 需要 S3 upload，不適合在 trigger 中做 I/O
- 違反「腳本可觀察、可重試」原則

## Design Details

### 1. Tier Configuration

集中配置在 `core/src/shared/tier_config.py`：

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class TierThreshold:
    hot_days: int
    warm_days: int
    cold_days: int
    frozen_retention_years: int = 5  # legal minimum

# Per-module configuration
TIER_THRESHOLDS: dict[str, TierThreshold] = {
    "memvault":  TierThreshold(hot_days=14,  warm_days=180,  cold_days=1095, frozen_retention_years=5),
    "intelflow": TierThreshold(hot_days=180, warm_days=730,  cold_days=1825, frozen_retention_years=5),
    "finance":   TierThreshold(hot_days=90,  warm_days=365,  cold_days=1825, frozen_retention_years=5),
    "taskflow":  TierThreshold(hot_days=30,  warm_days=365,  cold_days=1825, frozen_retention_years=5),
    "ideagraph": TierThreshold(hot_days=90,  warm_days=730,  cold_days=1825, frozen_retention_years=5),
}

def get_tier(module: str, age_days: int) -> str:
    t = TIER_THRESHOLDS[module]
    if age_days <= t.hot_days:
        return "hot"
    elif age_days <= t.warm_days:
        return "warm"
    elif age_days <= t.cold_days:
        return "cold"
    else:
        return "frozen"
```

### 2. Frozen Table Schema

每個有歸檔需求的模組新增 `_frozen` 表：

```sql
-- memvault.blocks_frozen
CREATE TABLE memvault.blocks_frozen (
    id              UUID PRIMARY KEY,
    space_id        VARCHAR(64) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    archived_at     TIMESTAMPTZ NOT NULL,
    frozen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    block_type      VARCHAR(20),
    tags            VARCHAR[] DEFAULT '{}',
    summary         TEXT,               -- LLM 自動產生的摘要
    s3_uri          TEXT NOT NULL,       -- s3://workshop-frozen/memvault/{id}.json.zst
    content_hash    VARCHAR(64) NOT NULL,-- SHA-256 of original content
    content_size    INTEGER,            -- original content bytes
    created_by      VARCHAR(64)
);

CREATE INDEX idx_bf_space_created ON memvault.blocks_frozen (space_id, created_at);
CREATE INDEX idx_bf_tags ON memvault.blocks_frozen USING gin (tags);
CREATE INDEX idx_bf_frozen ON memvault.blocks_frozen (frozen_at);

-- intelflow.reports_frozen (同構)
-- intelflow.briefings_frozen (同構)
-- finance.transactions_frozen (同構，欄位微調)
```

### 3. S3 Storage Layout (Frozen)

```
s3://workshop-frozen/
├── memvault/
│   └── {yyyy}/{mm}/{id}.json.zst     # zstd compressed JSON
├── intelflow/
│   ├── reports/{yyyy}/{mm}/{id}.json.zst
│   └── briefings/{yyyy}/{mm}/{id}.json.zst
└── finance/
    └── {yyyy}/{mm}/{id}.json.zst

# JSON 格式（完整 row snapshot）
{
    "id": "uuid",
    "content": "original full content",
    "metadata": { /* all original columns */ },
    "frozen_at": "2029-03-02T00:00:00Z",
    "schema_version": 1
}
```

### 4. Lifecycle Script (Enhanced archive_cold_data.py)

```
Phase 0: 驗證 (dry-run default)
  - 計算每個模組各 tier 的候選筆數
  - 預估 S3 upload 量
  - 輸出報表供確認

Phase 1: Hot → Warm (DELETE embeddings only)
  FOR module IN [memvault, intelflow, ...]:
    DELETE FROM {module}_embeddings
    WHERE {entity}_id IN (
      SELECT id FROM {module}.{entity}
      WHERE created_at < now() - interval '{hot_days} days'
    )
  -- Row 留在主表，只是失去 HNSW 搜尋能力

Phase 2: Warm → Cold (INSERT archive + DELETE main)
  FOR module IN [memvault, intelflow, ...]:
    candidates = SELECT * FROM {module}.{entity}
      WHERE created_at < now() - interval '{warm_days} days'

    FOR row IN candidates:
      IF row.content_size > 10240:  # COLD-BLOB
        upload content to S3 (workshop-archive bucket)
        row.content = f"s3://workshop-archive/..."
      INSERT INTO {module}.{entity}_archive VALUES (row)
      DELETE FROM {module}.{entity} WHERE id = row.id

Phase 3: Cold → Frozen (NEW)
  FOR module IN [memvault, intelflow, ...]:
    candidates = SELECT * FROM {module}.{entity}_archive
      WHERE created_at < now() - interval '{cold_days} days'

    FOR row IN candidates:
      # 1. 完整 snapshot upload to frozen bucket
      full_json = serialize_full_row(row)
      compressed = zstd_compress(full_json)
      s3_uri = upload_to_s3("workshop-frozen", compressed)
      content_hash = sha256(full_json)

      # 2. 自動摘要（如果沒有）
      summary = row.summary or generate_summary_via_llm(row.content)

      # 3. Insert frozen metadata
      INSERT INTO {module}.{entity}_frozen (
        id, space_id, created_at, archived_at, frozen_at,
        block_type, tags, summary, s3_uri, content_hash, content_size
      ) VALUES (...)

      # 4. Cleanup
      DELETE FROM {module}.{entity}_archive WHERE id = row.id
      # If content was in workshop-archive S3, optionally delete (or keep for audit trail)

Phase 4: 法律過期清理 (Optional, manual only)
  -- Frozen 資料超過 retention_years 後 CAN be deleted
  -- 但不自動刪除，需要 explicit --purge-expired flag
  -- 刪除前輸出完整 manifest 供審計
```

### 5. Query Routing

```python
async def search(query: str, *, include_warm=True, include_cold=False, include_frozen=False):
    results = []

    # Tier 1: Hot — vector search (HNSW)
    hot_results = await semantic_search_via_subtable(query, max_age_days=threshold.hot_days)
    results.extend(hot_results)

    # Tier 2: Warm — text search on main table (GIN + ILIKE, no vector)
    if include_warm and len(results) < top_k:
        warm_results = await text_search_main_table(
            query, min_age_days=threshold.hot_days, max_age_days=threshold.warm_days
        )
        for r in warm_results:
            r.score *= 0.7  # warm penalty
        results.extend(warm_results)

    # Tier 3: Cold — text search on archive table
    if include_cold and len(results) < top_k:
        cold_results = await text_search_archive(query, module)
        for r in cold_results:
            r.score *= 0.3  # cold penalty
        results.extend(cold_results)

    # Tier 4: Frozen — tag match + summary search only
    if include_frozen and len(results) < top_k:
        frozen_results = await tag_search_frozen(query, module)
        for r in frozen_results:
            r.score *= 0.05  # frozen penalty, content needs S3 fetch
            r.needs_thaw = True  # flag: full content requires async S3 fetch
        results.extend(frozen_results)

    return sorted(results, key=lambda r: r.score, reverse=True)[:top_k]
```

**Search API 預設行為**：
- `GET /api/memvault/search` → Hot + Warm（最常用）
- `GET /api/memvault/search?include_archived=true` → Hot + Warm + Cold
- `GET /api/memvault/search?include_frozen=true` → 全部四層

### 6. Frozen Content Thaw（解凍 API）

```python
@router.get("/{module}/frozen/{id}/thaw")
async def thaw_frozen_content(module: str, id: UUID):
    """Fetch full content from S3 for a frozen item. Async, may take 1-3s."""
    frozen = await get_frozen_metadata(module, id)
    if not frozen:
        raise NotFoundError(f"Frozen item {id} not found")

    content = await storage.download_and_decompress(frozen.s3_uri)

    # Verify integrity
    if sha256(content) != frozen.content_hash:
        raise IntegrityError(f"Content hash mismatch for {id}")

    return {"id": id, "content": json.loads(content), "tier": "frozen"}
```

### 7. Partial HNSW Auto-Reindex

修正現有痛點：partial HNSW index 不會自動縮小。

```sql
-- 新增 pg_cron job（或在 lifecycle script 中執行）
-- 每週 REINDEX 一次，確保 partial index 只包含 Hot 窗口內的資料
REINDEX INDEX CONCURRENTLY memvault.idx_blocks_embedding_recent;
REINDEX INDEX CONCURRENTLY intelflow.idx_reports_embedding_recent;
```

建議加入 lifecycle script 的 Phase 0（驗證階段）。

## Implementation Phases

### Phase 0: Config + Foundation（無 DB 變更）
- [ ] 新增 `core/src/shared/tier_config.py`（TierThreshold 配置）
- [ ] 重構 `archive_cold_data.py` 讀取 tier_config
- [ ] 新增 partial HNSW reindex 到 lifecycle script
- [ ] 修復 COLD-BLOB `s3://` URI 搜尋問題（過濾 s3:// 前綴的 rows）

### Phase 1: Hot → Warm 過渡（最小變更）
- [ ] 修改 lifecycle script：Phase 1 清理 Hot 窗口外的 embedding sub-table
- [ ] 修改 partial HNSW window 從 90d → 14d（memvault）、180d（intelflow 不變）
- [ ] 修改 search API：Warm 搜尋走 GIN text search（score × 0.7）
- [ ] API 預設行為改為 Hot + Warm

### Phase 2: Frozen 層（新表 + S3）
- [ ] Alembic migration：新增 `_frozen` 表（memvault, intelflow）
- [ ] S3 bucket 建立：`workshop-frozen`
- [ ] Lifecycle script Phase 3：Cold → Frozen 過渡邏輯
- [ ] LLM 摘要生成（frozen 時觸發）
- [ ] Thaw API endpoint

### Phase 3: 全模組覆蓋
- [ ] Finance, taskflow, ideagraph 的 frozen 表
- [ ] Per-module tier config 微調
- [ ] Frozen content integrity verification job
- [ ] 監控：各 tier 資料量 dashboard

### Phase 4: 法律追溯工具（未來）
- [ ] Frozen data audit trail API
- [ ] Retention policy enforcement
- [ ] 過期清理 workflow（manual + approval）

## Open Questions

1. **LLM 摘要品質** — Frozen 時的自動摘要用哪個模型？本地 Ollama 還是 Cloud API？
2. **S3 加密** — Frozen 資料是否需要 server-side encryption（法律合規）？
3. **跨模組統一搜尋** — 未來是否需要一個統一的 search API 跨所有模組的所有 tier？
4. **Briefing S3 支援** — 現有 briefing archive 不支援 COLD-BLOB，是否在此次一併修復？
5. **REINDEX 頻率** — 每日 vs 每週 REINDEX partial HNSW？

## Appendix: Query Routing Matrix

| Query Type | Hot | Warm | Cold | Frozen |
|-----------|-----|------|------|--------|
| Semantic search (default) | HNSW vector | - | - | - |
| Semantic + warm | HNSW vector | GIN text (×0.7) | - | - |
| Text search | GIN + ILIKE | GIN + ILIKE | - | - |
| Text search + archived | GIN + ILIKE | GIN + ILIKE | ILIKE (×0.3) | summary ILIKE (×0.05) |
| Get by ID | PK lookup | PK lookup | PK on archive | PK on frozen + S3 |
| Filter by tag | GIN | GIN | GIN on archive | GIN on frozen |

## Appendix: Storage Cost Estimate (per 1000 items/month)

| Tier | PG Storage | HNSW Overhead | S3 Cost | Est. Monthly |
|------|-----------|---------------|---------|-------------|
| Hot | 0.5 GB | ~30% | - | $15-25 |
| Warm | 0.4 GB | 0% | - | $8-12 |
| Cold | 0.3 GB | - | $0.02/GB | $3-5 |
| Frozen | 0.01 GB (metadata) | - | $0.004/GB | $0.50-1 |
