# Code Conventions

## Backend Module Layout (`core/src/modules/<name>/`)
```
__init__.py    # Module registration, router export
routes.py      # FastAPI routes (HTTP layer only)
models.py      # SQLAlchemy models (module-scoped)
schemas.py     # Pydantic request/response schemas
services.py    # Business logic — THIS IS THE PUBLIC API
events.py      # Event subscribers
hooks.py       # Plugin hook points
deps.py        # FastAPI dependencies
```
Other modules import from `services.py` only. Never from models.py or routes.py.

## Frontend Module Layout (`workbench/src/modules/<name>/`)
```
components/    # Domain-specific components
pages/         # Route-level components
hooks/         # Domain-specific hooks
stores/        # Zustand stores (domain-scoped)
api/           # API client functions
types/         # Domain-specific types
index.tsx      # Module entry (export routes)
```
Frontend modules MUST NOT import from other modules. Cross-module via Router, custom events, or `src/shared/stores/`.

## Naming
- Backend modules: snake_case → `auth`, `finance`
- Frontend modules: match backend names
- Module name = DB schema = API prefix (`/api/<module>/`)
- Events: `{module}.{entity}.{past_tense}` — always past tense
- Errors: `{module}.{error_name}` — structured codes
- IDs: UUID v7 everywhere (uuid-utils)

## Shared Code Threshold
Code goes in `shared/` or `libs/` ONLY if used by 2+ modules. One user → keep it local.

## OOP Patterns
- `BaseCRUDService<M,C,U,R>` — Template Method with hooks: `before_create()`, `after_create()`, `to_response()`
- `SpaceScopedModel` — TimestampMixin + space_id + created_by (8/10 modules)
- `GlobalModel` — TimestampMixin only (auth, admin)
- `PaginatedResponse<T>` — all list endpoints return this format
- `WorkshopError` hierarchy — NotFoundError(404), ForbiddenError(403), ConflictError(409), BadRequestError(400)
- `createCrudApi<T,C,U>(basePath)` — frontend CRUD factory, one line per module
- `BridgeAdapter` ABC — polymorphic external platform connectors

## Configuration
- `pydantic-settings` with prefixed env vars (CORE_*, etc.)
- .env for local dev, env vars for production
