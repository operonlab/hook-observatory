# CONTRACT_FOR_ADVERSARY — memvault data-flow-complete PR

> Adversary agent: do **not** open any source file in
> `core/src/modules/memvault/` (except `models.py` / `schemas.py` /
> `kg_models.py` for type signatures only),
> `libs/sdk-client/sdk_client/memvault.py`, `mcp/memvault/server.py`, or the
> new alembic migrations. Read only this contract. Your job is independent
> validation — write tests against the behaviour declared here. If a test
> fails, the contract is wrong OR the implementation is wrong; do not assume
> either.

This PR has two themes:

1. **Bitemporal end-to-end data flow** — `valid_at` / `invalid_at` / `as_of`
   travel from hook → SDK → MCP → HTTP → service.
2. **Governance closed loop** — CRAG verdict → triple metadata; auto_evolve
   idempotency; UNVERIFIED→VERIFIED promotion; Worker 5 persona/human content.

The earlier `CONTRACT_FOR_ADVERSARY.md` (bitemporal P0-P2) still holds — its
invariants must NOT regress.

---

## 1. HTTP API contract

### 1.1 `GET /api/memvault/blocks`
- New query param: `include_invalid: bool = false`.
- When `include_invalid=true`, response items MAY contain blocks where
  `invalid_at IS NOT NULL`. Soft-deleted (`deleted_at IS NOT NULL`) blocks
  are STILL excluded regardless.
- Default (false) → only blocks where `invalid_at IS NULL`.
- Permission: `memvault.read` (no escalation needed).
- Param flows identically into `?tags=…`, `?block_type=…`, and the no-filter
  path.

### 1.2 `POST /api/memvault/recall/text`
- Body schema gains `as_of: datetime | None = None` (ISO8601).
- Endpoint behaviour:
  - `as_of=None` → present-time recall.
  - `as_of=T` → recall MUST present knowledge as it was at instant T:
    excludes blocks where `valid_at > T` and where `invalid_at <= T`.
- Returned `Content-Type: text/plain` (markdown body unchanged in shape).

### 1.3 `POST /api/memvault/blocks/{id}/invalidate`  (NEW)
- Body: `{ "reason": str = "manual", "superseded_by_id": str | None = null }`.
- Sets `invalid_at = now()`, `superseded_by = body.superseded_by_id`,
  `invalidation_reason = body.reason`.
- Returns `MemoryBlockResponse`.
- 404 when block not found.
- Permission: `memvault.write`.

### 1.4 `POST /api/memvault/blocks/{id}/restore`  (NEW)
- Body: empty.
- Clears `invalid_at`, `superseded_by`, `invalidation_reason` (sets all to
  `null`).
- Returns `MemoryBlockResponse`.
- 404 when block not found.
- Permission: `memvault.write`.

### 1.5 `GET /api/memvault/kg/recall`
- New query param: `as_of: datetime | None = None`.
- When `as_of=T`:
  - `triples` layer (ilike fallback) MUST exclude triples where
    `created_at > T`, `invalid_at IS NOT NULL AND invalid_at <= T`, or
    `valid_at IS NOT NULL AND valid_at > T`.
  - `blocks` layer MUST honour the same predicate.
  - Vector layers (Qdrant) — partial coverage is acceptable; the call MUST
    NOT raise.

---

## 2. SDK contract (`sdk_client.memvault.MemvaultClient`)

| Method | New / Changed param | HTTP target |
|--------|--------------------|------------|
| `list_blocks` | `include_invalid: bool = False` | `GET /blocks?include_invalid=true` (only when True) |
| `recall` | `as_of: str | None = None` | `GET /search?as_of=…` (only when set) |
| `invalidate_block(block_id, reason='manual', superseded_by_id=None)` (NEW) | — | `POST /blocks/{id}/invalidate` with `{reason[, superseded_by_id]}` |
| `restore_block(block_id)` (NEW) | — | `POST /blocks/{id}/restore` with `{}` |

Behaviour: when an optional kwarg is None / False, it MUST NOT appear in the
emitted query string / request body.

---

## 3. MCP tool contract (`mcp/memvault/server.py`)

`memvault_recall(..., as_of: str = "")`:
- New `as_of` parameter (default empty string).
- When `as_of != ""`, propagate to `client.recall(as_of=as_of)`.
- Empty string MUST be treated as "no time-travel" (i.e. forwarded as None).

---

## 4. Hook recall_text contract

`build_recall_text(prompt, session_id=None, cwd=None, as_of=None)`:
- New `as_of: datetime | None` parameter.
- When set, the function MUST place `as_of=<iso>` in the query string of:
  - `GET /api/memvault/kg/recall` (cascade)
  - `GET /api/memvault/search` (fallback)
  - `GET /api/memvault/kg/attitudes/relevant`
- When None, those URLs MUST NOT contain `as_of=`.
- The function MUST NOT raise; on transport error it returns "".

---

## 5. Service-layer signature changes

`memory_block_service.invalidate_block(db, block_id, reason='manual',
superseded_by_id=None)`:
- `superseded_by_id` is now optional (was previously required).
- When not provided, `block.superseded_by` MUST be set to `None`.
- Returns the mutated MemoryBlock (was previously None).

`memory_block_service.restore_block(db, block_id)` (NEW):
- Inverse of invalidate_block — sets `invalid_at`, `superseded_by`,
  `invalidation_reason` all to None.
- Returns the mutated MemoryBlock; None when not found.

---

## 6. KGTriple verification fields  (new columns on `memvault.triples`)

| Column | Type | Default | Constraint |
|--------|------|---------|-----------|
| `verification_status` | `varchar(16)` | `'unverified'` | NOT NULL |
| `verified_at` | `timestamptz` | NULL | nullable |
| `last_confirmed_at` | `timestamptz` | NULL | nullable |
| `crag_correct_count` | `int` | 0 | NOT NULL |
| `crag_incorrect_count` | `int` | 0 | NOT NULL |

Status enum values: `'unverified' | 'verified' | 'disputed'`. Anything else
is invalid.

A partial index named `idx_triples_unverified` MUST exist with
`WHERE verification_status = 'unverified' AND invalid_at IS NULL`.

Two new audit-log tables:
- `memvault.kg_auto_evolve_log` with unique constraint
  `uq_auto_evolve_memory_hash` on `(memory_id, content_hash)`, plus columns
  `triples_extracted`, `triples_stored`, `contradictions_resolved`.
- `memvault.kg_verification_run_log` with columns `started_at`,
  `finished_at`, `dry_run`, `candidates_scanned`, `promoted_count`,
  `demoted_count`, `notes`.

---

## 7. CRAG verdict → triple metadata invariants

When `_record_implicit_feedback` runs (or any equivalent code path that
processes a `CascadeRecallResult` with verdict `CORRECT`/`INCORRECT`/
`AMBIGUOUS`):

- Verdict `CORRECT`, triples list `[t1, …, tN]`:
  - Each `tᵢ.crag_correct_count` increments by 1.
  - Each `tᵢ.last_confirmed_at` becomes "now" (timezone-aware UTC, within a
    few seconds of clock).
  - `verification_status` is NOT changed by this path.

- Verdict `INCORRECT`, triples `[t1, …, tN]`:
  - Each `tᵢ.crag_incorrect_count` increments by 1.
  - For any `tᵢ` where (after the increment) `crag_incorrect_count >= 2 AND
    crag_correct_count == 0 AND verification_status != 'disputed'`:
    `verification_status` becomes `'disputed'` (does NOT set `invalid_at`).

- Verdict `AMBIGUOUS`: NOTHING changes on triples.

The existing `search_feedback` write path MUST continue to operate
unchanged (positive / negative / skip semantics preserved).

---

## 8. auto_evolve idempotency invariants

Function: `kg_auto_evolve.auto_evolve_kg(memory_id, content, block_type,
space_id, source_session, db) -> dict[str, int]`.

- Returned dict has keys: `triples_extracted`, `triples_stored`,
  `contradictions_resolved`.

- When invoked and a row exists in `memvault.kg_auto_evolve_log` with
  `(memory_id=M, content_hash=H(content))`:
  - The function returns the cached `triples_extracted` /
    `triples_stored` / `contradictions_resolved` from that log row.
  - No new `memvault.triples` rows are written.
  - The LLM extractor (`extract_triples_from_content`) MUST NOT be invoked
    on this path. (If you can't observe the LLM call directly, observe the
    side effect: zero new rows in `memvault.triples`.)

- When invoked with same `memory_id=M` but different content `C' != C`:
  - Old log row(s) for `memory_id=M` are removed first.
  - Then a normal extraction runs.
  - A new log row with `(M, H(C'))` is written.

`H(content)` properties (call this `_content_hash`):
- `len(H) == 64`, valid hex (SHA-256).
- `H("hello world") == H("hello   world") == H("hello\nworld") ==
  H("  hello world  ")` (whitespace normalised).
- `H("hello world") != H("hello WORLD")` (case sensitive).
- `H("hello world") != H("hello world!")` (punctuation sensitive).

---

## 9. Promote-unverified contract

Function: `kg_verification.promote_unverified(db, *, space_id='default',
batch_size=100, dry_run=True) -> PromotionStats`.

`PromotionStats` is a dataclass with at minimum:
- `candidates_scanned: int`
- `promoted_ids: list[str]`
- `demoted_ids: list[str]`
- `dry_run: bool`
- `promoted_count: int` property (`== len(promoted_ids)`)
- `demoted_count: int` property (`== len(demoted_ids)`)

Promotion candidate (status MUST become `'verified'`, `verified_at` set to
the run's start time):
ANY of —
- A) `crag_correct_count >= 3 AND crag_incorrect_count == 0`
- B) `last_confirmed_at >= now() - 90 days AND access_count >= 5`

Demotion candidate (status MUST become `'disputed'`):
- `crag_incorrect_count >= 2 AND crag_correct_count == 0 AND
  verification_status != 'disputed'`

Both passes MUST skip rows with `deleted_at IS NOT NULL` (always);
promotion additionally skips rows with `invalid_at IS NOT NULL`.

`dry_run=True`:
- NO mutation of any triple row.
- An audit row in `kg_verification_run_log` IS still written.

`dry_run=False`:
- Triple rows are mutated as described.
- An audit row in `kg_verification_run_log` is written.

Module-level constants must satisfy:
- `CORRECT_COUNT_THRESHOLD >= 2`
- `RECENT_CONFIRM_DAYS >= 30`
- `RECENT_CONFIRM_ACCESS_THRESHOLD >= 2`
- `DEMOTE_INCORRECT_THRESHOLD >= 2`

---

## 10. stale_claims × last_confirmed_at invariant

When `lint_checks/stale_claims.check_stale_claims(db, space_id, *,
age_days_threshold=30, sample_size=100)` runs and a contradiction pair
(tA, tB) is detected:
- If BOTH `tA.last_confirmed_at` AND `tB.last_confirmed_at` are within the
  past `max(age_days_threshold, 90)` days, the pair MUST NOT be reported as
  a stale-claim finding.
- Otherwise, behaviour matches the previous contract (age-based decision).

Pre-existing behaviour preserved: when `last_confirmed_at IS NULL` on either
side, age-based decision applies (no special skip).

---

## 11. Worker 5 (sleeptime) throttle invariant

Module-level constant `PERSONA_HUMAN_THROTTLE_SECONDS = 86400` (24h).

`_maybe_update_persona_human(db, space_id) -> list[str]` returns the block
types updated. Constraint:
- Two consecutive calls for the same `space_id` within 24h MUST yield an
  empty list on the second call (regardless of whether the first ran the LLM
  or short-circuited on missing context).
- The throttle counter is bumped even on failure (so a broken LLM does not
  get hammered every sleeptime tick).

`_run_sleeptime` MUST still ensure persona / human placeholder rows exist
(idempotent) so downstream readers do not NPE — even when the LLM is
throttled or fails.

---

## 12. Alembic chain invariants

- `alembic heads` MUST report exactly **1** head.
- The head migration MUST add the five Triple columns from §6 plus create
  tables `kg_auto_evolve_log` and `kg_verification_run_log` plus the
  partial index.
- `downgrade()` of the head migration MUST be a clean inverse (drops the
  added columns + indices + tables).

---

## 13. "Not regressed" guarantees

These pre-existing behaviours MUST continue to hold (regression sentinels):

- All P0-P2 bitemporal contracts in the older `CONTRACT_FOR_ADVERSARY.md`.
- `GET /blocks` without `include_invalid` returns only active blocks.
- `_record_implicit_feedback` still writes to `search_feedback`.
- `/recall/text` with no `as_of` still returns the same markdown shape.
- Existing call-sites of `invalidate_block(db, block_id, ...)` keep working
  (kwarg reorder is backwards-compatible).

---

## Out of scope (do not test)

- Vector layer (Qdrant) full bitemporal coverage — explicitly TODO in code.
- Frontend UI.
- The exact wording of LLM prompts for persona/human.
- Cronicle job time format.

---

## Testing setup

Path-fixup boilerplate identical to `tests/test_p0_invalid_at_filter.py`
lines 1-55 — ensures the worktree's edited code is the one tested, not main's.

For SDK tests (HTTP not actually called), either
`MemvaultClient.__new__(MemvaultClient)` to bypass `__init__`, then
monkey-patch `_get` / `_post` on the class, OR use `pytest-httpx`.

For DB tests, use `shared.database.async_session_factory` against real
PostgreSQL. Use unique per-test `space_id` (e.g. `f"adv-{uuid4().hex[:12]}"`)
and clean up in correct FK order.

For URL-asserting tests on `build_recall_text`, monkey-patch
`memvault.recall_text.builder._http_get` to capture URLs without hitting
network.
