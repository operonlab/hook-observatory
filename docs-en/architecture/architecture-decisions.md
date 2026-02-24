---
doc_version: 2
content_hash: 3525e4c7
source_version: 1
target_lang: en
translated_at: 2026-02-24
source_hash: 3525e4c7
source_lang: zh-TW
---

# Architecture Decisions

> Documents the core design decisions, rationale, and alternatives for the Workshop architecture.

---

## AD-1: Modular Monolith over Microservices

**Decision**: Adopt a Modular Monolith (single deployment unit + module boundaries), rather than Microservices.

**Rationale**:
- Single developer team (+AI) — the operational overhead of Microservices far outweighs its benefits.
- Modules require frequent data exchange; network hops would add unnecessary latency.
- A single `uv run` is all it takes to start — a far superior developer experience compared to running 10+ services with docker-compose.
- If a specific Module does require independent scaling in the future, it can be extracted from the Monolith then.

**Constraints**:
- Prohibit direct imports between Modules (only via Event Bus or Public API).
- Each Module has its own independent DB schema (schema isolation, not DB isolation).
- Cross-Module data queries must go through an API — JOINs across Module tables are forbidden.

---

## AD-2: MCP Server as a Thin Adapter

**Decision**: Each Domain has its own MCP Server, but the MCP Servers do not directly access the database—
they call the FastAPI Core's REST API. MCP Server = HTTP Adapter.

**Rationale**:
- Claude Code needs an MCP interface to directly operate on each Domain.
- If MCP Servers were to access the DB directly, they would bypass the Core's validation, events, and Hook logic.
- The Adapter pattern keeps the MCP Servers lightweight; business logic is centralized in the Core.
- An MCP Server outage does not affect the Core; when the Core API changes, the MCP only needs to update its HTTP calls.

**Pattern**:
```
Claude Code ──► MCP Server ──► FastAPI Core ──► Database
                (adapter)       (business)       (persistence)
```

**Partitioning Rules**:
- Assign at least 1 MCP Server to each Domain.
- MCP Servers with more than 10 tools should be split (e.g., `workshop-quest-manage` + `workshop-quest-pool`).
- MCP Server tool naming convention: `{domain}_{action}` (e.g., `finance_add_transaction`).

**Existing MCP Servers**:
| Name | Tool Count |
|-------------|------------|
| `workshop-finance` | 9 |
| `workshop-quest` | 10 |
| `workshop-muse` | 8 |
| `kas-memory` | 8 |

---

## AD-3: Space-Based Sharing Model

**Decision**: Adopt a Space-based sharing model, rather than traditional Multi-Tenancy.

**Rationale**:
- Traditional Multi-Tenancy assumes an organizational hierarchy (org → team → user), which doesn't fit the personal workstation scenario.
- Sharing in Workshop is flexible: a ledger entry might be shared with a spouse, while another task is shared with a friend.
- A Space is a "sharing scope" — it can be personal / family / friends / org.
- Different Modules can be enabled/disabled independently for each Space.

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

**Design Highlights**:
- All data tables will include a `space_id` column (added in Phase 0).
- `modules[]` controls which Modules a member can access within that Space.
- A user can belong to multiple Spaces simultaneously.
- Default: Every new user automatically gets a personal space.

---

## AD-4: Widget-Based Dashboard

**Decision**: The Dashboard will use a Widget system, not a traditional page-routed SPA.

**Rationale**:
- Core requirement: "Like Android home screen widgets — freely design my dashboard".
- Traditional SPA page switching = context switching; Widgets can display information from multiple Modules at the same time.
- Widgets are composable, draggable, and resizable — more personalizable than fixed pages.
- Each Module can provide multiple Widgets (different sizes, different functional facets).

**Technology Choices**:
| Technology | Choice | Rationale |
|-----------|--------|-----------|
| Layout | `react-grid-layout` | A mature drag-and-drop grid solution |
| Widget RWD | CSS Container Queries | Widgets adapt to their own size, not the screen size |
| Cross-Widget Communication | Custom EventBus | Widget A emits an event → Widget B responds |
| Widget Registry | JSON manifest | Each Module declares the Widgets it provides |
| State Persistence | localStorage + Core API | Layout is stored in user preferences |

**Widget Lifecycle**:
1. A Module registers a Widget via its manifest (type, sizes, default props).
2. The user drags a Widget from the Gallery to the Dashboard.
3. The Widget adjusts its layout based on its Container size.
4. The Widget fetches data via the Core API.
5. Widgets communicate via the EventBus (e.g., clicking a finance transaction → quest shows related tasks).

**Widget Size Classes**:
- **Small** (1×1 ~ 2×1): Single data points, quick action buttons.
- **Medium** (2×2 ~ 3×2): Lists, simple charts, forms.
- **Large** (4×2 ~ full width): Full-featured interfaces, complex charts, knowledge graphs.

---

## AD-5: Resource Abstraction

**Decision**: Abstract human, machine, service, and AI agent into a single, unified Resource.

**Rationale**:
- Quest's task dispatch needs to know "who can perform this task" — and that "who" isn't necessarily a person.
- A task can be assigned to a human (manual), a machine (cron job), or an AI agent (Claude/Codex).
- A unified model allows the same nexus logic to be applied regardless of resource type.
- Lays the foundation for future ERP scenarios (machine capacity, personnel hours, AI agent parallelism).

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
- **nexus**: `SELECT * FROM resources WHERE capabilities @> ARRAY['python'] AND current_load < capacity`
- **roster**: Dashboard displays the load status of all resources.
- **quest dispatch**: Automatic matching based on task requirements × resource capabilities.

---

## AD-6: Event-Driven Cross-Module Communication

**Decision**: Modules communicate via an Event Bus, not direct imports.

For the full event format and specification, see [event-driven.md](./event-driven.md).

**Rationale**:
- Maintains clear Module boundaries.
- Allows for asynchronous processing (finance records don't need to wait for quest updates).
- Easy to add new subscribers (adding a Bridge doesn't require modifying the Core).

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

**Implementation Phases**:
1. **Phase 1**: In-process Event Bus (Python asyncio, sufficient before multi-worker setup).
2. **Phase 2**: Redis Streams (multi-process / multi-instance).
3. **Phase 3**: NATS JetStream.

---

## AD-7: Progressive Complexity Pattern

**Decision**: All Modules follow the progressive complexity principle—starting from the simplest form and then gradually adding features.

**Example**:

| Module | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|--------|---------|---------|---------|---------|
| quest | Checkbox to-do | + Story points | + Skill requirements + Task pool | + Orders/quotation/acceptance |
| finance | Personal accounting | + Family shared ledger | + Budget/analysis | + Inventory/POS |
| nexus | Manual pairing | + Conditional filtering | + AI recommendations | + Auto dispatch |
| lore | Manual memory | + Auto extraction | + Semantic search | + Cross-space isolation |

**Principles**:
- Each Phase is a usable and complete product — not a half-finished prototype.
- Phase N+1 will not break the user experience of Phase N.
- Upgrades are optional (Opt-in), not mandatory (simple mode is always available).
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2727ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2588ms
