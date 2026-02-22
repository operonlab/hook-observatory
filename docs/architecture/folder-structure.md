# Folder Structure & Naming Conventions

## Overview

```
~/workshop/
├── services/
│   ├── core/                    # Modular Monolith (Python/FastAPI)
│   │   ├── src/core/
│   │   │   ├── events/          # Event Bus engine
│   │   │   ├── hooks/           # Hook/Plugin engine
│   │   │   ├── modules/         # Domain modules
│   │   │   │   ├── auth/
│   │   │   │   ├── finance/
│   │   │   │   ├── quest/
│   │   │   │   ├── muse/
│   │   │   │   └── admin/
│   │   │   ├── middleware/      # Auth, CORS, OTel middleware
│   │   │   ├── shared/          # Shared types, utils
│   │   │   └── routes/          # Route aggregation
│   │   ├── plugins/             # Installed plugins
│   │   ├── migrations/          # Database migrations (all schemas)
│   │   └── tests/
│   ├── realtime/                # Hot-path: LiveKit WebRTC gateway
│   └── media/                   # Hot-path: STT/TTS/image processing
├── apps/
│   └── web/                     # Single React application
│       ├── src/
│       │   ├── shell/           # App shell (layout, nav, auth)
│       │   ├── modules/         # Domain UI modules
│       │   │   ├── auth/
│       │   │   ├── finance/
│       │   │   ├── quest/
│       │   │   ├── muse/
│       │   │   └── admin/
│       │   ├── plugins/         # Plugin UI runtime + slots
│       │   └── shared/          # Shared components, hooks, utils
│       ├── public/
│       ├── rsbuild.config.ts
│       └── package.json
├── plugins/                     # Plugin packages (git-based)
├── libs/
│   ├── python/                  # Python shared lib
│   └── typescript/              # TypeScript shared lib
├── infra/
│   ├── docker/                  # docker-compose, Dockerfiles
│   ├── nginx/                   # Nginx configs, routing rules
│   ├── observability/           # LGTM/SigNoz configs, dashboards
│   └── scripts/                 # Deploy scripts, CI/CD helpers
├── docs/
│   ├── architecture/            # System architecture docs
│   ├── api/                     # API design standards
│   ├── runbooks/                # Operational procedures
│   └── guides/                  # Developer onboarding
├── lab/                         # POC experiments
├── tools/                       # Developer tools, CLI utilities
├── pyproject.toml               # Python workspace root (uv)
└── package.json                 # JS workspace root (pnpm)
```

## Naming Rules

### Core Modules (`services/core/src/core/modules/`)

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| lowercase, snake_case | `auth`, `finance` | `Auth`, `userAuth` |
| noun or noun-phrase | `finance`, `quest` | `handle_payments` |
| match DB schema name | module `finance` → schema `finance` | Different names |

Each module directory:
```
services/core/src/core/modules/<name>/
├── __init__.py          # Module registration, router export
├── routes.py            # FastAPI router
├── models.py            # Database models (module-scoped)
├── schemas.py           # Pydantic request/response schemas
├── services.py          # Business logic (public API)
├── events.py            # Event handlers
├── hooks.py             # Hook points
└── deps.py              # FastAPI dependencies
```

### Frontend Modules (`apps/web/src/modules/`)

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| lowercase, kebab-case | `finance`, `quest` | `Finance`, `questModule` |
| Match backend module | `modules/finance` ↔ `core/modules/finance` | Different names |

Each frontend module:
```
apps/web/src/modules/<name>/
├── components/          # Domain-specific components
├── pages/               # Route-level components
├── hooks/               # Domain-specific hooks
├── stores/              # Zustand stores
├── api/                 # API client functions
├── types/               # Domain-specific types
└── index.tsx            # Module entry (exports routes)
```

### Hot-Path Services (`services/realtime/`, `services/media/`)

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| lowercase, kebab-case dirs | `realtime`, `media` | `livekit-service` |
| Python package: snake_case | `src/realtime/` | `src/realtime-service/` |

Each hot-path service:
```
services/<name>/
├── src/<package>/
│   ├── __init__.py
│   ├── main.py          # FastAPI app entrypoint
│   ├── routes/
│   └── core/
├── tests/
├── Dockerfile
├── pyproject.toml
└── README.md
```

### Plugins (`plugins/`)

```
plugins/
├── <plugin-name>/
│   ├── pulso-plugin.json    # Plugin manifest
│   ├── backend/             # Python hooks
│   │   └── hooks.py
│   ├── frontend/            # React components (optional)
│   │   └── components/
│   └── README.md
```

### Libs (`libs/`)

Shared code used by **2+ modules or services**. If only one consumer, keep it in that consumer.

```
libs/
├── python/                  # Python shared library
│   ├── src/corelib/         # importable as `from corelib import ...`
│   ├── pyproject.toml
│   └── README.md
└── typescript/              # TypeScript shared library
    ├── src/
    │   ├── components/      # Shared UI components
    │   ├── hooks/           # Shared React hooks
    │   ├── types/           # Shared TypeScript types
    │   └── utils/           # Shared utilities
    ├── package.json
    └── README.md
```

### Infra (`infra/`)

```
infra/
├── docker/                  # docker-compose files, base Dockerfiles
├── nginx/                   # Nginx configs, routing rules
├── observability/           # OTel collector config, Grafana dashboards, SigNoz setup
└── scripts/                 # Deploy scripts, CI/CD helpers
```

### Docs (`docs/`)

Cross-domain documentation only. Domain-specific docs go in each module/service's `README.md`.

```
docs/
├── architecture/            # System architecture, ADRs
├── api/                     # API design standards, OpenAPI conventions
├── runbooks/                # Operational procedures (deploy, rollback, debug)
└── guides/                  # Developer onboarding, setup instructions
```

### Lab (`lab/`)

POC experiments and prototype staging. Nothing here is imported by production code.

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| `<name>-poc` suffix | `finance-poc/` | `finance/` (conflicts with modules) |
| Every POC has README.md | Documents goal, hypothesis, conclusion | No docs, orphaned outputs |

Each lab directory:
```
lab/<name>-poc/
├── README.md              # Goal, hypothesis, conclusion (even if failed)
├── outputs/               # Skill / script outputs (.md, .json, etc.)
└── scripts/               # Quick validation scripts
```

**Lifecycle**: `lab/<name>-poc/` → validate → graduate to `services/core/src/core/modules/` + `apps/web/src/modules/` → archive or delete lab entry.

## Domain Mapping

Domains map vertically between backend modules and frontend modules:

```
                  services/core/src/core/modules/finance/  ← Backend logic
Finance domain ──
                  apps/web/src/modules/finance/            ← Frontend UI

                  services/core/src/core/modules/auth/     ← Backend logic
Auth domain ─────
                  apps/web/src/modules/auth/               ← Frontend UI (login, register)

                  services/media/                          ← Standalone service, no frontend
Media domain ────
                  (no frontend module)
```

## Key Principles

1. **Modular monolith** -- organize by business domain within a single deployable unit
2. **Module boundaries** -- no cross-module model imports; use service layer or events
3. **Shared code is explicit** -- only `libs/` and `shared/` content is shared
4. **Convention over configuration** -- consistent naming means less documentation needed
5. **README.md per unit** -- every service and significant module has its own README
