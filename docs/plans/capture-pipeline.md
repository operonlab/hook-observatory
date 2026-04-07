# Capture Pipeline — Progressive Enrichment for Workshop

**Status**: ✅ COMPLETED (2026-03-30)
**Outcome**: capture 已上線為 core module，含 6 個 adapter（finance/invest/taskflow/dailyos/webcrawl/grc）+ enrichment + resolver 框架

_Original: In Progress | Date: 2026-03-08_

## Problem

CLI/MCP/Agent input friction: too many required fields block quick data entry.
Users want to "capture first, structure later."

## Solution: Capture → Crystallize Pipeline

Platform-level primitive. Cross-cutting like EventBus.

```
INPUT --> Smart Defaults --> Capture Store --> AI Enrichment --> User Review --> Promote
(raw)    (fill inferred)   (shared.captures)  (background)      (inbox UI)    (validate + create)
```

## Architecture Decision

- **Storage**: `shared.captures` table (physically isolated from formal tables)
- **Iron Rule**: Captures NEVER affect aggregates (balance, monthly report, budget)
- **Promote**: Validate against target module's Create schema, then call `service.create()`
- **Terminology**: "Capture" (not "Draft")

## Capture Model

```sql
CREATE TABLE shared.captures (
    -- SpaceScopedModel fields (id, space_id, created_by, created_at, updated_at, deleted_at)
    module        TEXT NOT NULL,          -- 'finance', 'invest', 'taskflow'
    entity_type   TEXT NOT NULL,          -- 'transaction', 'subscription', 'trade'
    payload       JSONB NOT NULL DEFAULT '{}',
    raw_input     TEXT,                   -- original natural language input
    completeness  FLOAT NOT NULL DEFAULT 0.0,  -- 0.0 ~ 1.0
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending / promoted / expired
    promoted_id   TEXT,                   -- ID of the created entity after promote
    promoted_at   TIMESTAMPTZ,
    expires_at    TIMESTAMPTZ             -- auto-expire after TTL
);
```

## Module Adapters

Each module defines a CaptureAdapter:
- `field_weights`: dict of field -> weight (for completeness calculation)
- `smart_defaults(payload, user_prefs)`: fill inferable fields
- `validate_promote(payload)`: check if promotable
- `promote(payload, db, space_id)`: create formal record via service

## Completeness Levels

| Level | Score | Meaning | Aggregate Impact |
|-------|-------|---------|-----------------|
| L0 | 0-29% | Fragment | None |
| L1 | 30-69% | Recognizable | None |
| L2 | 70-99% | Near-complete | After promote only |
| L3 | 100% | Complete | After promote only |

## Finance Transaction Adapter

Field weights:
- amount: 25, type: 20, wallet_id: 20
- payment_method: 10, category_id: 10, description: 10, transacted_at: 5

Smart defaults:
- wallet_id -> user preference default_wallet_id
- payment_method -> inferred from wallet type
- transacted_at -> now()
- type -> 'expense' (most common)
- currency -> 'TWD'

## Phase Plan

- P0: Smart Defaults (default_wallet_id in preferences, payment_method default)
- P1: shared.captures table + CaptureService + finance adapter + API routes
- P2: Frontend capture inbox + batch fill UI
- P3: More adapters (invest, subscription) + MCP capture tool + notification digest

## Events

- `capture.created` — new capture stored
- `capture.promoted` — capture converted to formal record
- `capture.expired` — capture TTL reached

## API Routes

```
POST   /api/captures                    -- create capture
GET    /api/captures                    -- list (filter by module, status)
GET    /api/captures/:id                -- get one
PATCH  /api/captures/:id                -- update payload
POST   /api/captures/:id/promote        -- promote to formal record
DELETE /api/captures/:id                -- discard
GET    /api/captures/stats              -- counts by module/status
```
