---
doc_version: 3
content_hash: 87cf60a6
---

# Modular Monolith Architecture Guide

## Design Principles

### 1. Single Deployment, Module Boundaries

The backend is a **single deployable unit** with clearly separated domain modules. Each module owns its business logic, database schema, and API routes -- but they all run in one process.

```
                    ┌─────────────────────────────────────┐
                    │          Core Monolith (port 8800)   │
                    │                                     │
                    │  ┌────────┐ ┌────────┐ ┌────────┐  │
                    │  │  auth  │ │finance │ │  quest │  │
                    │  └────────┘ └────────┘ └────────┘  │
                    │  ┌────────┐ ┌────────┐ ┌────────┐  │
                    │  │  muse  │ │ intel  │ │ memory │  │
                    │  └────────┘ └────────┘ └────────┘  │
                    │  ┌────────┐ ┌────────┐ ┌────────┐  │
                    │  │ skill  │ │workfrc │ │matching│  │
                    │  └────────┘ └────────┘ └────────┘  │
                    │  ┌────────┐                        │
                    │  │ admin  │                        │
                    │  └────────┘                        │
                    │                                     │
                    │  ┌─────────────────────────────┐    │
                    │  │  Event Bus  │  Hook Engine  │    │
                    │  └─────────────────────────────┘    │
                    └─────────────────────────────────────┘
                              │            │
                    ┌─────────┴──┐   ┌─────┴────────┐
                    │  Realtime  │   │    Media      │
                    │  (LiveKit) │   │  (STT/TTS)   │
                    │  port 8830 │   │  port 8831   │
                    └────────────┘   └──────────────┘
```

**Why Modular Monolith over Microservices:**
- Simpler deployment and operations (one process, one container)
- No network latency between modules (in-process calls)
- Easier debugging and tracing (single log stream)
- Module boundaries enforce discipline without operational overhead
- Can extract to microservices later if a module truly needs independent scaling

### 2. Module Ownership

Each module owns **one** business domain:

| Module | Owns | Database Schema | Phase |
|--------|------|-----------------|-------|
| `auth` | Users, sessions, spaces, permissions | `auth` | 1 |
| `finance` | Transactions, budgets, subscriptions | `finance` | 1 |
| `quest` | Quests, tasks, dispatch, rewards | `quest` | 1 |
| `muse` | Sparks, links, knowledge graph | `muse` | 1 |
| `intel` | RSS feeds, daily briefings, topic tracking | `intel` | 2 |
| `memory` | LLM memories, semantic search, profiles | `memory` | 2 |
| `skill` | Skill trees, learning paths, assessments | `skill` | 2 |
| `workforce` | Resources (human/machine/agent), scheduling | `workforce` | 3 |
| `matching` | Talent-job matching, task pairing | `matching` | 3 |
| `admin` | Platform management, audit logs, system health | `admin` | 1 |

### 3. Module Boundary Rules

**Hard rules:**
- A module **must not** directly import another module's models or database tables
- A module **must not** directly write to another module's schema
- Cross-module reads go through **service imports** (call the other module's service layer)
- Cross-module state changes go through the **Event Bus**

```python
# GOOD: Module A reads from Module B via service import
from src.modules.finance.services import get_user_balance

# GOOD: Module A notifies Module B via event
await event_bus.publish("quest.quest.completed", {"quest_id": "...", "user_id": "..."})

# BAD: Module A directly imports Module B's models
from src.modules.finance.models import Transaction  # FORBIDDEN
```

### 4. Independent Data Stores

All modules share one PostgreSQL instance but use **separate schemas**:

```sql
CREATE SCHEMA auth;       -- owned by auth module (Phase 1)
CREATE SCHEMA finance;    -- owned by finance module (Phase 1)
CREATE SCHEMA quest;      -- owned by quest module (Phase 1)
CREATE SCHEMA muse;       -- owned by muse module (Phase 1)
CREATE SCHEMA intel;      -- owned by intel module (Phase 2)
CREATE SCHEMA memory;     -- owned by memory module (Phase 2)
CREATE SCHEMA skill;      -- owned by skill module (Phase 2)
CREATE SCHEMA workforce;  -- owned by workforce module (Phase 3)
CREATE SCHEMA matching;   -- owned by matching module (Phase 3)
CREATE SCHEMA admin;      -- owned by admin module (Phase 1)
```

Cross-schema queries are technically possible but **architecturally forbidden**. If Module A needs data from Module B, it calls B's service layer.

## Module Structure

Each module follows a consistent internal layout:

```
core/src/modules/<name>/
├── __init__.py          # Module registration
├── routes.py            # FastAPI router (or routes/ directory)
├── models.py            # SQLAlchemy / Pydantic models (module-scoped)
├── schemas.py           # Pydantic request/response schemas
├── services.py          # Business logic (the public API of this module)
├── events.py            # Event handlers (subscribers)
├── hooks.py             # Hook points this module exposes
└── deps.py              # FastAPI dependencies
```

The `services.py` is the **public interface** of each module. Other modules import from here, never from `models.py` or `routes.py`.

## Inter-Module Communication

| Pattern | When | Example |
|---------|------|---------|
| Service import (sync) | Reading data from another module | `finance.services.get_balance(user_id)` |
| Event Bus (async) | State change that others may care about | `quest.quest.completed` triggers finance reward |
| Shared types in `src.shared` | Common types used by 2+ modules | `UserId`, `Pagination`, `ErrorResponse` |

See [Event-Driven Architecture](./event-driven.md) for detailed event patterns.

## Hot-Path Services

Two services run **outside** the monolith because they have fundamentally different runtime requirements:

### Realtime Service (port 8830)

- **What**: LiveKit WebRTC gateway + agents
- **Why separate**: WebRTC requires persistent connections, media processing, different scaling pattern
- **Communication**: REST API for token generation, Redis events for state sync

### Media Service (port 8831)

- **What**: STT, TTS, image processing pipelines
- **Why separate**: CPU/GPU intensive, needs independent resource allocation
- **Communication**: HTTP API calls from core, results published as events

## Port Allocation

| Port | Service |
|------|---------|
| 8800 | Core Monolith |
| 8830 | Realtime (LiveKit) |
| 8831 | Media (STT/TTS) |
| 3000 | Frontend dev server |

## Configuration

Use `pydantic-settings` with environment variables. Module-specific config uses prefixed env vars:

```python
from pydantic_settings import BaseSettings

class CoreSettings(BaseSettings):
    port: int = 8800
    db_url: str = "postgresql://localhost/workshop"
    redis_url: str = "redis://localhost:6379"
    debug: bool = False

    model_config = {"env_prefix": "CORE_"}
```

## Health Check

The monolith exposes a single health endpoint with per-module status:

```json
{
  "status": "healthy",
  "service": "core",
  "version": "0.1.0",
  "modules": {
    "auth": "healthy",
    "finance": "healthy",
    "quest": "healthy",
    "muse": "healthy",
    "intel": "healthy",
    "memory": "healthy",
    "skill": "healthy",
    "workforce": "healthy",
    "matching": "healthy",
    "admin": "healthy"
  }
}
```

## Module Registration

Modules register themselves with the core application at startup:

```python
# core/src/app.py
from src.modules import auth, finance, quest, muse, intel, memory, skill, workforce, matching, admin

def create_app() -> FastAPI:
    app = FastAPI()

    # Register module routers (Phase 1)
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(finance.router, prefix="/api/finance", tags=["finance"])
    app.include_router(quest.router, prefix="/api/quest", tags=["quest"])
    app.include_router(muse.router, prefix="/api/muse", tags=["muse"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

    # Register module routers (Phase 2)
    app.include_router(intel.router, prefix="/api/intel", tags=["intel"])
    app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
    app.include_router(skill.router, prefix="/api/skill", tags=["skill"])

    # Register module routers (Phase 3)
    app.include_router(workforce.router, prefix="/api/workforce", tags=["workforce"])
    app.include_router(matching.router, prefix="/api/matching", tags=["matching"])

    # Initialize event bus and hook engine
    app.state.event_bus = EventBus()
    app.state.hook_engine = HookEngine()

    # Register module event handlers
    auth.register_events(app.state.event_bus)
    finance.register_events(app.state.event_bus)
    quest.register_events(app.state.event_bus)

    return app
```

## Future: Extracting a Module

If a module outgrows the monolith (e.g., media processing needs GPU scaling), the extraction path is:

1. Module already has clean boundaries (service layer, events, no cross-model imports)
2. Replace in-process service imports with HTTP client calls
3. Replace in-process events with Redis Streams events
4. Deploy as independent service
5. No changes needed in other modules (they already use the service/event interface)

This is the key advantage of enforcing module boundaries from day one.
