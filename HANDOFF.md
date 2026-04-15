## Goal
Memvault Read Track 架構重整 + techstack 頁面精確反映真實程式碼流程。

## 已完成

### QueryClassifyOp (worktree: feature/query-classify-op, 4 commits)
- `e2d99cd6` — Tier 1∥2+3 實作（keyword∥semantic fusion + LLM fallback）
- `063173bf` — Tier 2 改 max-similarity（修正 port 架構誤判）
- `1a4877b4` — Test-adversary 76 spec-driven tests
- `673dd2f9` — 消除 choose_thinking_mode consumer 路由 → intent 路由
- 125 tests pass

### techstack SVG (main, untracked)
- 左右兩欄 Write | Read 佈局
- QueryClassifyOp 三層視覺化
- Output Formatter 取代 choose_thinking_mode 雙軌

## 嚴重問題：Read Track SVG 與程式碼不符

Audit 發現 SVG 畫的流程跟程式碼嚴重不符：

| SVG 畫的 | 程式碼實際做的 |
|----------|-------------|
| Classify → Cascade → Scoring → Reranking（四個獨立串行階段） | Scoring + Reranking 嵌在 search 函式裡面 |
| 11-Stage Scoring 接在 Cascade 後面 | Scoring 在 qdrant_search()/semantic_search() 內部 |
| Cascade 的 L2/L1/L0/PPR 都經過 scoring | 只有 Blocks 經過 scoring，其他不走 |
| Cascade 裡有 Hybrid RRF | cascade recall 根本沒呼叫 RRF |
| Reranking 是 Cascade 後的獨立步驟 | Reranking 在 search 內部，只對 blocks 做 |

### 真實 Read Track 流程（已驗證 query_runtime.py + kg_services.py + services.py）

```
Query
  ↓
classify_query_full() → intent + scoring_config
  ↓
┌─ Fast Search (qdrant_search) ────────────────────┐
│   Qdrant 搜尋 → 11-Stage Scoring → Reranking      │
│   → fast_cards                                     │
└────────────────────────────────────────────────────┘
  ↓
Attitude search（qdrant_search，有 scoring）
  ↓
Working cards（最近 blocks，無 scoring）
  ↓
IF intent=slow:
┌─ Cascade Recall ─────────────────────────────────┐
│   L2 Summary（staleness 檢查，無 scoring）         │
│   L1 Community（無 scoring）                       │
│   L0 Triple（無 scoring）                          │
│   PPR Walk（無 scoring）                           │
│   Block search（走 semantic_search → 有 scoring）  │
│   CRAG Eval（可選）                                │
│   Access rerank（輕量）                            │
│   → deep_cards                                    │
└───────────────────────────────────────────────────┘
  ↓
Output Formatter (format: text · json · cards)
```

### Write Track 真實流程（已驗證 routes.py + services.py）
```
User Input
  ↓
Dedup G1（routes.py:128, 可能 SKIP/MERGE/SUPERSEDE）
  ↓
Noise Filter（services.py:174, quarantine tag 不拒絕）
  ↓
Injection Guard（services.py:181, quarantine tag 不拒絕）
  ↓ 存入 DB
  ∥ 並行 event-driven
  ├─ Embedding → Qdrant
  └─ KG Auto Evolve → L0 Triple
       ↓ 批次背景
     L1 Leiden / L2 Summary
```

## Next Steps

1. **重新設計 Read Track SVG** — 必須反映嵌套結構（scoring/reranking 在 search 內部）
2. **Write Track SVG 已修正** — Dedup→Noise→Guard 串行順序正確
3. 建議開新 session（context 已膨脹），讀 HANDOFF 繼續

## Branch 狀態
- `.worktrees/feature/query-classify-op` — 4 commits ahead，125 tests pass
- `.worktrees/refactor/memvault-dual-track` — 1 commit ahead
- Main: techstack SVG 修到一半（Read Track 需重做）
