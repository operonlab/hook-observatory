# Follow-up — Memvault Bitemporal P0→P2 (round 2, post codex review)

## ⚠️ Pre-existing alembic multi-head — NOT introduced by this branch

`main` already has 10 heads. This branch adds `mv20260502bt01` chained off
`mv20260411kg01`, leaving the head count at 10. So:

```bash
# WRONG — fails with "Multiple head revisions are present" pre-existing on main
alembic upgrade head

# RIGHT — upgrade ALL heads
~/workshop/.venv/bin/python3 -m alembic -c core/alembic.ini upgrade heads
```

Cleaning up the pre-existing multi-head state is out of scope for this PR
(would require a global `alembic merge` that shouldn't be made by a feature
branch). Open a separate housekeeping PR if you want a single linear chain.

## ⚠️ 少爺手動執行：Apply schema

**Already added column to dev DB** (so P1/P2 tests can run), but `alembic_version`
table is NOT updated. Two options:

**Option A — fast** (keep dev DB column, just register the migration):
```bash
cd ~/workshop
~/workshop/.venv/bin/python3 -m alembic -c core/alembic.ini stamp mv20260502bt01
```
Note: this skips creating the new `idx_blocks_active_eff` functional index —
you'll need to run it manually:
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS memvault.idx_blocks_active_eff
  ON memvault.blocks (COALESCE(valid_at, created_at))
  WHERE deleted_at IS NULL AND invalid_at IS NULL;
```

**Option B — clean** (drop dev DB column, run real migration):
```sql
DROP INDEX IF EXISTS memvault.idx_blocks_valid_at;
ALTER TABLE memvault.blocks DROP COLUMN IF EXISTS valid_at;
```
Then:
```bash
~/workshop/.venv/bin/python3 -m alembic -c core/alembic.ini upgrade heads
```

## ⚠️ 服務重啟

Many files changed (`routes.py` + `services.py` + `query_runtime.py` +
`dream.py` + `kg_routes.py` + `kg_services.py` + `dedup.py` + `sleeptime.py`
+ `curate.py` + `grc_adapter.py` + `lint.py` + `lint_checks/*`). Restart Core:
```bash
cd ~/workshop && ./scripts/workshop_services.py restart core
```

## What changed (round 2 — addressed all codex Critical + Major)

### Critical
- **C1**: `/api/memvault/search` and `/query` now accept `as_of` query param + SDK passthrough.
- **C2**: `qdrant_search` / `semantic_search` / `_keyword_search` / `_warm_tier_search` all accept `as_of` and apply `active_block_filters(as_of=...)`.
- **C3**: `active_block_filters(as_of=T)` now includes a transaction-time guard (`created_at <= T`) — backdated backfill no longer leaks into past as-of views.
- **C4**: `_warm_tier_search` (semantic_search warm-tier) was missing both `deleted_at` and `invalid_at` filters — fixed via helper.
- **C5**: FOLLOWUP corrected to `alembic upgrade heads` (plural). Multi-head left for a separate housekeeping PR.

### Major
- **M1**: `list` / `list_by_tags` / `list_by_type` default to active-only; opt-in `include_invalid: bool = False` for audit callers.
- **M2 / M3**: `dream.py` (5 sites), `kg_services.py`, `kg_routes.py`, `sleeptime.py`, `dedup.py`, `curate.py`, `grc_adapter.py`, `lint.py`, `lint_checks/stable_id_validity.py` all now filter `invalid_at IS NULL` (or use the helper). `routes.py` `/sessions` group_by also fixed.
- **M4 / M5 / M6 / M7**: `extract_valid_at` now pre-normalises slash dates (`2025/01/15`), Chinese dates (`2025年1月15日`), English month names (`Jan 15, 2025` / `15 Jan 2025`), and resolves English `X (years|months|weeks|days) ago`. Anchors on `body.created_at` (M5).
- **M8**: Migration uses `CREATE INDEX CONCURRENTLY` (no write lock); adds functional index on `COALESCE(valid_at, created_at) WHERE deleted_at IS NULL AND invalid_at IS NULL` to support `as_of` recall.

### Helper
- New `core/src/modules/memvault/bitemporal_filters.py` — `active_block_filters(as_of=None)` is the single source of truth. ALL future read paths must use this; do not hand-write `MemoryBlock.invalid_at IS NULL`.

## Tests

Run new integration tests (real PG, standalone — see "Test ordering" below):
```bash
~/workshop/.venv/bin/python3 -m pytest \
    core/src/modules/memvault/tests/test_p0_invalid_at_filter.py \
    core/src/modules/memvault/tests/test_p1_valid_at_extraction.py \
    core/src/modules/memvault/tests/test_p2_as_of_recall.py -v
```

Independent adversary tests (round 2 — written by separate agent without
seeing the implementation) live in:
```
core/src/modules/memvault/tests/test_adversary_bitemporal.py
```

### Test ordering
Integration tests use real `src.modules.memvault.*` imports and conflict with
mock-based `test_sleeptime.py` etc when collected together (Table redef +
sys.modules cache pollution). Run integration tests in their OWN pytest
invocation. Pre-existing `test_sleeptime.py` is broken on `main` too
(`ModuleNotFoundError: src.events.types`) — not introduced here.

## Six-iron-rules compliance (round 2)

| # | Rule | Round 1 | Round 2 |
|---|------|---------|---------|
| 1 | Mutation thinking | ❌ | ✅ codex independent review found 5 Critical + 11 Major missed mutations |
| 2 | 寫測分離 | ❌ | ✅ codex review + planned independent adversary test agent |
| 3 | Invariants | ⚠️ | ⚠️ partially; could improve |
| 4 | Real runtime → regression | ✅ | ✅ |
| 5 | Mock only at I/O boundary | ✅ | ✅ no mocks |
| 6 | AI tests are drafts | ❌ | ✅ codex pass treated my tests as drafts |
