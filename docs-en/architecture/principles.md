---
doc_version: 3
content_hash: 2ab57e6f
source_version: 3
translated_at: 2026-02-23
---

# Workshop Design Principles

> Design principles adopted by the Workshop — from SOLID to GoF to modern practices, each annotated with specific applications within the Workshop.
> Divided into three levels: **Core** (always on the mind during development), **Applied** (referenced during design decisions), **Reference** (consulted when needed).

---

## Tier 1: Core — Always on the mind during development

> These 10 principles are the ultimate guidance for the Workshop's daily development. If any are violated, one should stop and reflect.

### 1. SRP — Single Responsibility

> A module should do only one thing and have only one reason to change.

**Workshop Application**: Each Domain Service handles only one business domain. `finance` only handles finance, `quest` only handles tasks. Cross-domain logic goes through the Event Bus and is not crammed into a specific module.

### 2. DRY — Don't Repeat Yourself (+ Rule of Three)

> Write a piece of logic only once. However, repetition can be tolerated for the first two times; abstract on the third.

**Workshop Application**: `BaseCRUDService<M,C,U,R>` eliminates CRUD repetition for 39 entities. The frontend `createCrudApi<T,C,U>` follows the same principle. But we don't force helpers for logic that only appears once.

### 3. KISS — Keep It Simple, Stupid

> Prefer simplicity over complexity. The simplest solution is usually the best.

**Workshop Application**: Modular Monolith > Microservices (a one-person team doesn't need distributed complexity). In-process Event Bus > Redis Pub/Sub (sufficient for Phase 1).

### 4. YAGNI — You Aren't Gonna Need It

> Don't write code for "what might be needed in the future."

**Workshop Application**: Technical foundation of the Progressive Complexity principle. In Phase 1, we build a checkbox to-do; there's no need to build a task pool dispatch engine in advance. Each Phase is a complete and usable product.

### 5. SSOT — Single Source of Truth

> Every piece of data has only one authoritative source.

**Workshop Application**:
- The Space model is the single source of truth for sharing scope.
- The Event Bus is the sole propagation channel for state changes.
- PostgreSQL schema-per-module prevents data from being scattered.

### 6. SoC — Separation of Concerns

> Strictly separate different concerns; do not mix them.

**Workshop Application**: Module boundaries = concern boundaries. `core/src/shared/` for cross-module shared code, `core/src/modules/{name}/` for module-specific code. Route handlers only deal with the HTTP protocol, Services only handle business logic, and Models only manage data structures.

### 7. Fail Fast

> Errors should be exposed as early as possible; never swallow them silently.

**Workshop Application**: The `WorkshopError` hierarchy ensures all errors surface immediately. The `before_create()` hook validates before the DB insert. The frontend API client uses a global error interceptor for unified handling.

### 8. Composition > Inheritance

> Prioritize composition over inheritance to reuse behavior.

**Workshop Application**: Service = BaseCRUD (inheritance) + EventBus (composition) + Permission (composition). Widget = ModuleLayout (composition) + data hook (composition) + rendering component (composition). Composition Recipes are themselves the concretization of service composition.

### 9. Loose Coupling + High Cohesion

> Minimize dependencies between modules; elements within a module should be highly related.

**Workshop Application**:
- Loose: Modules communicate only via the Event Bus (writes) or Public API (reads); direct imports are prohibited.
- High: Models/schemas/service/routes within each module closely serve the same business domain.

### 10. MVP — Minimum Viable Product

> Minimum Viable Product — the smallest version that can validate assumptions.

**Workshop Application**: Each Phase is an MVP. The quest in Phase 1 is a checkbox; if it works, it's a success. We don't strive for "perfection" but for the ability to "validate core assumptions."

---

## Tier 2: Applied — Referenced during design decisions

> These principles need to be explicitly considered when making architectural/design decisions.

### SOLID (Remaining Four)

| Principle | Workshop Application |
|-----------|---------------------|
| **OCP** (Open/Closed) | Plugin system: Adding a new Plugin doesn't change the Core. Connecting a new Module to the Event Bus doesn't change existing Modules. |
| **LSP** (Liskov Substitution) | `BridgeAdapter` ABC: LINE/Telegram/Discord adapters are completely interchangeable. |
| **ISP** (Interface Segregation) | Each MCP Server only exposes tools for its domain and does not force the implementation of irrelevant interfaces. |
| **DIP** (Dependency Inversion) | Services depend on Repository interfaces, not directly on the PostgreSQL driver. |

### Architecture Principles

| Principle | Workshop Application |
|-----------|---------------------|
| **Bounded Context** (DDD) | Each Module = one bounded context, with its own "language" and data model. |
| **Event-Driven** | Modules communicate via events. `finance.transaction.created` → `quest` can subscribe. |
| **Idempotency** | Event handlers must be idempotent — receiving the same event twice won't produce duplicate effects. |
| **Progressive Disclosure** | MCP tools are loaded on demand (`ToolSearch`), not crammed into the system prompt all at once. |
| **12-Factor App** | Config in env (`.env`), stateless services, port binding, dev/prod parity. |
| **CoC** (Convention over Config) | Unified file structure for modules: `models.py`, `schemas.py`, `service.py`, `routes.py`. |
| **PoLA** (Least Astonishment) | API behavior follows REST conventions; Event naming `{module}.{entity}.{action}` is intuitive and readable. |
| **Defensive Programming** | Boundary validation in `before_create()`; external input is never trusted. |

### Design Patterns in Workshop

| Pattern | Where Used |
|---------|-----------|
| **Template Method** | `BaseCRUDService` hooks: `before_create()`, `after_create()`, `to_response()`. |
| **Adapter** | `BridgeAdapter` (LINE/Telegram/Discord), MCP Server (HTTP adapter to Core API). |
| **Observer / Pub-Sub** | Event Bus — modules subscribe to events from other modules. |
| **Strategy** | LLM provider switching (OpenAI ↔ Ollama), embedding model selection. |
| **Factory** | `createCrudApi<T,C,U>(basePath)` — Create a frontend API client in one line. |
| **Facade** | MCP Server = a simplified facade for the Core API; Dashboard = a unified container for Widgets. |
| **State** | Quest state machine: `pending → active → completed → cancelled`. |
| **Registry** | Error code registry: `ERROR_REGISTRY` dict → `GET /api/meta/error-codes`. |
| **Singleton** | DB connection pool, Redis client. |
| **Proxy** | API Gateway — auth/rate-limit handled at the proxy layer. |
| **Mediator** | Event Bus acts as a mediator between modules. |

---

## Tier 3: Reference — Consulted when needed

> These principles/patterns are useful in specific scenarios but are not part of daily development.

### Future Considerations

| Principle | When Relevant |
|-----------|---------------|
| **CQRS** | Phase 3+ — Separate read and write into different models/databases (if there's a significant difference in load). |
| **CAP Theorem** | During multi-instance deployment — trade-offs among C/A/P. |
| **Eventually Consistent** | Multi-instance + cross-service synchronization — sacrifice real-time consistency to ensure eventual synchronization. |
| **Strangler Fig** | If migrating progressively from V1 to V2 (we chose a complete rewrite, so it's not currently applicable). |
| **Anti-Corruption Layer** | When integrating with external legacy APIs (e.g., government open data, legacy system integration). |

### Remaining GoF Patterns (for reference)

| Category | Patterns | Potential Use |
|----------|----------|---------------|
| **Creational** | Builder, Prototype | Builder: Complex query assembly; Prototype: deep copy config. |
| **Structural** | Composite, Bridge, Flyweight, Decorator | Composite: Widget tree; Decorator: `@authenticate`. |
| **Behavioral** | Command, Chain of Responsibility, Iterator, Visitor, Memento | Command: undo/redo; CoR: middleware pipeline; Memento: version rollback. |

### Testing Principles

| Principle | Application |
|-----------|-------------|
| **Test Pyramid** | Many Unit → Some Integration → Few E2E. |
| **AAA Pattern** | Arrange → Act → Assert. |
| **Test Isolation** | Each test is independent and doesn't depend on execution order. |
| **Real Validation** | Master prefers real execution over mock/smoke tests. |

### Modern / AI Era (2024-2026)

| Principle | Application |
|-----------|-------------|
| **AI-Augmented Development** | Claude Code + Skills assist in development; humans review AI-generated code. |
| **Prompt-as-Code** | `SKILL.md` / `agents/*.md` as prompts managed by version control. |
| **Minimum Tool Surface** | MCP Server only exposes minimum necessary tools (< 10 per server). |
| **Blast Radius Isolation** | The blast radius of failures in each Module is controllable (schema isolation, independent event handlers). |
| **Infrastructure as Code** | Docker Compose, Nginx config all under version control. |
| **Observability > Monitoring** | OpenTelemetry traces + structured logging (built from Phase 1). |

---

## Quick Reference Card

```
10 Principles always on the mind during development:

 1. SRP    — One module, one responsibility.
 2. DRY    — Don't write logic twice (abstract on the third).
 3. KISS   — Simplicity is usually the best solution.
 4. YAGNI  — Don't write code for imaginary requirements.
 5. SSOT   — Only one authoritative source for each piece of data.
 6. SoC    — Strictly separate different concerns.
 7. Fail Fast — Let errors explode immediately.
 8. Composition > Inheritance — Use composition, not inheritance.
 9. Loose Coupling + High Cohesion — Loose between modules, tight within.
10. MVP    — Build the smallest version that can be validated first.
