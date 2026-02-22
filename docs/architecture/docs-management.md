# Documentation Management

## Hybrid Model: Centralized + Distributed

### Centralized (`docs/`)

Cross-domain, system-level documentation that applies to the whole platform.

```
docs/
├── architecture/        # System design decisions
│   ├── folder-structure.md    # This repo's layout and naming rules
│   ├── micro-services.md      # Backend architecture guide
│   ├── micro-frontends.md     # Frontend architecture guide
│   ├── docs-management.md     # This file
│   └── adr/                   # Architecture Decision Records
│       └── 001-template.md
├── api/                 # API design standards
│   ├── conventions.md         # Naming, versioning, error format
│   └── openapi/               # Cross-service OpenAPI specs
├── runbooks/            # Operational procedures
│   ├── deploy.md
│   ├── rollback.md
│   └── incident-response.md
└── guides/              # Developer guides
    ├── getting-started.md     # New developer onboarding
    ├── add-new-service.md     # How to add a new micro service
    └── add-new-app.md         # How to add a new micro frontend
```

### Distributed (per domain)

Domain-specific documentation lives **inside** each service/app as `README.md`.

```
services/finance/README.md     ← How to run, env vars, API endpoints
apps/finance/README.md         ← How to develop, component structure
```

## What Goes Where?

| Content | Location | Example |
|---------|----------|---------|
| Architecture decisions | `docs/architecture/` | "Why we chose Module Federation" |
| API design standards | `docs/api/` | "All endpoints use camelCase" |
| Deployment procedures | `docs/runbooks/` | "How to deploy finance service" |
| Onboarding guide | `docs/guides/` | "Set up dev environment" |
| Service-specific setup | `services/<name>/README.md` | "Finance needs STRIPE_KEY env var" |
| App-specific dev guide | `apps/<name>/README.md` | "Run with `pnpm dev`" |
| Shared lib usage | `libs/<lang>/README.md` | "Import corelib.db for connections" |

## ADR (Architecture Decision Records)

For significant technical decisions, create an ADR in `docs/architecture/adr/`:

```markdown
# ADR-NNN: <Title>

## Status
Accepted | Proposed | Deprecated

## Context
What situation prompted this decision?

## Decision
What did we decide?

## Consequences
What are the trade-offs?
```

## Maintenance Rules

1. **Update docs with code** — if you change behavior, update the relevant doc in the same PR
2. **README.md is mandatory** — every service and app must have one
3. **No stale docs** — delete docs for removed features; outdated docs are worse than no docs
4. **English for code docs** — technical docs in English for tooling compatibility
