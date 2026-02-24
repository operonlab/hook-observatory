---
doc_version: 5
content_hash: 2989924d
source_version: 5
target_lang: en
translated_at: 2026-02-24
source_hash: 91c13a19
source_lang: zh-TW
---

# Shared Layer Design — OOP Patterns Catalog

> A comprehensive analysis of Workshop's shared patterns. Each pattern describes: who the user is, which OOP technique is adopted, and how it is used.

---

## Decisions

| Item | Decision |
|------|----------|
| ID Format | UUID v7 (`uuid-utils` library) |
| CRUD Service | BaseCRUD (standard) + helpers (special) coexist |
| get_current_user | Specification defined in shared/deps.py, re-exported by auth/deps.py |
| Error Codes | Structured `"module.error_name"` + centralized registry + `GET /api/meta/error-codes` endpoint |
| Frontend Sharing | Synchronous design |
| spaceId Passing | Explicit parameters (no implicit injection) |
| Bridge Sharing | `core/src/shared/bridges/` |
| Docs vs Code | Docs-first |

---

## 1. Inheritance

> "Is-a" relationship. Subclasses automatically inherit fields and behaviors from parent classes.

### 1.1 SQLAlchemy Model Inheritance Chain

```
                        TimestampMixin
                     ┌───── id (UUID v7)
                     │ created_at (server_default)
                     │ updated_at (server_default + onupdate)
                     │
           ┌─────────┴─────────┐
     SpaceScopedModel       GlobalModel
   ┌── space_id (FK)      (no extra fields)
   │── created_by (FK)          │
   │                            │
   ▼                            ▼
Transaction              AuditLog
Budget                   SystemSetting
Quest, Task
Spark, Link
Source, Memory
Skill, Resource
...(39 entities)
```

**Who inherits SpaceScopedModel (8 modules, ~35 entities):**
finance, quest, muse, scout, lore, dojo, roster, nexus

**Who inherits GlobalModel (2 modules, ~4 entities):**
admin (audit_log, setting), auth (user, api_key)

**auth is special:** space/space_member are meta-entities — they do not inherit from any base and define their own schema.

### 1.2 Pydantic Schema Inheritance Chain

```
         TimestampMixin
      ┌── created_at
      │── updated_at
      │
      ├── SpaceScopedResponse
      │    ┌── id
      │    │── space_id
      │    └── created_by
      │         │
      │         ▼
      │    TransactionResponse
      │    QuestResponse
      │    SparkResponse ...
      │
      └── ErrorResponse
           ┌── detail
           │── code ("module.error_name")
           └── module
```

### 1.3 Exception Inheritance Chain

```
  WorkshopError (base)
  ├── status_code: int
  ├── code: str ("module.error_name")
  ├── module: str | None
  │
  ├── NotFoundError (404)
  ├── ForbiddenError (403)
  ├── ConflictError (409)
  ├── BadRequestError (400)
  └── RateLimitError (429)
```

The exception handler is registered in `main.py` and automatically converts `WorkshopError` to an HTTP response.

### 1.4 Frontend TypeScript Inheritance

```typescript
// BaseEntity — Corresponds to SpaceScopedResponse
interface BaseEntity {
  id: string;
  space_id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

// Each module extends it
interface Transaction extends BaseEntity { amount: number; category: string; }
interface Quest extends BaseEntity { title: string; status: QuestStatus; }
interface Spark extends BaseEntity { content: string; tags: string[]; }
```

---

## 2. Generics

> Same behavior, different types. One piece of logic + multiple types = eliminates duplicate code.

### 2.1 Backend: BaseCRUDService<M, C, U, R>

```
BaseCRUDService<ModelT, CreateT, UpdateT, ResponseT>

  list(db, space_id, pagination) → PaginatedResponse<ResponseT>
  get(db, space_id, entity_id)   → ResponseT
  create(db, space_id, data: CreateT, user_id) → ResponseT
  update(db, space_id, entity_id, data: UpdateT) → ResponseT
  delete(db, space_id, entity_id) → bool
```

**Usage**:
```
FinanceService = BaseCRUDService<Transaction, TransactionCreate, TransactionUpdate, TransactionResponse>
QuestService   = BaseCRUDService<Quest, QuestCreate, QuestUpdate, QuestResponse>
MuseService    = BaseCRUDService<Spark, SparkCreate, SparkUpdate, SparkResponse>
```

Covers 39 standard CRUD entities.

### 2.2 Backend: PaginatedResponse<T>

```
PaginatedResponse<T>
  items: list[T]
  total: int
  page: int
  page_size: int
  pages: int (computed)
```

All list endpoints uniformly return this format, where T is replaced with the Response type of each module.

### 2.3 Frontend: createCrudApi<T, C, U>

```typescript
createCrudApi<EntityT, CreateT, UpdateT>(basePath: string) → {
  list(spaceId, page?, pageSize?) → PaginatedResponse<EntityT>
  get(spaceId, id)                → EntityT
  create(spaceId, data: CreateT)  → EntityT
  update(spaceId, id, data: UpdateT) → EntityT
  delete(spaceId, id)             → void
}
```

Each module can create an API client with just one line of code:
```typescript
const transactionApi = createCrudApi<Transaction, CreateTransaction, UpdateTransaction>("/api/finance/transactions");
const questApi = createCrudApi<Quest, CreateQuest, UpdateQuest>("/api/quest/quests");
```

### 2.4 Frontend: PaginatedResponse<T> (corresponding)

```typescript
interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}
```

---

## 3. Polymorphism

> Same interface, different implementations. The caller does not need to know the specific subclass.

### 3.1 Template Method — Service Hook Points

BaseCRUDService defines a fixed flow; subclasses override specific steps:

```
create() flow:
  1. before_create(data) → data     ← Override: validation, transformation, default values
  2. DB insert
  3. after_create(model)             ← Override: send events, trigger side effects
  4. to_response(model) → response   ← Override: custom serialization
```

**Override scenarios for each module**:

| Module | before_create | after_create | to_response | Custom Methods |
|--------|:---:|:---:|:---:|---|
| finance | Amount validation | Send `transaction.created` event | -- | monthly_insights() |
| quest | Default status=open | Send `quest.created` event | Associated task count | dispatch(), accept(), complete() |
| muse | -- | Send `spark.created` event | -- | graph_traverse(), semantic_search() |
| scout | -- | Schedule summary generation | -- | generate_briefing() |
| lore | Embedding calculation | Send event | -- | semantic_search(), auto_extract() |
| dojo | Prerequisite check | Send event | Associated learning progress | recommend() |
| roster | Capacity check | Send event | -- | check_availability() |
| nexus | -- | Send event + trigger scoring | -- | score(), match() |

### 3.2 Bridge Adapter — Same interface, different platforms

```
BridgeAdapter (ABC)
  ├── receive(raw_payload) → WorkshopMessage    # Parse external format
  ├── send(event) → ExternalPayload             # Convert to external format
  ├── validate_signature(headers, body) → bool   # Validate webhook source
  └── refresh_token() → str                      # Token management

LINEAdapter(BridgeAdapter)       — LINE Messaging API implementation
TelegramAdapter(BridgeAdapter)   — Telegram Bot API implementation
DiscordAdapter(BridgeAdapter)    — Discord Webhook implementation
```

**Polymorphic call**: Event Bus subscribers don't care which platform it is:
```python
adapter: BridgeAdapter = get_adapter(platform)
adapter.send(event)  # LINE/Telegram/Discord each handle it in their own way
```

### 3.3 Error Handler — Single entry point, dispatched by subclasses

```python
# main.py registers a handler that automatically handles all WorkshopError subclasses
app.add_exception_handler(WorkshopError, workshop_error_handler)

# NotFoundError → 404, ForbiddenError → 403, etc.
# No need to write try/except in every route
```

---

## 4. Encapsulation

> Hiding internal details, exposing only necessary interfaces.

### 4.1 FastAPI Dependencies — Encapsulating Auth/Permissions/Pagination

| Dependency | What it encapsulates | What it exposes |
|-----------|---------------------|-----------------|
| `get_current_user()` | Session cookie parsing, itsdangerous signature verification | `dict` (user info) |
| `get_space_id()` | Path parameter / query parameter extraction, existence validation | `str` (space_id) |
| `require_permission(action)` | RBAC lookup + ABAC policy evaluation | Passes or throws 403 |
| `get_pagination()` | Query parameter parsing + validation | `PaginationParams` |
| `get_db()` | Connection pool, session lifecycle | `AsyncSession` |

The route handler only sees a clean interface:
```python
 @router.get("/")
async def list_transactions(
    space_id: str = Depends(get_space_id),
    pagination: PaginationParams = Depends(get_pagination),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.list(db, space_id, pagination)
```

### 4.2 Error Registry — Encapsulating Code ↔ Status Mapping

```python
# User just needs to: raise NotFoundError("finance.transaction_not_found")
# The registry automatically looks up status=404, default_message="Transaction not found"
# The exception handler automatically assembles the HTTP response
```

Modules do not need to know about HTTP status codes.

### 4.3 Event Publishing — Encapsulating Event Construction

```python
# No need to manually create an Event object every time
# publish_crud_event("finance", "transaction", "created", data, user_id)
# Internal implementation: Create Event → Set type/source/user_id/trace_id → bus.publish
```

### 4.4 Frontend API Client — Encapsulating HTTP Details

```typescript
// The user just needs to call transactionApi.list(spaceId, page)
// The client handles internally: credentials, headers, error parsing, retries
```

---

## 5. Composition

> "Has-a" relationship. Assembling various capabilities together.

### 5.1 Service = CRUD + Events + Permissions

BaseCRUDService is not directly coupled with EventBus or PolicyEngine.
Subclasses combine freely in hooks:

```
FinanceService
  has-a: BaseCRUDService (inheritance)
  uses: publish_crud_event() (called in after_create)
  uses: require_permission() (at the route layer, not the service layer)
```

### 5.2 Standalone Helpers (for non-standard entities)

Entities that do not inherit from BaseCRUDService can use helper functions directly:

| Helper | Functionality |
|--------|----------|
| `build_paginated_query(model, space_id, filters, order_by)` | Assemble SELECT |
| `paginate(stmt, db, pagination)` | Execute + wrap in PaginatedResponse |
| `get_or_404(db, model, id, space_id)` | Throws NotFoundError if not found |
| `check_exists(db, model, **filters)` | Check uniqueness constraints |

Quest's state machine (accept/complete) does not use BaseCRUD, but still uses `get_or_404` + `publish_crud_event`.

---

## 6. Backend ↔ Frontend Contract

| Concept | Backend (Python) | Frontend (TypeScript) |
|---------|-----------------|----------------------|
| Base Entity | `SpaceScopedResponse` | `BaseEntity` interface |
| Paginated List | `PaginatedResponse[T]` | `PaginatedResponse<T>` |
| Error | `ErrorResponse` | `ErrorResponse` |
| Error Codes | `ERROR_REGISTRY` dictionary → `GET /api/meta/error-codes` | Fetch on init → local map |
| CRUD Operations | `BaseCRUDService<M,C,U,R>` | `createCrudApi<T,C,U>(path)` |
| Space Context | `get_space_id()` dependency | explicit `spaceId` parameter |
| Authentication | `get_current_user()` dependency | `useAuth()` hook (session cookie) |
| Pagination | `get_pagination()` → `PaginationParams` | `usePaginatedList(fetcher, spaceId)` |

---

## 7. File Mapping Table

### Backend: `core/src/shared/`

| File | Content | Technique |
|------|----------|-----------|
| `types.py` | UserId, SpaceId, EntityId, TypeVars | Type aliases |
| `schemas.py` | TimestampMixin, SpaceScopedResponse, PaginationParams, PaginatedResponse<T>, ErrorResponse | Inheritance + Generics |
| `models.py` | Base, TimestampMixin, SpaceScopedModel, GlobalModel | Mixin |
| `service.py` | BaseCRUDService<M,C,U,R> + helper functions | Generics + Template Method + Composition |
| `deps.py` | get_db, get_current_user, get_space_id, require_permission, get_pagination | Encapsulation (DI) |
| `exceptions.py` | WorkshopError hierarchy + ERROR_REGISTRY | Inheritance + Registry |
| `events.py` | event_type(), publish_crud_event() | Encapsulation (function) |

### Frontend: `workbench/src/shared/`

| File | Content | Technique |
|------|----------|-----------|
| `api/client.ts` | fetch wrapper + error interceptor | Encapsulation |
| `api/crud.ts` | createCrudApi<T,C,U> | Generics + Factory |
| `types/base.ts` | BaseEntity, PaginatedResponse<T>, ErrorResponse | Interfaces (corresponding to backend) |
| `types/errors.ts` | Error code mapping (from `/api/meta/error-codes`) | Registry |
| `hooks/usePaginatedList.ts` | Paginated data fetching | Custom Hook |
| `hooks/useSpaceId.ts` | Current space context | Custom Hook |
| `errors/handler.ts` | Global errors → toast/redirect | Encapsulation |
| `components/ModuleLayout.tsx` | Module page skeleton | Composition |
| `components/PaginatedList.tsx` | List + pagination controls | Composition |

### Future: `core/src/shared/bridges/`

| File | Content | Technique |
|------|----------|-----------|
| `adapter.py` | BridgeAdapter ABC | Polymorphism (ABC) |
| `auth.py` | webhook signature verification | Encapsulation |

---

## 8. Coverage

| Quantity | Description |
|--------|-------------|
| **39** | Standard CRUD entities → Covered by BaseCRUDService |
| **~28** | Special methods → Standalone helpers + custom services |
| **8/10** | Core modules use SpaceScopedModel |
| **~60** | Event types following the `module.entity.action` format |
| **3+** | Bridge platforms using BridgeAdapter polymorphism |
| **10** | Frontend modules corresponding to backend shared types |
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2489ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2521ms
