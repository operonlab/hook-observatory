# DocVault Pipeline Slot Contracts

每個 Slot 的 input/output schema 與 side effects。任何符合契約的 Op 都能插入。

## ChunkSlot

| 項目 | 定義 |
|------|------|
| **Input** | `raw_content: str` — 原始文件全文 |
| **Output** | `chunks: list[Chunk]` — 語義分段列表 |
| | `section_tree: dict` — 結構樹 `{title, level, children}` |
| **Side Effects** | 無 |

### Chunk Schema
```python
@dataclass
class Chunk:
    content: str
    chunk_index: int
    section_path: str | None  # "Chapter 3 > 3.2 > Paragraph 4"
    page_range: str | None    # "12-13"
    heading: str | None
    token_count: int
    chunk_type: str           # text | table | list | code
```

### 可選 Ops
- `ContextualChunkOp` ⭐ — 每塊加 `{doc_title} > {section_path}:` 前綴
- `HierarchicalChunkOp` — 法條層級結構
- `LateChunkOp` — 先嵌入完整文件再分塊（需改 embed_worker）

---

## IndexSlot

| 項目 | 定義 |
|------|------|
| **Input** | `chunks: list[Chunk]` |
| **Output** | `indexed_collection: str` — Qdrant collection reference |
| **Side Effects** | Qdrant upsert（`service_id="docvault-chunk"`） |

### 可選 Ops
- `FlatIndexOp` — 基本 Qdrant indexing
- `RAPTORIndexOp` — 遞迴聚類+摘要建樹
- `GraphIndexOp` — 實體圖譜索引

---

## SearchSlot

| 項目 | 定義 |
|------|------|
| **Input** | `query_embedding: list[float]` — 1024D dense vector |
| **Output** | `candidates: list[ScoredChunk]` — 帶分數的 chunk 列表 |
| **Side Effects** | 無 |

### ScoredChunk Schema
```python
@dataclass
class ScoredChunk:
    chunk: DocumentChunkResponse
    score: float
    source: str  # "vector" | "keyword" | "hybrid"
```

### 可選 Ops
- `HybridRRFSearchOp` — Qdrant RRF（dense + sparse）
- `DeepReadSearchOp` — locate-then-read 結構定位
- `GraphSearchOp` — 實體關係搜尋
- `AgenticSearchOp` — agent 自主選策略

---

## RerankSlot

| 項目 | 定義 |
|------|------|
| **Input** | `candidates: list[ScoredChunk]` |
| **Output** | `reranked: list[ScoredChunk]` — 重排後的 top-k |
| **Side Effects** | 無 |

### 可選 Ops
- `JinaRerankOp` ⭐ — 現有 Jina v3 MLX
- `ColBERTRerankOp` — token 級晚期交互
- `CrossEncoderOp` — 通用 cross-encoder

---

## SynthSlot

| 項目 | 定義 |
|------|------|
| **Input** | `question: str`, `evidence: list[ScoredChunk]` |
| **Output** | `answer: str`, `citations: list[Citation]` |
| **Side Effects** | QALog 寫入（透過 qa_log_service） |

### Citation Schema
```python
@dataclass
class Citation:
    document_id: str
    chunk_id: str | None
    section: str | None
    page: str | None
    quote: str | None
```

### 可選 Ops
- `CitedAnswerOp` — 通用帶引用回答
- `StrictCiteOp` — 醫療/合規場景精確引用
- `ContradictionAwareOp` — 法律場景矛盾對比
