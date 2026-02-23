---
doc_version: 4
content_hash: adfe14e5
---

# Folder Structure & Naming Conventions

## Three-Tier Taxonomy

Workshop organizes all functionality into three tiers:

| Tier | Description | Lives In |
|------|-------------|----------|
| **Core Modules** | DB-backed business domains (10 modules) | `core/src/modules/` |
| **Stations** | Standalone local tools (no Core DB dependency) | `stations/` |
| **Bridges** | External platform connectors | `bridges/` |

## Overview

```
~/workshop/
├── core/                        # Modular Monolith (Python/FastAPI)
│   ├── src/
│   │   ├── events/              # Event Bus engine
│   │   ├── hooks/               # Hook/Plugin engine
│   │   ├── modules/             # Core Modules (10 domains)
│   │   │   ├── auth/            # Authentication & authorization
│   │   │   ├── finance/         # Accounting & finance
│   │   │   ├── quest/           # Tasks & dispatch
│   │   │   ├── muse/            # Ideas & knowledge graph
│   │   │   ├── scout/           # Daily intelligence
│   │   │   ├── lore/            # LLM memory persistence
│   │   │   ├── dojo/            # Skill trees & learning paths
│   │   │   ├── roster/          # Resource management
│   │   │   ├── nexus/           # Matching engine
│   │   │   └── admin/           # Platform management
│   │   ├── middleware/          # Auth, CORS, OTel middleware
│   │   ├── shared/              # Shared types, utils
│   │   └── routes/              # Route aggregation
│   ├── services/                # Hot-path services (independent deploy)
│   │   ├── realtime/            # LiveKit WebRTC gateway
│   │   └── media/               # STT/TTS/image processing
│   ├── plugins/                 # Installed plugins
│   ├── migrations/              # Database migrations (all schemas)
│   └── tests/
├── workbench/                   # Single React application
│   ├── src/
│   │   ├── shell/               # App shell (layout, nav, auth)
│   │   ├── modules/             # Domain UI modules (mirror of Core Modules)
│   │   │   ├── auth/
│   │   │   ├── finance/
│   │   │   ├── quest/
│   │   │   ├── muse/
│   │   │   ├── scout/
│   │   │   ├── lore/
│   │   │   ├── dojo/
│   │   │   ├── roster/
│   │   │   ├── nexus/
│   │   │   └── admin/
│   │   ├── plugins/             # Plugin UI runtime + slots
│   │   └── shared/              # Shared components, hooks, utils
│   ├── public/
│   ├── rsbuild.config.ts
│   └── package.json
├── mcp/                         # MCP adapter layer (thin wrappers over Core API)
├── stations/                    # Standalone local tools
│   └── sandbox-executor/        # Sandbox code execution MCP server
├── bridges/                     # External platform connectors
│   └── (LINE, Telegram, Discord, Firebase — planned)
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
│   ├── blueprint/               # Implementation blueprints
│   ├── reference/               # Reference materials
│   ├── vision/                  # Platform vision (manifesto, domains, ADRs, roadmap)
│   └── zh-TW/                   # Traditional Chinese translations (auto-generated)
│       ├── architecture/        # Mirror of docs/architecture/
│       ├── blueprint/           # Mirror of docs/blueprint/
│       ├── reference/           # Mirror of docs/reference/
│       ├── vision/              # Mirror of docs/vision/
│       └── CLAUDE.zh-TW.md     # Mirror of root CLAUDE.md
├── scripts/                     # Build/translate/deploy scripts
│   └── translate-docs.py       # Auto-translate docs to zh-TW via Gemini CLI
├── lab/                         # POC experiments
├── pyproject.toml               # Python workspace root (uv)
└── package.json                 # JS workspace root (pnpm)
```

## Naming Rules

### Core Modules (`core/src/modules/`)

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| lowercase, snake_case | `auth`, `finance` | `Auth`, `userAuth` |
| noun or noun-phrase | `finance`, `quest` | `handle_payments` |
| match DB schema name | module `finance` → schema `finance` | Different names |

Each module directory:
```
core/src/modules/<name>/
├── __init__.py          # Module registration, router export
├── routes.py            # FastAPI router
├── models.py            # Database models (module-scoped)
├── schemas.py           # Pydantic request/response schemas
├── services.py          # Business logic (public API)
├── events.py            # Event handlers
├── hooks.py             # Hook points
└── deps.py              # FastAPI dependencies
```

### 10 Core Modules

| Module | Domain | Phase | DB Schema |
|--------|--------|-------|-----------|
| `auth` | Authentication & authorization | 1 | `auth` |
| `finance` | Accounting & finance | 1 | `finance` |
| `quest` | Tasks & dispatch | 1 | `quest` |
| `muse` | Ideas & knowledge graph | 1 | `muse` |
| `scout` | Daily intelligence | 2 | `scout` |
| `lore` | LLM memory persistence | 2 | `lore` |
| `dojo` | Skill trees & learning paths | 2 | `dojo` |
| `roster` | Resource management | 3 | `roster` |
| `nexus` | Matching engine | 3 | `nexus` |
| `admin` | Platform management | 1 | `admin` |

### Frontend Modules (`workbench/src/modules/`)

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| lowercase, kebab-case | `finance`, `quest` | `Finance`, `questModule` |
| Match backend module | `modules/finance` ↔ `core/src/modules/finance` | Different names |

Each frontend module:
```
workbench/src/modules/<name>/
├── components/          # Domain-specific components
├── pages/               # Route-level components
├── hooks/               # Domain-specific hooks
├── stores/              # Zustand stores
├── api/                 # API client functions
├── types/               # Domain-specific types
└── index.tsx            # Module entry (exports routes)
```

### Hot-Path Services (`core/services/`)

| Rule | Example | Anti-pattern |
|------|---------|-------------|
| lowercase, kebab-case dirs | `realtime`, `media` | `livekit-service` |
| Python package: snake_case | `src/realtime/` | `src/realtime-service/` |

Each hot-path service:
```
core/services/<name>/
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

### Bridges (`bridges/`)

External platform connectors. Each bridge wraps a third-party API.

```
bridges/<platform>/
├── __init__.py
├── client.py            # Platform API client
├── webhook.py           # Incoming webhook handlers
├── events.py            # Bridge-specific events
└── schemas.py           # Platform-specific schemas
```

Planned bridges: LINE, Telegram, Discord, Firebase.

### MCP Adapters (`mcp/`)

Thin wrapper layer that exposes Core API endpoints as MCP tools. MCP servers never touch the database directly.

```
mcp/<server-name>/
├── server.py            # MCP server entrypoint
├── tools/               # Tool definitions
└── README.md
```

### Stations (`stations/`)

Standalone local tools that don't depend on Core DB. Each station is self-contained.

```
stations/<name>/
├── src/                 # Source code
├── README.md
└── package.json / pyproject.toml
```

### Plugins (`plugins/`)

```
plugins/
├── <plugin-name>/
│   ├── plugin.json      # Plugin manifest
│   ├── backend/         # Python hooks
│   │   └── hooks.py
│   ├── frontend/        # React components (optional)
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
├── blueprint/               # Implementation blueprints
├── reference/               # Reference materials
├── vision/                  # Platform vision docs
│   ├── workshop-manifesto.md    # What Workshop is
│   ├── domain-catalog.md        # Service Catalog + Composition Recipes
│   ├── architecture-decisions.md # 7 ADRs from brainstorming
│   └── roadmap.md               # Four-phase roadmap
├── zh-TW/                   # Traditional Chinese translations
│   ├── architecture/        # *.zh-TW.md files
│   ├── blueprint/
│   ├── reference/
│   ├── vision/
│   └── CLAUDE.zh-TW.md
├── api/                     # API design standards
├── runbooks/                # Operational procedures
└── guides/                  # Developer onboarding
```

**Translation workflow**: English docs are source of truth. Run `python3 scripts/translate-docs.py` to auto-translate to zh-TW. Version tracking via YAML frontmatter (`doc_version` + `content_hash`).

### Scripts (`scripts/`)

```
scripts/
└── translate-docs.py        # Auto-translate docs to zh-TW (Gemini CLI)
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

**Lifecycle**: `lab/<name>-poc/` → validate → graduate to `core/src/modules/` + `workbench/src/modules/` → archive or delete lab entry.

## Domain Mapping

Domains map vertically between backend modules and frontend modules:

```
                  core/src/modules/finance/           ← Backend logic
Finance domain ──
                  workbench/src/modules/finance/      ← Frontend UI

                  core/src/modules/auth/              ← Backend logic
Auth domain ─────
                  workbench/src/modules/auth/         ← Frontend UI (login, register)

                  core/services/media/                ← Standalone service, no frontend
Media domain ────
                  (no frontend module)
```

## Key Principles

1. **Three-tier taxonomy** -- Core Modules (DB-backed) / Stations (local tools) / Bridges (connectors)
2. **Modular monolith** -- organize by business domain within a single deployable unit
3. **Module boundaries** -- no cross-module model imports; use service layer or events
4. **Shared code is explicit** -- only `libs/` and `shared/` content is shared
5. **Convention over configuration** -- consistent naming means less documentation needed
6. **README.md per unit** -- every service and significant module has its own README
7. **English source of truth** -- all docs in English, auto-translated to zh-TW
