# Bitemporal Memvault — Public Contract

This document defines the BEHAVIOUR you must test. **Do NOT read any
implementation files** (services.py, query_runtime.py, routes.py, dream.py,
bitemporal_filters.py, temporal_extract.py, kg_*.py, dedup.py, sleeptime.py,
curate.py, lint*.py). Test only against the contract below.

You may read schemas.py and models.py for type signatures.

## Schema

`memvault.blocks` table (bitemporal extension):
- `valid_at TIMESTAMPTZ NULL` — when the fact STARTED being true
- `invalid_at TIMESTAMPTZ NULL` — when the fact STOPPED being true (NULL = still valid)
- `superseded_by VARCHAR(32) NULL` — points to the block that replaced this one
- `deleted_at TIMESTAMPTZ NULL` — soft delete (orthogonal to bitemporal)
- `created_at TIMESTAMPTZ NOT NULL` — system time the row was inserted

A block is "active for caller view" iff
  `deleted_at IS NULL AND invalid_at IS NULL`

A block is "active as of T" iff
  `deleted_at IS NULL`
  AND `created_at <= T`                                  (transaction-time)
  AND `COALESCE(valid_at, created_at) <= T`              (valid-time start)
  AND `(invalid_at IS NULL OR invalid_at > T)`           (valid-time end)

Note: `invalid_at == T` ⇒ block is NOT active at T (T is the moment of death).
Note: `created_at == T` ⇒ block IS active at T (T is the moment of birth).

## API surface to test

### `MemoryBlockService` (singleton at `src.modules.memvault.services.memory_block_service`)

All methods take `db: AsyncSession, space_id: str` and may take `as_of: datetime | None = None`:

- `text_search(db, space_id, query: str, top_k=10, as_of=None) -> list[SemanticSearchResult]`
- `qdrant_search(db, space_id, query: str, query_embedding: list[float], top_k=10, as_of=None) -> tuple[list[SemanticSearchResult], SearchMetadata] | None`
- `semantic_search(db, space_id, query_embedding: list[float], top_k=10, query=None, as_of=None) -> tuple[...]`
- `find_by_source_session(db, space_id, source_session: str) -> MemoryBlockResponse | None`  ← always current view, no as_of
- `list(db, space_id, pagination=None, include_invalid: bool = False) -> PaginatedResponse[MemoryBlockResponse]`
- `list_by_tags(db, space_id, tags, pagination=None, include_invalid: bool = False)`
- `list_by_type(db, space_id, block_type, pagination=None, include_invalid: bool = False)`

`SemanticSearchResult` has `.block.id` (string).

### Helper

`from src.modules.memvault.bitemporal_filters import active_block_filters`
- `active_block_filters(as_of: datetime | None = None) -> list[ColumnElement]`
- Returns SQLAlchemy WHERE clauses to splat into `.where(*conditions)`.

### `extract_valid_at` (pure function)

`from src.modules.memvault.temporal_extract import extract_valid_at`
- `extract_valid_at(content: str | None, ref: datetime | None = None) -> datetime | None`
- Returns the first ISO date recoverable from `content`, as a tz-aware UTC datetime at midnight.
- If `content` has none, returns None.
- `ref` anchors relative phrases (e.g. "上週", "X days ago"). Defaults to `datetime.now(UTC)` if None.

### POST /api/memvault/blocks (route behaviour, integration-level)

When body has no `valid_at`:
1. `extract_valid_at(body.content, ref=body.created_at or instance.created_at)` is called.
2. If it returns a date, `instance.valid_at` is set to that date.
3. If None, `instance.valid_at` stays NULL.

When body explicitly sets `valid_at`, that value wins (no extraction).

## Required test coverage (write tests for ALL of these)

### Bitemporal predicate (`active_block_filters`)

Insert 1 block per scenario into an isolated test space. Run a `select(MemoryBlock).where(*active_block_filters(as_of=...))` and assert membership:

1. **B1 — transaction-time guard**: Block A inserted today (`created_at=2026-05-01`) with backdated `valid_at=2020-01-01`.
   - `as_of=2025-01-01` → A NOT in results (created later).
   - `as_of=2026-06-01` → A in results.

2. **B2 — `as_of == created_at` boundary**: Block with `created_at=2026-05-01 12:00:00` exactly.
   - `as_of=2026-05-01 12:00:00` → IN results (closed lower bound).
   - `as_of=2026-05-01 11:59:59` → NOT in results.

3. **B3 — `as_of == valid_at` boundary**: Block with `valid_at=2026-04-01`.
   - `as_of=2026-04-01 00:00:00` → IN results (closed lower bound).
   - `as_of=2026-03-31 23:59:59` → NOT in results.

4. **B4 — `as_of == invalid_at` boundary**: Block with `invalid_at=2026-03-01`.
   - `as_of=2026-03-01 00:00:00` → NOT in results (open upper bound — fact already gone).
   - `as_of=2026-02-28 23:59:59` → IN results.

5. **B5 — NULL valid_at fallback**: Block with `valid_at=NULL`, `created_at=2026-02-01`.
   - `as_of=2026-01-01` → NOT in results (COALESCE picks created_at).
   - `as_of=2026-03-01` → IN results.

6. **B6 — current view (as_of=None)**: Block with `invalid_at NOT NULL`.
   - With `as_of=None` → NOT in results.

7. **B7 — deleted_at always wins**: Block with `deleted_at NOT NULL` and `invalid_at IS NULL` and `valid_at <= as_of`.
   - With ANY `as_of`, including None → NOT in results.

### Search paths (all four must respect bitemporal)

For each of: `text_search`, `qdrant_search`, `semantic_search`, query_runtime recent-fallback:

- Insert one valid block + one block invalidated last week.
- Search at `as_of=None` → only valid block.
- Search at `as_of=two weeks ago` → only invalidated block.

For `find_by_source_session`:
- Two blocks share the same `source_session`. One has `invalid_at NOT NULL`, one is valid.
- `find_by_source_session` returns the VALID one (or None if both invalid).

### Listing endpoints

- `list()` with `include_invalid=False` (default) → no invalid blocks.
- `list()` with `include_invalid=True` → invalid blocks appear.
- Same for `list_by_tags` and `list_by_type`.

### `extract_valid_at` formats

Must return correct date for each input (use ref=`datetime(2026, 5, 1, tzinfo=UTC)` unless noted):

- `"2025-01-15 incident"` → 2025-01-15
- `"事件 2025/01/15 發生"` → 2025-01-15
- `"事件 2025/1/15 發生"` → 2025-01-15
- `"2025年1月15日 上線"` → 2025-01-15
- `"2025年01月15日 上線"` → 2025-01-15
- `"2025年1月15號 上線"` → 2025-01-15  (號 / 號 / 号)
- `"deployed Jan 15, 2025"` → 2025-01-15
- `"deployed January 15, 2025"` → 2025-01-15
- `"deployed 15 Jan 2025"` → 2025-01-15
- `"deployed 15th Jan 2025"` → 2025-01-15
- `"started 2 years ago"` (ref=2026-05-01) → 2024-05-02 (close to that — accept ±2 days)
- `"started 3 months ago"` (ref=2026-05-01) → ~2026-02-01 (accept ±5 days)
- `"started 4 weeks ago"` (ref=2026-05-01) → 2026-04-03 (accept ±2 days)
- `"上週開始"` (ref=2026-05-01 = Friday) → some day in week prior (accept 2026-04-19 to 2026-04-26)
- Empty / None / no-date content → None

### `extract_valid_at` chooses FIRST ISO date

- `"started 2024-03-10, refactored 2025-08-20"` → 2024-03-10 (first by text position).

### Mutation thinking — please add tests that would catch these mutations

If any of the following changes were made, a STRONG test suite should fail. Make sure your tests would catch them:

- Change `<=` to `<` in `valid_at <= as_of` clause → B3 case at exact boundary should fail.
- Change `>` to `>=` in `invalid_at > as_of` clause → B4 case at exact boundary should fail.
- Change `COALESCE(valid_at, created_at)` to just `valid_at` → B5 NULL-valid_at row should disappear from current view (regression!).
- Drop the `created_at <= as_of` clause → B1 backdated-future row should leak into past as-of view.
- Drop `MemoryBlock.invalid_at.is_(None)` from any search path → invalidated blocks would leak into current view searches.

### Adversary scoping

- Use unique `space_id` per test (e.g. `f"adv-{uuid.uuid4().hex[:12]}"`).
- Clean up: delete blocks in correct FK order (`superseded_by` references must be cleared first).

## Testing infrastructure to use

Real PostgreSQL via `shared.database.async_session_factory`. NO mocks for the DB.

Path-fixup boilerplate (copy from `tests/test_p0_invalid_at_filter.py` lines 1–55) ensures the worktree's edited code is the one tested, not main's.

Run command:
```bash
~/workshop/.venv/bin/python3 -m pytest <your-file> -v
```

## What NOT to do

- Do NOT read services.py, query_runtime.py, routes.py, dream.py, kg_*.py,
  bitemporal_filters.py, temporal_extract.py, dedup.py, sleeptime.py,
  curate.py, lint*.py before writing your tests. The whole point is independent
  validation against the contract.
- Do NOT copy structure from existing `test_p0/p1/p2_*.py` files (other than the path-fixup at top).
- Do NOT add tests beyond what the contract requires (unless you spot a contract gap, in which case flag it in the test docstring).
- Do NOT mock anything except what is documented as external I/O (none in this scope — we use real PG).
