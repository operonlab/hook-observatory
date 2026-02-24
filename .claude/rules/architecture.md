# Architecture Constraints

## Modular Monolith
- Single deployable unit: all 10 domain modules in one FastAPI process (port 8800)
- Two hot-path services run separately: realtime/LiveKit (8830), media/STT-TTS (8831)
- Frontend: single React app (workbench/, port 3000) — NO micro-frontend, NO Module Federation

## Module Boundaries (HARD RULES)
- Modules MUST NOT import another module's models.py or DB tables
- Modules MUST NOT write to another module's PostgreSQL schema
- Cross-module reads → call the target module's `services.py` (public API)
- Cross-module writes → publish events via EventBus, never direct DB writes
- Each module owns one PostgreSQL schema: module name = schema name

## 10 Core Modules

| Module | Domain | Phase |
|--------|--------|-------|
| auth | Authentication, sessions, spaces, permissions | 1 |
| finance | Transactions, budgets, subscriptions | 1 |
| taskflow | Quests, tasks, dispatch, rewards | 1 |
| ideagraph | Sparks, links, knowledge graph | 1 |
| admin | Platform management, audit logs | 1 |
| intelflow | RSS feeds, daily briefings | 2 |
| memvault | LLM memories, semantic search | 2 |
| skillpath | Skill trees, learning paths | 2 |
| workpool | Resources, scheduling, capacity | 3 |
| matchcore | Talent-job matching, scoring | 3 |

## Event-Driven Rules
- Naming: `{module}.{entity}.{past_tense}` (e.g., `finance.transaction.created`)
- Events are immutable — once published, data never changes
- Handlers MUST be idempotent — processing same event twice = no side effects
- Fire-and-forget — if you need a response, use service imports instead
- Keep payloads lean: IDs + essential data only; fetch full records via service imports

## Service Taxonomy
- **Core Modules** (DB-backed): auth, finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore, admin
- **Stations** (`stations/`): standalone local tools, no Core DB dependency
- **Bridges** (`bridges/`): external platform connectors (LINE, Telegram, Discord)
- **MCP adapters** (`mcp/`): thin wrappers over Core API — NEVER touch DB directly
- **Vendor** (`vendor/`): third-party tools, used as-is, no modification

## Key Design Principles
- KISS: modular monolith > microservices (solo team)
- YAGNI: don't build for hypothetical future needs
- Prefer Existing: mature OSS > custom build (RustFS, LiveKit, react-grid-layout)
- MVP: each phase is a complete, usable product
- Composition > Inheritance: Service = BaseCRUD + EventBus + Permission
