# DocVault KG Layer — Phase 2-4 實作計畫

Issue: JonesHong/workshop#33
Branch: `feature/docvault-kg-ops`
基於: HiRAG (EMNLP 2025) 三層架構 + libs/kg-ops 共享庫

## 架構概覽

```
Query → L2 Community Summaries → L1 Community Members → L0 Triples → Chunks
                                                                      ↕
Upload → Chunks → ChunkEntityOp(L0) → CommunityIndexOp(L1+L2) → Qdrant
```

三層 KG 搜尋解決 Q4/Q6 散佈 chunk 回收不足問題：
- L0: chunk 級 entity + triple（哪些 chunk 提到同一個 entity）
- L1: Leiden 社群聚類（哪些 entity 屬於同一主題）
- L2: 社群摘要（主題級語義搜尋入口）

## Phase 2: ChunkEntityOp — Entity Extraction

### 2a: KG Models (`docvault/kg_models.py`)

新增 5 張表（docvault schema）：

| Table | 用途 | Key Fields |
|-------|------|------------|
| `doc_entities` | 正規化 entity 節點 | canonical_name, aliases, entity_type, document_id |
| `doc_triples` | SPO 三元組 | subject, predicate, object, chunk_id, document_id |
| `doc_communities` | Leiden 社群 | resolution_level, size, entity_ids, summary |
| `doc_community_triples` | M2M 社群↔三元組 | community_id, triple_id |
| `doc_community_summaries` | L2 預生成摘要 | community_id, summary, key_findings |

### 2b: Alembic Migration

基於 `m5n6o7p8q9r2`，新增 docvault KG 五張表。

### 2c: ChunkEntityOp 實作

- 位置: `docvault/ops/chunk_entity.py`
- 輸入: `chunks[]`, `document_id`, `space_id`
- 流程:
  1. 對每個 chunk 呼叫 `kg_ops.extract_triples(chunk.content)`
  2. `kg_ops.normalize_entity_text()` 正規化 entity
  3. 批量存入 `doc_entities` + `doc_triples`
  4. 建立 entity → chunk 映射
- 輸出: `entity_count`, `triple_count`
- 限制: 每 chunk 最多 5 triples，LLM call 失敗靜默降級

### 2d: 串接到 Ingest Pipeline

在 `routes.py` upload_document() 的 Step 10（Qdrant index）後新增 Step 11：
```python
# 11. Extract KG entities + triples (best-effort)
try:
    chunk_entity_op = ChunkEntityOp()
    await chunk_entity_op({...})
except Exception:
    logger.exception("KG extraction failed")
```

## Phase 3: CommunityIndexOp — Leiden Clustering

### 3a: CommunityIndexOp 實作

- 位置: `docvault/ops/community_index.py`
- 輸入: `document_id` 或 `space_id`（全量重建）
- 流程:
  1. 查詢該 space 所有 doc_triples
  2. `kg_ops.build_entity_graph(triples)` → igraph
  3. `kg_ops.run_leiden(graph)` → 多解析度社群
  4. `kg_ops.assign_triples_to_communities()` → 分配
  5. 存入 `doc_communities` + `doc_community_triples`
  6. 對每個社群生成 L2 摘要（LLM call）
  7. 存入 `doc_community_summaries`
  8. 索引摘要到 Qdrant（service_id="docvault-community"）

### 3b: 串接到 Ingest Pipeline

在 ChunkEntityOp 之後觸發。使用 fire-and-forget 避免阻塞 upload response。

## Phase 4: GraphSearchOp — Cascade Recall

### 4a: GraphSearchOp 實作

- 位置: `docvault/ops/graph_search.py`
- 介面: SearchSlot（替代 HybridRRFSearchOp）
- 流程:
  1. 標準 vector search（HybridRRF）取得 seed results
  2. 從 query 提取 entity（簡單 NER 或 keyword extraction）
  3. 搜尋 L2 community summaries（Qdrant semantic search）
  4. 取得命中社群的 L1 member triples
  5. 透過 triple→chunk 映射取得相關 chunks
  6. 合併 vector results + graph results，RRF 去重
- 輸出: `evidence_chunks[]`（與 HybridRRFSearchOp 格式相同）

### 4b: 串接到 QA Pipeline

1. 在 `domain_profiles.py` 的 `_build_registry()` 註冊 GraphSearchOp
2. default profile search slot 改為 `"GraphSearchOp"`
3. `routes.py` qa_question() 的 step 3 改用 profile 中的 search op

## 模組邊界

- docvault KG tables 在 `docvault` schema — 不碰 memvault schema
- 共享邏輯在 `libs/kg-ops/`（normalize、extract、community）
- memvault 繼續用自己的 `kg_models.py` + `kg_services.py`（不動）

## 測試策略（六鐵律）

1. **Mutation thinking**: 測試應在實作前思考「這段程式碼可能出什麼錯」
2. **寫測分離**: 獨立 agent 撰寫測試，不是實作 agent
3. **不變量優先**: entity normalization 是冪等的、triple count ≤ max_triples
4. **Runtime→回歸**: 實際 LLM call 測試 + mock 回歸測試
5. **Mock 只限外部 I/O**: LLM API call 用 mock，DB 用真實 session
6. **草稿不是成品**: 必須通過獨立 review
