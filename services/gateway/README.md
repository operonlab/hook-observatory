# Gateway Service

API Gateway — routing, authentication, health aggregation.

## Port
8800

## Responsibilities
- Request routing to downstream services
- Authentication & session management
- Health check aggregation
- Rate limiting

## Run
```bash
uvicorn gateway.main:app --host 127.0.0.1 --port 8800
```

## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| GATEWAY_PORT | 8800 | Service port |
| GATEWAY_DB_URL | postgresql://localhost/workshop | PostgreSQL connection |
| GATEWAY_REDIS_URL | redis://localhost:6379/0 | Redis connection |
| GATEWAY_DEBUG | false | Debug mode |
