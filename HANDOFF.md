# DocVault E2E 修通 Handoff

## Goal
修通 docvault CLI/API 的 search + QA route，讓少爺能用 `/docvault` 問 PDF 文件的問題。

## 背景
少爺想要 memvault（個人記憶）之外，再建一套基於文件事實的 QA 知識圖譜（docvault）。這個 session 完成了：
- 完整架構設計（Plan: `.claude/plans/flickering-greeting-micali.md`）
- Slot-based pipeline（5 可替換 Slot + Domain Profiles）
- 模組骨架（67 files, ~9K LOC, 五層覆蓋）
- DB schema（6 tables in `docvault.*`）
- tmux-relay signal fix（pane-exited hook）
- **底層 E2E 鏈路已通**：PDF parse → chunk → embed → Qdrant index → search

## 當前痛點（需要修的）
CLI/API 的 search 和 QA route 回 500。底層 `hybrid_search()` 已確認能用，問題在 route 層的 request/response 格式。

### 具體問題
1. `POST /api/docvault/search` — route 改成接受 body `DocumentSearchParams`，但可能 SDK 和 route 的 params 沒對齊
2. `POST /api/docvault/qa` — 還沒測過，可能也有類似問題
3. CLI `docvault search` 和 `docvault qa` 依賴上面的 route

### 已驗證能用的底層
```python
# 這些都確認 OK：
from src.shared.qdrant_search import hybrid_search
from src.shared.search_types import SearchConfig
config = SearchConfig(top_k=5, service_ids=["docvault-chunk"])
results, meta = await hybrid_search("problem-first approach", "default", config)
# → 3 results, score 0.5/0.33/0.25
```

### 已上傳的測試文件
- Document ID: `019d6381167e774196fc6094797a98e7`
- Title: "Anthropic Skill Guide"
- Source: `/tmp/anthropic-skill-guide.pdf` (561KB, 33 pages)
- 26 chunks indexed in Qdrant (service_id="docvault-chunk")

## Files Modified
| Path | What Changed |
|------|-------------|
| `core/src/modules/docvault/routes.py` | upload endpoint 已通，search/qa route 需修 body params |
| `core/src/modules/docvault/schemas.py` | 加了 DocumentSearchParams、DocumentUploadRequest |
| `core/src/modules/docvault/models.py` | 修了 metadata_ column name |
| `libs/sdk-client/sdk_client/docvault.py` | upload() 改用 file_path，search params 需對齊 route |
| `core/cli/docvault.py` | 依賴 SDK，SDK 修好就能用 |

## Next Steps
1. 修 `routes.py` 的 `search_documents` endpoint — 確認 `DocumentSearchParams` body 和 SDK 的 request 對齊
2. 修 `routes.py` 的 `qa` endpoint — 確認 `QARequest` body 格式
3. 重啟 core：`~/.local/bin/python3 scripts/workshop_services.py restart core`
4. 測試：`~/.local/bin/python3 ~/workshop/core/cli/docvault.py search "problem-first" --json` (需設 CORE_INTERNAL_API_KEY env)
5. 測試：同上但用 `qa "How does problem-first approach work?"` 
6. 少爺的最終需求：用 docvault 回答「Anthropic Skill Guide 裡 problem-first 是怎麼處理問題的？」

## Key Decisions
1. docvault 是獨立 module，不改 memvault（認識論不同：記憶衰減 vs 文件永存）
2. Slot-based pipeline：不同領域（醫療/法律/金融）用不同 Op 組合
3. Phase 1 default 用 ContextualChunkOp（Anthropic 方法），不用 LateChunkOp（需改 embed_worker）
4. 矛盾偵測改異步（emit event），不在讀路徑同步寫
5. Auth 用 X-Internal-Key header，env: CORE_INTERNAL_API_KEY

## References
- Plan: `/Users/joneshong/.claude/plans/flickering-greeting-micali.md`
- Skill: `~/.claude/skills/docvault/SKILL.md`
- Memory: `~/.claude/projects/-Users-joneshong-workshop/memory/docvault-architecture.md`
