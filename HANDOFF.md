# HANDOFF: Memvault Knowledge Lint — 主動矛盾掃描 Pipeline

## Goal
建立 Knowledge Lint pipeline，主動掃描知識庫中語意層面的過時/矛盾知識。今天已修好寫入時的衝突處理（三條線），但跨月的信念演化（如 microservices → monolith）只靠寫入時的 dedup 抓不到，需要定期主動掃描。

## 今天已完成（不需要重做）

### Synthesis Pipeline 修復
- `community_pipeline.py` + `community_summary_pipeline.py`: X-Internal-Key auth + 無限分頁循環修復
- L1 summaries: 2 → 483，communities: 2,824 → 3,834

### Block 萃取全面補齊
- `schemas.py`: `MemoryBlockCreate` 加 `source_session`
- `re_extract_batch.py`: 多目錄掃描 + cold thaw + 進度追蹤 + 限速
- 4,210 sessions 全部處理完畢，blocks 2,262 → 2,469（去重後）

### 時序衝突三條線
- **Wire 1**: `routes.py` SUPERSEDE handler → `invalidate_block()`（用 `invalid_at` 不用 `deleted_at`）
- **Wire 2**: `conflict_resolver.py` LLM prompt 含 `existing_created_at` 時間
- **Wire 3**: `kg_services.py` `_is_attitude_contradiction()` 啟發式矛盾偵測
- **Schema**: blocks 表新增 `invalid_at` + `superseded_by` + `invalidation_reason`（Alembic migration `mv20260409tv01`）

### 清理結果
- 精確重複清理: attitudes 3,711→1,729, triples 37,740→28,362, blocks 3,096→2,469
- 4 組 chosen_over 矛盾已 invalidated
- 6 個過時架構 triples 已 invalidated（microservices→monolith 演化）

## 已完成：Knowledge Lint Pipeline — 語意矛盾掃描

### 新增 `check_semantic_contradictions()`
- **純語意 embedding 搜尋**（threshold 0.70），無結構化約束
- **LLM 三分法判斷**：contradiction / evolution / compatible
- 每次 run 最多 20 對 LLM 呼叫，timeout 15s/pair，429 retry + 1s pacing
- Block-level 偵測（不只 triple），優先 knowledge + attitude 類型
- **混合取樣**：半數最新 + 半數最舊，確保跨時間比較（避免批次 re-extract 偏向）
- **Session filter**：同 `source_session` 才跳過（非 time delta）
- **Batch-friendly model**：排除 gemini-flash-lite（rate limit 太嚴），優先 kimi-k2.5/deepseek-v3

### 新增 `remediate_semantic()`
- evolution → `invalidate_block(reason="evolved", superseded_by=newer)`
- contradiction → `conflict_resolver.resolve_conflict()` 做 MERGE/SUPERSEDE/COEXIST
- dry_run=True 預設

### Knowledge Lint v2 — 四層遞進偵測（Phase 2, 部分完成）

**Layer 1: 圖結構偵測（4 checks, 確定性, 0 LLM, ~200ms）**
- `check_predicate_contradictions()` — should vs should_NOT, chosen_over 環偵測
- `check_temporal_staleness()` — 同 entity 跨 30+ 天 volatile predicate 漂移
- `check_attitude_chain_integrity()` — 環偵測 + 斷鏈 + 重複 current
- `check_entity_alias_collision()` — alias 重疊 + name containment

**Layer 3: Action-Grounded Validation（1 check, 確定性, 0 LLM, ~15ms）**
- `check_grounding()` — 比對 triples vs port_registry/modules/deprecated names
- 新檔案 `ground_truth.py` — GroundTruth builder

**測試結果（2026-04-09）**：1 秒找到 80 findings（17 grounding + 8 temporal + 54 alias + 1 attitude + 0 predicate）

**已完成：Pipeline 三階段流程（Task 9）**
- `CandidateConflict` / `ConfirmedConflict` dataclasses
- `_finding_to_candidate()` — L1/L3/L4 findings → candidates 統一轉換
- `_cross_validate()` — 上下夾擊：triple→block / block→triples / grounding=1.0，批次 DB 查詢
- `check_knowledge_conflicts()` — 整合 L1+L3+L4 → cross-validate（Stage 1+2）
- `remediate_knowledge_conflicts()` — Stage 3 cascade invalidation（block→triples 重疊 ≥ 3 words）
- `entity_alias_collision` name containment 門檻：4→6（減少短名誤報）

### 整合
- 註冊進 `ALL_CHECKS`（13 個 check）
- `kg_routes.py` lint route 支援 semantic + knowledge_conflicts remediation
- `ws_memvault_lint.py` 週排程自動修復加入 semantic_contradictions
- Dream Loop 不變（仍用快速結構化掃描）

### 測試結果（2026-04-09）
- semantic_contradictions: **10 evolution + 6 compatible + 0 contradiction**（kimi-k2.5, 543s）
- 偵測到：`uv run` 規則修正、worktree pytest 方案演化、Op Registry 架構升級等
- 三個 bug 修復歷程：time filter → session filter、sample bias → 混合取樣、gemini 429 → batch model
- structural contradictions: 20（多為 trivial 同義詞差異）→ 清理 ruf006 後剩 3
- orphan_entities: 117, data_gaps: 48, community_anomalies: 15

## Key Files
| File | Purpose |
|------|---------|
| `core/src/modules/memvault/lint.py` | 7 checks + 3 remediation functions |
| `core/src/modules/memvault/llm_models.py` | `SemanticLintOutput` model |
| `core/src/modules/memvault/kg_routes.py` | `POST /api/memvault/kg/lint` + semantic remediation |
| `core/src/modules/memvault/models.py` | MemoryBlock `invalid_at` + `superseded_by` + `invalidation_reason` |
| `core/src/modules/memvault/conflict_resolver.py` | LLM 衝突仲裁（callee） |
| `schedules/runners/ws_memvault_lint.py` | 週排程 runner |

## Current DB State
| Entity | Count | Notes |
|--------|-------|-------|
| Blocks | 2,469 | 去重後，有 `invalid_at` 欄位 |
| Triples | 28,362 | 去重後 |
| Communities | 3,834 | Leiden 重建 |
| Summaries | 483 | L0/L1/L2 部分（timeout，每日排程會累積） |
| Attitudes | 1,729 | 去重後 |
