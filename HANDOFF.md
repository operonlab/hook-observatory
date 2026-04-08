# HANDOFF: Synthesis Pipeline 排查

## Goal
排查 memvault synthesis pipeline 為什麼 community_summaries 只有 76/2342（3.2% 產生率），修復後讓 cascade recall L2 summaries 層恢復正常。

## Background
- Synthesis 排程在每日 17:30 跑（`schedules/runners/ws_memvault_synthesis.py`）
- 調查發現 Step 1（`synthesis_runner.py` → Leiden clustering + LLM summaries）反覆失敗
- DB 有 2,342 個 communities 但只有 76 個 community_summaries
- Qdrant 已有 211 個 summary 向量（`backfill_kg_qdrant.py` 已跑過）

## Today's Context
今天（2026-04-08）完成了 memvault 的大修：
1. PydanticAI 導入：7 個 httpx → PydanticAI Agent（全走 LiteLLM）
2. extract.py auth 修復：X-Internal-Key header（860 blocks 孤兒已補吃）
3. cascade recall blocks 層修復：改用 qdrant_search()
4. KG Qdrant 向量全層補建：35K+ vectors
5. 萃取模型切換：LiteLLM gemini-3.1-pro（主）+ Gemini CLI（備援）

**唯一剩餘問題**就是 synthesis pipeline L2 summaries 產生率低。

## Key Files
| File | Purpose |
|------|---------|
| `schedules/runners/ws_memvault_synthesis.py` | 排程入口 |
| `schedules/manifest.json` (line 16-24) | Job config (17:30 daily) |
| `mcp/memvault/pipelines/synthesis_runner.py` | 實際 pipeline |
| `mcp/memvault/pipelines/cluster_pipeline.py` | Leiden clustering |
| `core/src/modules/memvault/kg_services.py` | CommunityService / CommunitySummaryService |

## Diagnosis Steps
1. 讀 synthesis log：`~/Claude/memvault/logs/synthesis.log` 或 Cronicle (port 4105) job log
2. 找到 Step 1 的具體錯誤訊息
3. 手動跑一次 synthesis 觀察錯誤
4. 修復後驗證 summaries 數量增加

## What's Already Verified
- DB: blocks 2262, triples 28900, communities 2342, attitudes 2131
- Qdrant: blocks 2296, triples 28632, communities 2342, summaries 211, attitudes 2146
- Cascade recall: 四層（summaries/communities/triples/blocks）全通
- Core API auth: X-Internal-Key working
