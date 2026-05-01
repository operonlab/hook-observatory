# Follow-up — Memvault Bitemporal P0→P2

## ⚠️ 少爺手動執行：Alembic Migration

**已加 column 到 dev DB**（避免 P1/P2 測試卡關），但 alembic_version 表**未**記錄。
請少爺從 main 執行：

```bash
cd ~/workshop/core
~/workshop/.venv/bin/python3 -m alembic stamp mv20260502bt01
```

或乾淨做法 — 先 DROP column 再走正規 alembic upgrade：
```sql
DROP INDEX IF EXISTS memvault.idx_blocks_valid_at;
ALTER TABLE memvault.blocks DROP COLUMN IF EXISTS valid_at;
```
然後：
```bash
~/workshop/.venv/bin/python3 -m alembic upgrade head
```

Migration file: `core/migrations/versions/mv20260502bt01_blocks_valid_at.py`
- revision: `mv20260502bt01`
- down_revision: `mv20260411kg01`
- 新增欄位: `memvault.blocks.valid_at TIMESTAMPTZ NULL`
- 新增 partial index: `idx_blocks_valid_at WHERE valid_at IS NOT NULL`

## ⚠️ 服務重啟

修改 `routes.py` + `services.py` + `query_runtime.py` 後須重啟 Core：
```bash
cd ~/workshop && ./scripts/workshop_services.py restart core
```

## Done
- P0: Recall 過濾 invalid_at（5 路徑全到位）— 4 真實 DB 測試
- P1a: MemoryBlock.valid_at 欄位 + migration file
- P1b: POST /blocks 自動萃取 valid_at（text_ops.normalize_temporal_range）
- P2: text_search + recent-fallback 加 as_of 參數（time-travel recall）
- 22 個真實 PG 整合測試（不用 mock）— standalone 跑 22/22 過

## 測試指令

```bash
# 真實 PG 整合測試（須 standalone 跑，避開與 mock 測試的 import 順序衝突）
~/workshop/.venv/bin/python3 -m pytest \
    core/src/modules/memvault/tests/test_p0_invalid_at_filter.py \
    core/src/modules/memvault/tests/test_p1_valid_at_extraction.py \
    core/src/modules/memvault/tests/test_p2_as_of_recall.py -v
```

## Known pre-existing failures (NOT caused by this branch)
- `test_sleeptime.py` 6 失敗：`ModuleNotFoundError: src.events.types` — main 上也是壞的

## P2 路由暴露（建議下個 commit）
P2 加了 service 層 `as_of` 參數，但 `/api/memvault/search` 路由還未暴露 `as_of` query 參數。建議：
```python
@router.get("/search", ...)
async def search(
    ...,
    as_of: datetime | None = Query(None, description="Time-travel: view as of this datetime"),
    ...
)
```
然後 pipe 到 `_search_blocks(as_of=as_of)`。本 commit 未動 router signature 以避免破壞既有 caller。
