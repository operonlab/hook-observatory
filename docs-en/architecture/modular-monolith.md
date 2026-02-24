---
doc_version: 3
content_hash: 87cf60a6
source_version: 3
target_lang: en
translated_at: 2026-02-24
source_hash: ea165cf9
source_lang: zh-TW
---

# Modular Monolith Architecture Guide

## Design Principles

### 1. Single Deployment & Module Boundaries

The backend is a **single deployable unit** with clearly separated domain modules. Each module owns its business logic, database schema, and API routes—but they all run in the same process.

```
                    ┌─────────────────────────────────────┐
                    │          Core Monolith (port 8800)   │
                    │                                     │
                    │  ┌────────┐ ┌────────┐ ┌────────┐  │
                    │  │  auth  │ │finance │ │  quest │  │
                    │  └────────┘ └────────┘ └────────┘  │
                    │  ┌────────┐ ┌────────┐ ┌────────┐  │
                    │  │  muse  │ │ scout  │ │  lore  │  │
                    │  └────────┘ └────────┘ └────────┘  │
                    │  ┌────────┐ ┌────────┐ ┌────────┐  │
                    │  │  dojo  │ │ roster │ │ nexus  │  │
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

**Why choose a modular monolith over microservices:**
- Simpler deployment and operations (one process, one container)
- No network latency between modules (in-process calls)
- Easier debugging and tracing (single log stream)
- Module boundaries enforce development discipline without operational overhead
- A module can be easily extracted into a microservice later if it truly needs to scale independently

### 2. Module Ownership

Each module owns **one** business domain:

| Module | Owns | Database Schema | Phase |
|--------|------|-----------------|-------|
| `auth` | Users, sessions, spaces, permissions | `auth` | 1 |
| `finance` | Transactions, budgets, subscriptions | `finance` | 1 |
| `quest` | Quests, tasks, dispatch, rewards | `quest` | 1 |
| `muse` | Sparks, links, knowledge graph | `muse` | 1 |
| `scout` | RSS feeds, daily briefings, topic tracking | `scout` | 2 |
| `lore` | LLM memories, semantic search, profiles | `lore` | 2 |
| `dojo` | Skill trees, learning paths, assessments | `dojo` | 2 |
| `roster` | Resources (human/machine/agent), scheduling | `roster` | 3 |
| `nexus` | Talent-job matching, task pairing | `nexus` | 3 |
| `admin` | Platform management, audit logs, system health | `admin` | 1 |

### 3. Module Boundary Rules

**Hard Rules:**
- A module **must not** directly import another module's models or database tables
- A module **must not** write directly to another module's schema
- Cross-module reads happen via **service imports** (calling another module's service layer)
- Cross-module state changes happen via the **Event Bus**

```python
# Correct: Module A reads Module B's data via a service import
from src.modules.finance.services import get_user_balance

# Correct: Module A notifies Module B via an event
await event_bus.publish("quest.quest.completed", {"quest_id": "...", "user_id": "..."})

# Incorrect: Module A directly imports Module B's models
from src.modules.finance.models import Transaction  # Forbidden
```

### 4. Independent Data Storage

All modules share a single PostgreSQL instance but use **separate schemas**:

```sql
CREATE SCHEMA auth;       -- Owned by auth module (Phase 1)
CREATE SCHEMA finance;    -- Owned by finance module (Phase 1)
CREATE SCHEMA quest;      -- Owned by quest module (Phase 1)
CREATE SCHEMA muse;       -- Owned by muse module (Phase 1)
CREATE SCHEMA scout;      -- Owned by scout module (Phase 2)
CREATE SCHEMA lore;       -- Owned by lore module (Phase 2)
CREATE SCHEMA dojo;       -- Owned by dojo module (Phase 2)
CREATE SCHEMA roster;     -- Owned by roster module (Phase 3)
CREATE SCHEMA nexus;      -- Owned by nexus module (Phase 3)
CREATE SCHEMA admin;      -- Owned by admin module (Phase 1)
```

Cross-schema queries are technically possible, but **architecturally forbidden**. If Module A needs data from Module B, it must call B's service layer.

## Module Structure

Each module follows a consistent internal layout:

```
core/src/modules/<name>/
├── __init__.py          # Module registration
├── routes.py            # FastAPI routes (or routes/ directory)
├── models.py            # SQLAlchemy / Pydantic models (module-scoped)
├── schemas.py           # Pydantic request/response schemas
├── services.py          # Business logic (this module's public API)
├── events.py            # Event handlers (subscribers)
├── hooks.py             # Hook points exposed by this module
└── deps.py              # FastAPI dependencies
```

`services.py` is the **public interface** of each module. Other modules should import from here, and never from `models.py` or `routes.py`.

## Inter-Module Communication

| Pattern | When to Use | Example |
|---------|------|---------|
| Service Import (Sync) | Reading data from another module | `finance.services.get_balance(user_id)` |
| Event Bus (Async) | State change that other modules may care about | `quest.quest.completed` triggers finance reward |
| Shared types in `src.shared` | Common types used by 2+ modules | `UserId`, `Pagination`, `ErrorResponse` |

See [Event-Driven Architecture](./event-driven.md) for detailed event patterns.

## Hot-Path Services

Two services run **outside** the monolith because they have fundamentally different runtime needs:

### Realtime Service (port 8830)

- **Functionality**: LiveKit WebRTC gateway + agents
- **Why separate**: WebRTC requires persistent connections, media processing, and different scaling patterns
- **Communication method**: REST API for token generation, and Redis events for state sync

### Media Service (port 8831)

- **Functionality**: STT, TTS, image processing pipelines
- **Why separate**: CPU/GPU intensive, requires independent resource allocation
- **Communication method**: HTTP API calls from core, with results published as events

## Port Allocation

| Port | Service |
|------|---------|
| 8800 | Core Monolith |
| 8830 | Realtime Service (LiveKit) |
| 8831 | Media Service (STT/TTS) |
| 3000 | Frontend Dev Server |

## Configuration

Uses `pydantic-settings` with environment variables. Module-specific configs use prefixed environment variables:

```python
from pydantic_settings import BaseSettings

class CoreSettings(BaseSettings):
    port: int = 8800
    db_url: str = "postgresql://localhost/workshop"
    redis_url: str = "redis://localhost:6379"
    debug: bool = False

    model_config = {"env_prefix": "CORE_"}
```

## Health Checks

The monolith exposes a single health check endpoint that includes the status of its modules:

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
    "scout": "healthy",
    "lore": "healthy",
    "dojo": "healthy",
    "roster": "healthy",
    "nexus": "healthy",
    "admin": "healthy"
  }
}
```

## Module Registration

Modules register themselves with the core application on startup:

```python
# core/src/app.py
from src.modules import auth, finance, quest, muse, scout, lore, dojo, roster, nexus, admin

def create_app() -> FastAPI:
    app = FastAPI()

    # Register module routes (Phase 1)
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(finance.router, prefix="/api/finance", tags=["finance"])
    app.include_router(quest.router, prefix="/api/quest", tags=["quest"])
    app.include_router(muse.router, prefix="/api/muse", tags=["muse"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

    # Register module routes (Phase 2)
    app.include_router(scout.router, prefix="/api/scout", tags=["scout"])
    app.include_router(lore.router, prefix="/api/lore", tags=["lore"])
    app.include_router(dojo.router, prefix="/api/dojo", tags=["dojo"])

    # Register module routes (Phase 3)
    app.include_router(roster.router, prefix="/api/roster", tags=["roster"])
    app.include_router(nexus.router, prefix="/api/nexus", tags=["nexus"])

    # Initialize Event Bus and Hook Engine
    app.state.event_bus = EventBus()
    app.state.hook_engine = HookEngine()

    # Register module event handlers
    auth.register_events(app.state.event_bus)
    finance.register_events(app.state.event_bus)
    quest.register_events(app.state.event_bus)

    return app
```

## Future Vision: Extracting a Module

If a module outgrows the monolith (e.g., media processing needs GPU scaling), the extraction path is:

1. The module already has clear boundaries (service layer, events, no cross-model imports)
2. Replace in-process service imports with HTTP client calls
3. Replace in-process events with Redis Streams events
4. Deploy as a separate service
5. Other modules require no changes (they already use the service/event interface)

This is the core benefit of enforcing module boundaries from day one.
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2497ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3357ms
