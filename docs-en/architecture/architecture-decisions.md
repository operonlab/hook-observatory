---
doc_version: 2
content_hash: 3525e4c7
source_version: 1
target_lang: en
translated_at: 2026-02-24
source_hash: 7cdf409d
source_lang: zh-TW
---

# Architecture Decisions

> Documents the core design decisions, rationale, and alternatives for the Workshop architecture.

---

## AD-1: Modular Monolith over Microservices

**Decision**: Adopt a Modular Monolith (single deployment unit + module boundaries) instead of Microservices.

**Rationale**:
- Solo development team (+AI) — the operational overhead of Microservices far outweighs its benefits.
- Modules require frequent data exchange; network hops would add unnecessary latency.
- A single `uv run` is sufficient to start — the development experience is far superior to using docker-compose to run 10+ services.
- If a specific Module genuinely needs independent scaling in the future, it can be extracted from the Monolith.

**Constraints**:
- Prohibit direct imports between Modules (only through Event Bus or Public API).
- Each Module has its own independent DB schema (schema isolation, not DB isolation).
- Cross-Module data queries must go through APIs — JOINS across Module tables are forbidden.

---

## AD-2: MCP Server as a Thin Adapter

**Decision**: Each Domain has its own independent MCP Server, but MCP Servers do not directly access the database — they call the FastAPI Core's REST API. MCP Server = HTTP Adapter.

**Rationale**:
- Claude Code requires an MCP interface to operate each Domain directly.
- If MCP Servers were to access the DB directly, they would bypass the Core's validation, events, and Hook logic.
- The Adapter pattern keeps MCP Servers lightweight; business logic is centralized in the Core.
- An MCP Server outage does not affect the Core; when the Core API changes, the MCP only needs to update its HTTP calls.

**Pattern**:
```
Claude Code ──► MCP Server ──► FastAPI Core ──► Database
                (adapter)       (business)       (persistence)
```

**Splitting Rules**:
- Each Domain is allocated at least 1 MCP Server.
- MCP Servers with more than 10 tools should be split (e.g., `workshop-quest-manage` + `workshop-quest-pool`).
- MCP Server tool naming convention: `{domain}_{action}` (e.g., `finance_add_transaction`).

**Existing MCP Servers**:
| Name | Tool Count |
|---|---|
| `workshop-finance` | 9 |
| `workshop-quest` | 10 |
| `workshop-muse` | 8 |
| `kas-memory` | 8 |

---

## AD-3: Space-Based Sharing Model

**Decision**: Adopt a Space-based sharing model instead of a traditional Multi-Tenant one.

**Rationale**:
- Traditional Multi-Tenancy assumes an organizational hierarchy (org → team → user), which doesn't fit the personal workstation scenario.
- Sharing in Workshop is flexible: one ledger entry might be shared with a spouse, while another task is shared with a friend.
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
- All data tables include a `space_id` column (added in Phase 0).
- `modules[]` controls which Modules a member can access within that Space.
- A user can belong to multiple Spaces simultaneously.
- Default: Every new user automatically gets a personal space.

---

## AD-4: Widget-Based Dashboard

**Decision**: The Dashboard adopts a Widget system instead of a traditional page-routed SPA.

**Rationale**:
- Core requirement: "Like Android home screen widgets — freely design my dashboard."
- Traditional SPA page switching = context switching; Widgets can display information from multiple Modules simultaneously.
- Widgets are composable, draggable, and resizable — offering more personalization than fixed pages.
- Each Module can provide multiple Widgets (different sizes, different functional facets).

**Technology Choices**:
| Technology | Choice | Rationale |
|---|---|---|
| Layout | `react-grid-layout` | A mature drag-and-drop grid solution. |
| Widget RWD | CSS Container Queries | Widgets adapt to their own size, not the screen size. |
| Cross-Widget Communication | Custom EventBus | Widget A emits an event → Widget B responds. |
| Widget Registry | JSON manifest | Each Module declares the Widgets it provides. |
| State Persistence | localStorage + Core API | Layout is stored in user preferences. |

**Widget Lifecycle**:
1. Module registers a Widget via manifest (type, sizes, default props).
2. User drags a Widget from the Gallery to the Dashboard.
3. Widget adjusts its layout based on the Container size.
4. Widget fetches data via the Core API.
5. Widgets communicate via the EventBus (e.g., clicking a finance transaction → quest displays related tasks).

**Widget Size Classes**:
- **Small** (1×1 ~ 2×1): Single data metric, quick action buttons.
- **Medium** (2×2 ~ 3×2): Lists, simple charts, forms.
- **Large** (4×2 ~ full width): Full-featured interfaces, complex charts, knowledge graphs.

---

## AD-5: Resource Abstraction

**Decision**: Unify human, machine, service, and AI agent into a single abstraction: a Resource.

**Rationale**:
- The quest's task dispatch needs to know "who can perform this task" — and this "who" is not necessarily a person.
- A task can be assigned to a human (manual), a machine (cron job), or an AI agent (Claude/Codex).
- A unified model allows the same nexus logic to be applied regardless of the resource type.
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
- **roster**: The Dashboard displays the load status of all resources.
- **quest dispatch**: Automatic matching based on task requirements × resource capabilities.

---

## AD-6: Event-Driven Cross-Module Communication

**Decision**: Modules communicate via an Event Bus, not direct imports.

For the full event format and specifications, see [event-driven.md](./event-driven.md).

**Rationale**:
- Maintains clear Module boundaries.
- Allows for asynchronous processing (finance recording doesn't need to wait for quest updates).
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

**Implementation Levels**:
1. **Phase 1**: In-process Event Bus (Python asyncio, sufficient before multi-worker setup).
2. **Phase 2**: Redis Streams (multi-process / multi-instance).
3. **Phase 3**: NATS JetStream.

---

## AD-7: Progressive Complexity Pattern

**Decision**: All Modules follow the principle of progressive complexity — starting from the simplest form and gradually adding features.

**Example**:

| Module | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|
| quest | Checkbox to-do | + Story points | + Skill requirements + Task pool | + Orders/quotation/acceptance |
| finance | Personal accounting | + Family shared ledger | + Budget/analysis | + Inventory/POS |
| nexus | Manual pairing | + Conditional filtering | + AI recommendations | + Auto dispatch |
| lore | Manual memory | + Auto extraction | + Semantic search | + Cross-space isolation |

**Principles**:
- Each Phase is a usable and complete product — not a half-finished prototype.
- Phase N+1 will not break the user experience of Phase N.
- Upgrades are optional (Opt-in), not mandatory (simple mode is always available).

---

## AD-8: Station SDK — Workstation Shared Layer

**Decision**: Common logic between Stations is extracted into `libs/python/station-sdk/` and provided as a lightweight SDK (not a framework).

**Rationale**:
- `system-monitor` and `llm-usage` have 4 overlapping pieces of logic: launchd scheduling, Core API push, Widget data format, and notification integration.
- If each station writes its own HTTP client and JSON format, maintenance costs grow linearly with the number of stations.
- However, the core value of stations is their ability to run independently; they cannot be forced to depend on the SDK.

**Design Principles**:

| Principle | Description |
|---|---|
| **SDK is an optional dependency** | Stations can run independently without the SDK (pure shell / pure Python). |
| **Convention over configuration** | SDK provides defaults (API endpoints, Widget formats); stations just need to fill in business logic. |
| **Not a framework** | SDK does not control the station's lifecycle, only provides callable utility functions. |
| **Extraction threshold: ≥ 2 users** | Logic is extracted to the SDK only when it is shared by 2 or more stations. |

**SDK Modules**:
```
libs/python/station-sdk/
├── api_client.py       ← Core API push (unified auth + endpoint discovery)
├── scheduler.py        ← launchd plist generation / management / frequency changes
├── widget_schema.py    ← Workbench Widget JSON standard format
└── notifier.py         ← Notification channel abstraction (connects to notification bridge)
```

**Relationship between Stations and SDK**:

| Station | Uses SDK | Description |
|---|:---:|---|
| system-monitor | ✅ | Uses everything: scheduling + API + Widget + notifications. |
| llm-usage | ✅ | API + Widget + notifications. |
| envkit | ❌ | Different nature as a CLI tool, no scheduling/Widget needs. |
| sandbox-executor | ❌ | Node.js MCP Server, different language. |

**Alternatives**:
- ❌ Each station implements independently → duplicate code, inconsistent formats.
- ❌ Station framework (forcing inheritance from `BaseStation` class) → over-engineering, limits flexibility.
- ✅ **Lightweight SDK (optional dependency utility library)** → balances sharing and independence.

---

## AD-9: Python-First + Selective Rust

**Decision**: The Core Monolith and most services use Python. Rust is used selectively only for CPU-bound hot-path scenarios.

**Rationale**:

| Factor | Python | Rust | Workshop Assessment |
|---|---|---|---|
| Development Speed (1 person + AI) | 3-5x faster | Slower | **Python wins** — A solo team's biggest bottleneck is development speed, not execution speed. |
| AI/ML Ecosystem | Native (LiteLLM, Anthropic SDK, etc.) | Second-class citizen | **Python wins** — Workshop heavily uses AI services. |
| AI Code Generation Quality | Claude/Codex's strongest language | Relatively weaker | **Python wins** — AI-assisted development is a core productivity driver. |
| I/O-bound Performance | async FastAPI ≈ Rust | Slightly ahead | **Tie** — Workshop's bottlenecks are in DB/network I/O. |
| CPU-bound Performance | Weak | Extremely strong (10-100x) | Rust wins — but Workshop has very few CPU-intensive operations. |
| Memory Usage | ~150-300MB | ~30-80MB | Rust wins — but Mac Mini 24GB is more than enough. |

**Division of Labor Strategy**:
```
Python is responsible for:           Rust is responsible for:
├── Core Monolith (FastAPI)        ├── Object Storage (RustFS — already in use)
├── MCP Servers (thin HTTP adapters) ├── Future: media transcoding hot-path
├── Stations (local tools)         └── Future: high-throughput batch processing
├── Event Bus
└── Bridges
```

**When to Consider Rust**:
- Performance profiling proves Python is the bottleneck (not DB/network).
- Concurrent users > 1000 (unlikely for a personal workstation).
- CPU-bound hot-path services (media processing, large-batch data computation).

**Alternatives**:
- ❌ Rewrite everything in Rust → Development speed drops 3-5x, AI ecosystem support is poor, limited benefits (small difference in I/O-bound scenarios).
- ❌ Go → Medium development speed, but AI/ML ecosystem is far behind Python.
- ✅ **Python-First + Selective Rust** → Maximize development speed, use Rust where performance is truly needed.
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3262ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3181ms
