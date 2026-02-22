# Folder Structure & Naming Conventions

## Overview

```
~/workshop/
├── services/              # Backend micro services (Python/FastAPI)
├── apps/                  # Frontend micro apps (React/TypeScript)
├── libs/                  # Shared libraries (cross-domain)
│   ├── python/            # Python shared lib
│   └── typescript/        # TypeScript shared lib (UI components, types)
├── lab/                   # POC experiments (Skill outputs, prototypes)
├── infra/                 # Infrastructure (Docker, Nginx, scripts)
├── docs/                  # Cross-domain documentation
├── tools/                 # Developer tools, CLI utilities
├── pyproject.toml         # Python workspace root (uv)
└── package.json           # JS workspace root (pnpm)
```

## Naming Rules

### Services (`services/`)

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| lowercase, kebab-case | `user-auth` | `userAuth`, `UserAuth` |
| noun or noun-phrase | `finance`, `speech-to-text` | `handle-payments` |
| no `-service` suffix | `finance/` | `finance-service/` |
| Python package: snake_case | `src/finance/` | `src/finance-api/` |

Each service directory:
```
services/<name>/
├── src/<python_package>/
│   ├── __init__.py
│   ├── main.py            # FastAPI app entrypoint
│   ├── routes/            # API route modules
│   ├── models/            # Pydantic models / DB schemas
│   └── core/              # Business logic
├── tests/
├── Dockerfile
├── pyproject.toml
└── README.md
```

### Apps (`apps/`)

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| lowercase, kebab-case | `finance`, `disk-report` | `Finance`, `diskReport` |
| Match service name | `apps/finance` ↔ `services/finance` | Different names for same domain |
| `shell` = host app | `apps/shell/` | `apps/host/`, `apps/main/` |

Each app directory:
```
apps/<name>/
├── src/
│   ├── components/
│   ├── pages/
│   ├── hooks/
│   └── index.tsx
├── public/
├── package.json
├── tsconfig.json
└── README.md
```

### Libs (`libs/`)

Shared code that is **used by 2+ services/apps**. If only one consumer, keep it in that consumer.

```
libs/
├── python/                # Python shared library
│   ├── src/corelib/       # importable as `from corelib import ...`
│   ├── pyproject.toml
│   └── README.md
└── typescript/            # TypeScript shared library
    ├── src/
    │   ├── components/    # Shared UI components
    │   ├── hooks/         # Shared React hooks
    │   ├── types/         # Shared TypeScript types
    │   └── utils/         # Shared utilities
    ├── package.json
    └── README.md
```

### Docs (`docs/`)

Cross-domain documentation only. Domain-specific docs go in each service/app's `README.md`.

```
docs/
├── architecture/          # System architecture, ADRs, folder conventions
├── api/                   # API design standards, OpenAPI conventions
├── runbooks/              # Operational procedures (deploy, rollback, debug)
└── guides/                # Developer onboarding, setup instructions
```

### Infra (`infra/`)

```
infra/
├── docker/                # docker-compose files, base Dockerfiles
├── nginx/                 # Nginx configs, routing rules
└── scripts/               # Deploy scripts, CI/CD helpers
```

## Domain Mapping

A domain is a vertical slice of functionality. The same domain name appears in both `services/` and `apps/` when it has both backend and frontend.

```
                    services/finance/    ← API (port 8793)
  Finance domain ──
                    apps/finance/        ← UI (micro frontend)

                    services/gateway/    ← API (port 8800)
  Gateway domain ──
                    apps/shell/          ← UI (host app, port 3000)

                    services/stt/        ← API only, no frontend
  STT domain ──────
                    (no apps entry)
```


### Lab (`lab/`)

POC experiments and Skill output staging area. Nothing here is imported by production services.

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| `<name>-poc` suffix | `finance-poc/` | `finance/` (conflicts with services/) |
| Every POC has README.md | Documents goal, hypothesis, conclusion | No docs, orphaned outputs |
| outputs/ for Skill artifacts | `lab/finance-poc/outputs/*.md` | Dumping .md in services/ |

Each lab directory:
```
lab/<name>-poc/
├── README.md              # Goal, hypothesis, conclusion (even if failed)
├── outputs/               # Skill / script outputs (.md, .json, etc.)
└── scripts/               # Quick validation scripts
```

**Lifecycle**: `lab/<name>-poc/` → validate → graduate to `services/` + `apps/` → archive or delete lab entry.

**Cleanup rules**:
- Graduated: keep README.md, delete outputs/
- Failed: keep README.md (records why), delete rest
- Idle > 30 days: review and decide

## Key Principles

1. **Vertical slicing** — organize by business domain, not by technical layer
2. **Independent deployability** — each service and app can be built/deployed alone
3. **Shared code is explicit** — only `libs/` content is shared; no implicit cross-domain imports
4. **Convention over configuration** — consistent naming means less documentation needed
5. **README.md per unit** — every service and app has its own README for domain-specific docs
