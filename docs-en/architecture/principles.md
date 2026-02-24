---
doc_version: 4
content_hash: eccf4c8d
source_version: 4
target_lang: en
translated_at: 2026-02-24
source_hash: 0933f100
source_lang: zh-TW
---

# Workshop Design Principles

> The design principles adopted by Workshop—from SOLID and GoF to modern practices. Each principle is noted with its specific application within Workshop.
> They are divided into three levels: **Core** (to be kept in mind at all times during development), **Applied** (to be consulted when making design decisions), and **Reference** (to be looked up when needed).

---

## Level 1: Core — To be kept in mind at all times during development

> These 10 principles are the guiding pillars of daily development in Workshop. Violating any of them is worth a pause for reconsideration.

### 1. SRP — Single Responsibility Principle

> A module should do one thing, and have only one reason to change.

**Workshop Application**: Each Domain Service manages a single business domain. `finance` only handles money, `quest` only handles tasks. Cross-domain logic flows through the Event Bus—it is not crammed into a single module.

### 2. DRY — Don't Repeat Yourself (+ Rule of Three)

> Write the same logic only once. But tolerate the first two repetitions—abstract on the third occurrence.

**Workshop Application**: `BaseCRUDService<M,C,U,R>` eliminates CRUD duplication across 39 entities. The frontend `createCrudApi<T,C,U>` follows the same principle. But do not force the creation of helpers for logic that appears only once.

### 3. KISS — Keep It Simple, Stupid

> The simplest solution is often the best.

**Workshop Application**: Modular Monolith > Microservices (a one-person team does not need distributed complexity). In-process Event Bus > Redis Pub/Sub (sufficient for Phase 1).

### 4. YAGNI — You Aren't Gonna Need It

> Do not develop for hypothetical future needs.

**Workshop Application**: The technical foundation of Progressive Complexity. The `quest` in Phase 1 is just a checklist—no need to pre-build a task pool scheduling engine. Each Phase is a complete, usable product.

### 5. SSOT — Single Source of Truth

> Every piece of data has one and only one authoritative source.

**Workshop Application**:
- The Space model is the single source of truth for shared scope.
- The Event Bus is the only channel for propagating state changes.
- PostgreSQL's schema-per-module prevents data from being scattered in multiple locations.

### 6. SoC — Separation of Concerns

> Different concerns should be strictly separated—do not mix them.

**Workshop Application**: Module boundary = concern boundary. `core/src/shared/` stores code shared across modules, `core/src/modules/{name}/` stores module-specific code. Route handlers only handle HTTP protocol, Services only handle business logic, Models only manage data structures.

### 7. Fail Fast

> Expose errors as early as possible—never swallow them silently.

**Workshop Application**: The `WorkshopError` hierarchy ensures all errors surface immediately. `before_create()` hooks perform validation before writing to the database. The frontend API client uses a global error interceptor for unified handling.

### 8. Composition > Inheritance

> Prefer composition over inheritance for behavior reuse.

**Workshop Application**: Service = BaseCRUD (inheritance) + EventBus (composition) + Permission (composition). Widget = ModuleLayout (composition) + data hook (composition) + render component (composition). Composition Recipes themselves are a manifestation of service composition.

### 9. Loose Coupling + High Cohesion

> Minimize dependencies between modules; keep the content within a module highly related.

**Workshop Application**:
- Loose Coupling: Modules communicate only through the Event Bus (write) or Public API (read)—direct imports are forbidden.
- High Cohesion: Within each module, models/schemas/service/routes all serve the same business domain closely.

### 10. MVP — Minimum Viable Product

> The minimum viable version that can validate a hypothesis.

**Workshop Application**: Each Phase is an MVP. The `quest` in Phase 1 is just a checkbox—if it works, it's a success. Don't strive for "perfect"—strive for "validating the core hypothesis."

### 11. Prefer Existing Solutions

> If someone has already built the wheel, just use it. Only consider building your own if it's too big, too small, or doesn't meet the needs.

**Workshop Application**:
- **Priority**: Mature open-source solution > Lightweight wrapper > In-house development
- RustFS (a MinIO community fork) is used for object storage, not a self-built S3-compatible layer.
- LiveKit is used for WebRTC, not a self-built signaling server.
- `react-grid-layout` is used for Widget drag-and-drop, not a self-built grid system.
- **Regular Review**: At the end of each Phase, review—are there new mature solutions that can replace current self-built components?
- **Counter-example**: T1/T2 tried to build too many things from scratch, leading to a full rollback and rewrite.

---

## Level 2: Applied — To be consulted when making design decisions

> These principles need to be explicitly considered when making architectural or design decisions.

### Remaining SOLID Principles

| Principle | Workshop Application |
|-----------|---------------------|
| **OCP** (Open/Closed) | Plugin system: Adding a new Plugin does not require modifying the Core. New modules are attached to the Event Bus without changing existing modules. |
| **LSP** (Liskov Substitution) | `BridgeAdapter` ABC: LINE/Telegram/Discord adapters are completely interchangeable. |
| **ISP** (Interface Segregation) | Each MCP Server only exposes the tools for its Domain—it doesn't force implementation of unrelated interfaces. |
| **DIP** (Dependency Inversion) | Services depend on Repository interfaces, not directly on the PostgreSQL driver. |

### Architectural Principles

| Principle | Workshop Application |
|-----------|---------------------|
| **Bounded Context** (DDD) | Each Module = a bounded context with its own "language" and data model. |
| **Event-Driven** | Modules communicate via events. `quest` can subscribe to `finance.transaction.created`. |
| **Idempotency** | Event handlers must be idempotent—receiving the same event twice does not produce duplicate effects. |
| **Progressive Disclosure** | MCP tools are loaded on-demand (ToolSearch), not stuffed into the system prompt. |
| **12-Factor App** | Configuration in environment variables (`.env`), stateless services, port binding, dev/prod parity. |
| **CoC** (Convention over Config) | Modules follow a uniform file structure: `models.py`, `schemas.py`, `service.py`, `routes.py`. |
| **PoLA** (Principle of Least Astonishment) | API behavior follows REST conventions; event naming `{module}.{entity}.{action}` is intuitive. |
| **Defensive Programming** | Boundary validation in `before_create()`; external input is never trusted. |

### Design Patterns in Workshop

| Pattern | Usage Location |
|---------|-----------|
| **Template Method** | `BaseCRUDService` hooks: `before_create()`, `after_create()`, `to_response()` |
| **Adapter** | `BridgeAdapter` (LINE/Telegram/Discord), MCP Server (HTTP adapter connecting to Core API) |
| **Observer / Pub-Sub** | Event Bus—modules subscribe to events from other modules. |
| **Strategy** | LLM provider switching (OpenAI ↔ Ollama), embedding model selection. |
| **Factory** | `createCrudApi<T,C,U>(basePath)`—creates a frontend API client in one line of code. |
| **Facade** | MCP Server = a simplified facade for the Core API; Dashboard = a unified container for Widgets. |
| **State** | Quest state machine: `pending → active → completed → cancelled` |
| **Registry** | Error code registry: `ERROR_REGISTRY` dictionary → `GET /api/meta/error-codes` |
| **Singleton** | DB connection pool, Redis client. |
| **Proxy** | API Gateway—handles auth/rate-limit at the proxy layer. |
| **Mediator** | Using the Event Bus as a mediator between modules. |

---

## Level 3: Reference — To be looked up when needed

> These principles/patterns are useful in specific scenarios but are not essential for daily development.

### Future Considerations

| Principle | When Relevant |
|-----------|---------------|
| **CQRS** | Phase 3+ — Separate read/write models or databases (if read/write pressure diverges significantly). |
| **CAP Theorem** | Multi-instance deployment—choose two out of Consistency, Availability, and Partition tolerance. |
| **Eventually Consistent** | Multi-instance + cross-service synchronization—trade immediate consistency for eventual convergence. |
| **Strangler Fig** | Gradual migration from V1 to V2 (we chose a rewrite, so not currently applicable). |
| **Anti-Corruption Layer** | When integrating with external legacy APIs (e.g., government open data, old system adapters). |

### Remaining GoF Patterns (for reference)

| Category | Pattern | Potential Use |
|----------|----------|---------------|
| **Creational** | Builder, Prototype | Builder: complex query assembly; Prototype: deep copying of configurations. |
| **Structural** | Composite, Bridge, Flyweight, Decorator | Composite: Widget tree; Decorator: `@authenticate`. |
| **Behavioral** | Command, Chain of Responsibility, Iterator, Visitor, Memento | Command: undo/redo; CoR: middleware pipeline; Memento: version rollback. |

### Testing Principles

| Principle | Application |
|-----------|-------------|
| **Test Pyramid** | Many unit tests → some integration tests → very few end-to-end tests. |
| **AAA Pattern** | Arrange → Act → Assert. |
| **Test Isolation** | Each test is independent—does not depend on execution order. |
| **Real Verification** | Prefer real execution over mock/smoke tests. |

### Modern / AI Era (2024-2026)

| Principle | Application |
|-----------|-------------|
| **AI-Augmented Dev** | Claude Code + Skills assist development; humans review AI-generated code. |
| **Prompt-as-Code** | `SKILL.md` / `agents/*.md` as version-controlled prompt management. |
| **Minimal Tool Surface** | MCP Servers only expose the necessary minimal tools (fewer than 10 per server). |
| **Blast Radius Isolation** | The impact of each module's failure is contained (schema isolation, independent event handlers). |
| **Infrastructure as Code** | Docker Compose, Nginx configurations are all version-controlled. |
| **Observability > Monitoring** | OpenTelemetry tracing + structured logging (built from Phase 1). |

---

## Quick Reference Card

```
11 Core Principles for Daily Development:

 1. SRP           — A module should do one thing.
 2. DRY           — Don't repeat the same logic (abstract on the third time).
 3. KISS          — The simplest solution is often the best.
 4. YAGNI         — Don't write code for hypothetical needs.
 5. SSOT          — Every piece of data has one authoritative source.
 6. SoC           — Strictly separate different concerns.
 7. Fail Fast     — Expose errors immediately.
 8. Composition > Inheritance — Prefer composition over inheritance.
 9. Loose Coupling + High Cohesion — Low coupling between modules, high cohesion within.
10. MVP           — Build the minimum viable version to validate a hypothesis.
11. Prefer Existing — Use wheels others have built, unless they don't fit.
```
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2779ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2743ms
