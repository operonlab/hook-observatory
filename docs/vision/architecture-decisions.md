---
doc_version: 1
content_hash: 78a58ddc
---

# Architecture Decisions

> Records key design decisions for Workshop architecture, rationale, and alternatives.

---

## AD-1: Modular Monolith over Microservices

**Decision**: Adopt Modular Monolith (single deployment unit + module boundaries), not Microservices.

**Rationale**:
- One-person dev team (+AI) — microservices operational overhead far exceeds benefits
- Modules need frequent data exchange; network hops add unnecessary latency
- Single `uv run` startup — dev experience far superior to docker-compose with 10+ services
- If a Module genuinely needs independent scaling later, it can be extracted from the Monolith

**Constraints**:
- Direct imports between Modules are forbidden (only via Event Bus or Public API)
- Each Module has an independent DB schema (schema isolation, not DB isolation)
- Cross-module data queries must go through API — no JOINs across Module tables

---

## AD-2: MCP Server as Thin Adapter

**Decision**: Each Domain has an independent MCP Server, but MCP Servers do not touch the database directly —
they call FastAPI Core's REST API. MCP Server = HTTP Adapter.

**Rationale**:
- Claude Code needs MCP interface to directly operate each Domain
- MCP Servers hitting DB directly would bypass Core's validation, events, and Hook logic
- Adapter pattern keeps MCP Servers lightweight; business logic stays centralized in Core
- MCP Server outage doesn't affect Core; when Core API changes, MCP only updates HTTP calls

**Pattern**:
```
Claude Code ──► MCP Server ──► FastAPI Core ──► Database
                (adapter)       (business)       (persistence)
```

**Splitting Rules**:
- Each Domain gets at least 1 MCP Server
- MCP Servers exceeding 10 tools should be split (e.g., `workshop-quest-manage` + `workshop-quest-pool`)
- MCP Server tool naming: `{domain}_{action}` (e.g., `finance_add_transaction`)

**Existing MCP Servers (pending rename)**:
| Current Name | Planned Name | Tool Count |
|-------------|-------------|------------|
| `pulso-finance` | `workshop-finance` | 9 |
| `pulso-quest` | `workshop-quest` | 10 |
| `pulso-muse` | `workshop-muse` | 8 |
| `kas-memory` | `workshop-memory` | 8 |

---

## AD-3: Space-Based Sharing Model

**Decision**: Adopt Space-based sharing model, not traditional Multi-Tenant.

**Rationale**:
- Traditional Multi-Tenant assumes organizational hierarchy (org → team → user), which doesn't fit a personal workstation scenario
- Workshop's sharing is flexible: one ledger entry might be shared with spouse, another task shared with a friend
- A Space is a "sharing scope" — can be personal / family / friends / org
- Each Space can independently enable/disable different Modules

**Data Model**:
```sql
-- Space definition
CREATE TABLE spaces (
    id          UUID PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,  -- personal, family, friends, org
    owner_id    UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Space members
CREATE TABLE space_members (
    space_id    UUID REFERENCES spaces(id),
    user_id     UUID REFERENCES users(id),
    role        TEXT NOT NULL,  -- owner, admin, member, guest
    modules     TEXT[] NOT NULL DEFAULT '{}',  -- authorized module list
    joined_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (space_id, user_id)
);
```

**Design Points**:
- All data tables include a `space_id` column (added in Phase 0)
- `modules[]` controls which Modules a member can access in that Space
- Users can belong to multiple Spaces simultaneously
- Default: each new user automatically gets a personal space

---

## AD-4: Widget-Based Dashboard

**Decision**: Dashboard uses a Widget system, not traditional page-routed SPA.

**Rationale**:
- Core requirement: "like Android home screen widgets — freely design my dashboard"
- Traditional SPA page switching = context switching; Widgets show multiple Module info simultaneously
- Widgets are composable, draggable, resizable — far more personalized than fixed pages
- Each Module can provide multiple Widgets (different sizes, different functional facets)

**Technology Choices**:
| Technology | Choice | Rationale |
|-----------|--------|-----------|
| Layout | `react-grid-layout` | Mature drag-and-drop grid solution |
| Widget RWD | CSS Container Queries | Widgets adapt to their own size, not screen size |
| Cross-Widget Communication | Custom EventBus | Widget A emits event → Widget B responds |
| Widget Registry | JSON manifest | Each Module declares what Widgets it provides |
| State Persistence | localStorage + Core API | Layout stored in user preferences |

**Widget Lifecycle**:
1. Module registers Widget via manifest (type, sizes, default props)
2. User drags Widget from Gallery to Dashboard
3. Widget adapts layout based on Container size
4. Widget fetches data via Core API
5. Widgets communicate via EventBus (e.g., click finance transaction → quest shows related task)

**Widget Size Classes**:
- **Small** (1×1 ~ 2×1): Single data metric, quick action button
- **Medium** (2×2 ~ 3×2): Lists, simple charts, forms
- **Large** (4×2 ~ full width): Full feature interface, complex charts, knowledge graph

---

## AD-5: Resource Abstraction

**Decision**: Unify human, machine, service, and AI agent into a single Resource abstraction.

**Rationale**:
- quest's task dispatch needs to know "who can do this" — that "who" isn't necessarily a person
- A task can be assigned to a human (manual), machine (cron job), or AI agent (Claude/Codex)
- Unified model enables the same matching logic regardless of resource type
- Lays the foundation for future ERP scenarios (machine capacity, personnel hours, AI agent parallelism)

**Unified Resource Model**:
```
resources:
  id              UUID
  type            ENUM(human, machine, service, agent)
  name            TEXT
  capabilities    TEXT[]        -- what it can do
  capacity        FLOAT         -- maximum capacity
  current_load    FLOAT         -- current load
  availability    JSONB         -- schedule / availability
  cost_rate       DECIMAL       -- unit cost
  status          ENUM(active, busy, offline, maintenance)
  metadata        JSONB         -- type-specific extension fields
```

**Use Cases**:
- **matching**: `SELECT * FROM resources WHERE capabilities @> ARRAY['python'] AND current_load < capacity`
- **workforce**: Dashboard showing load status for all resources
- **quest dispatch**: Auto-pair based on task requirements × resource capabilities

---

## AD-6: Event-Driven Cross-Module Communication

**Decision**: Modules communicate via Event Bus, not direct imports.

**Rationale**:
- Maintains clean Module boundaries
- Allows asynchronous processing (finance recording doesn't need to wait for quest update)
- Easy to add new subscribers (adding a Bridge doesn't require changing Core)

**Event Format**:
```python
{
    "event_type": "finance.transaction.created",
    "space_id": "uuid",
    "payload": { ... },
    "timestamp": "2026-02-23T10:00:00Z",
    "source_module": "finance"
}
```

**Implementation Levels**:
1. **Phase 1**: In-process Event Bus (Python asyncio, sufficient until multi-worker)
2. **Phase 2**: Redis Pub/Sub (multi-process / multi-instance)
3. **Phase 3**: Consider NATS / RabbitMQ (if truly needed)

---

## AD-7: Progressive Complexity Pattern

**Decision**: All Modules follow the progressive complexity principle — start from the simplest form, then incrementally add features.

**Examples**:

| Module | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|--------|---------|---------|---------|---------|
| quest | Checkbox to-do | + Story points | + Skill requirements + Task pool | + Orders/quotation/acceptance |
| finance | Personal accounting | + Family shared ledger | + Budget/analysis | + Inventory/POS |
| matching | Manual pairing | + Conditional filtering | + AI recommendations | + Auto dispatch |
| memory | Manual memory | + Auto extraction | + Semantic search | + Cross-space isolation |

**Principles**:
- Each Phase is a usable, complete product — not a half-finished prototype
- Phase N+1 does not break Phase N's user experience
- Upgrades are opt-in, not forced (simple mode is always available)
