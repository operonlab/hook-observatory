# Micro Services Architecture Guide

## Design Principles

### 1. Single Responsibility
Each service owns **one** business domain. It owns its data, its API, and its business logic.

- `finance` owns transactions, budgets, subscriptions
- `quest` owns quests, skills, rewards
- `gateway` owns routing, auth, health aggregation

### 2. API-First
Every service exposes a well-defined HTTP API. Internal communication between services uses HTTP (not shared database access).

```
Client → Gateway → Service A
                 → Service B
```

**Never** let Service A directly query Service B's database.

### 3. Independent Data Stores
Each service owns its database schema. Co-locating in the same PostgreSQL instance is fine, but schemas must be isolated.

```sql
-- Good: separate schemas
CREATE SCHEMA finance;   -- owned by finance service
CREATE SCHEMA quest;     -- owned by quest service

-- Bad: shared tables across services
```

### 4. Stateless Services
Services should be stateless. Session state goes in Redis, persistent state goes in PostgreSQL, files go in object storage (MinIO/S3).

## Service Template

```
services/<name>/
├── src/<package>/
│   ├── __init__.py
│   ├── main.py              # FastAPI app factory
│   ├── config.py            # pydantic-settings config
│   ├── routes/
│   │   ├── __init__.py
│   │   └── <resource>.py    # one file per resource
│   ├── models/
│   │   ├── __init__.py
│   │   ├── db.py            # SQLAlchemy / raw SQL models
│   │   └── schemas.py       # Pydantic request/response schemas
│   ├── core/
│   │   ├── __init__.py
│   │   └── <logic>.py       # business logic, pure functions
│   └── deps.py              # FastAPI dependencies (db session, auth, etc.)
├── tests/
│   ├── conftest.py
│   ├── test_routes/
│   └── test_core/
├── migrations/              # Alembic or raw SQL migrations
├── Dockerfile
├── pyproject.toml
└── README.md
```

## Port Allocation Convention

| Range | Purpose |
|-------|---------|
| 8800-8809 | Platform services (gateway, orchestrator) |
| 8810-8829 | Domain services (finance, quest, muse, ...) |
| 8830-8849 | Tool services (stt, tts, storage, ...) |
| 8850-8899 | Reserved for future expansion |
| 3000-3099 | Frontend dev servers |

## Health Check Standard

Every service MUST expose `GET /health` returning:

```json
{
  "status": "healthy",
  "service": "<name>",
  "version": "<version>"
}
```

## Configuration

Use `pydantic-settings` with environment variables. Service-specific config in `.env` (gitignored), defaults in `config.py`.

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    port: int = 8810
    db_url: str = "postgresql://localhost/mydb"
    debug: bool = False

    model_config = {"env_prefix": "FINANCE_"}
```

## Inter-Service Communication

| Pattern | When to use |
|---------|-------------|
| HTTP (httpx) | Synchronous request/response |
| Redis Pub/Sub | Event-driven, fire-and-forget |
| PostgreSQL LISTEN/NOTIFY | Database-triggered events |
| WebSocket (Socket.IO) | Real-time client updates |

## Deployment

Each service builds to an independent Docker image:

```dockerfile
FROM python:3.12-slim
COPY --from=builder /app/.venv /app/.venv
CMD ["uvicorn", "finance.main:app", "--host", "0.0.0.0", "--port", "8810"]
```

Local development uses shared venv + LaunchAgent/systemd for process management.
