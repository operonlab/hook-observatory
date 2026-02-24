---
doc_version: 4
content_hash: adfe14e5
source_version: 4
target_lang: en
translated_at: 2026-02-24
source_hash: 68ee2d28
source_lang: zh-TW
---

# Directory Structure and Naming Conventions

## Three-Tier Classification

Workshop organizes all functionality into three tiers:

| Tier | Description | Location |
|------|-------------|----------|
| **Core Modules** | Business domains backed by a database (10 modules) | `core/src/modules/` |
| **Stations** | Standalone local tools (no dependency on the core database) | `stations/` |
| **Bridges** | External platform connectors | `bridges/` |

## Overview

```
~/workshop/
├── core/                        # Modular Monolith (Python/FastAPI)
│   ├── src/
│   │   ├── events/              # Event Bus Engine
│   │   ├── hooks/               # Hooks/Plugins Engine
│   │   ├── modules/             # Core Modules (10 domains)
│   │   │   ├── auth/            # Authentication & Authorization
│   │   │   ├── finance/         # Accounting & Finance
│   │   │   ├── quest/           # Quests & Scheduling
│   │   │   ├── muse/            # Ideas & Knowledge Graph
│   │   │   ├── scout/           # Daily Intelligence
│   │   │   ├── lore/            # LLM Memory Persistence
│   │   │   ├── dojo/            # Skill Tree & Learning Paths
│   │   │   ├── roster/          # Resource Management
│   │   │   ├── nexus/           # Matching Engine
│   │   │   └── admin/           # Platform Administration
│   │   ├── middleware/          # Auth, CORS, OTel Middleware
│   │   ├── shared/              # Shared Types, Utilities
│   │   └── routes/              # Route Aggregation
│   ├── services/                # Hot-Path Services (Independently Deployed)
│   │   ├── realtime/            # LiveKit WebRTC Gateway
│   │   └── media/               # STT/TTS/Image Processing
│   ├── plugins/                 # Installed Plugins
│   ├── migrations/              # Database Migrations (all schemas)
│   └── tests/
├── workbench/                   # Single React Application
│   ├── src/
│   │   ├── shell/               # Application Shell (Layout, Navigation, Auth)
│   │   ├── modules/             # Domain UI Modules (corresponding to core modules)
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
│   │   ├── plugins/             # Plugin UI Runtime + Slots
│   │   └── shared/              # Shared Components, Hooks, Utilities
│   ├── public/
│   ├── rsbuild.config.ts
│   └── package.json
├── mcp/                         # MCP Adaptation Layer (thin wrapper around Core API)
├── stations/                    # Standalone Local Tools
│   ├── system-monitor/          # Disk Analysis + Hardware Resource Monitoring
│   ├── llm-usage/               # Unified LLM Token/Cost Tracking
│   ├── envkit/                  # Environment Snapshot + One-click Migration
│   └── sandbox-executor/        # Sandbox Code Execution MCP Server
├── bridges/                     # External Platform Connectors
│   └── (LINE, Telegram, Discord, Firebase — Planned)
├── plugins/                     # Plugin Packages (git-based)
├── libs/
│   ├── python/                  # Python Shared Libraries
│   └── typescript/              # TypeScript Shared Libraries
├── infra/
│   ├── docker/                  # docker-compose, Dockerfiles
│   ├── nginx/                   # Nginx config, routing rules
│   ├── observability/           # LGTM/SigNoz config, dashboards
│   └── scripts/                 # Deployment scripts, CI/CD helpers
├── docs/
│   ├── architecture/            # System Architecture Docs
│   ├── blueprint/               # Implementation Blueprints
│   ├── reference/               # Reference Materials
│   ├── vision/                  # Platform Vision (Manifesto, Domains, Composition Model, Roadmap)
│   └── guides/                  # Developer Guides (Doc Management, Feature Lifecycle)
├── scripts/                     # Build/Translate/Deploy Scripts
│   └── translate-docs.py       # Automatically translate docs to Traditional Chinese (zh-TW) via Gemini CLI
├── lab/                         # POC Experiments
├── pyproject.toml               # Python Workspace Root (uv)
└── package.json                 # JS Workspace Root (pnpm)
```

## Naming Conventions

### Core Modules (`core/src/modules/`)

| Rule | Example | Anti-Pattern |
|------|---------|-------------|
| Lowercase, snake_case | `auth`, `finance` | `Auth`, `userAuth` |
| Noun or noun phrase | `finance`, `quest` | `handle_payments` |
| Consistent with database schema name | Module `finance` → schema `finance` | Different names |

Each module directory:
```
core/src/modules/<name>/
├── __init__.py          # Module registration, route exports
├── routes.py            # FastAPI routes
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
| `auth` | Authentication & Authorization | 1 | `auth` |
| `finance` | Accounting & Finance | 1 | `finance` |
| `quest` | Quests & Scheduling | 1 | `quest` |
| `muse` | Ideas & Knowledge Graph | 1 | `muse` |
| `scout` | Daily Intelligence | 2 | `scout` |
| `lore` | LLM Memory Persistence | 2 | `lore` |
| `dojo` | Skill Tree & Learning Paths | 2 | `dojo` |
| `roster` | Resource Management | 3 | `roster` |
| `nexus` | Matching Engine | 3 | `nexus` |
| `admin` | Platform Administration | 1 | `admin` |

### Frontend Modules (`workbench/src/modules/`)

| Rule | Example | Anti-Pattern |
|------|---------|-------------|
| Lowercase, kebab-case | `finance`, `quest` | `Finance`, `questModule` |
| Matches backend module | `modules/finance` ↔ `core/src/modules/finance` | Different names |

Each frontend module:
```
workbench/src/modules/<name>/
├── components/          # Domain-specific components
├── pages/               # Route-level pages
├── hooks/               # Domain-specific hooks
├── stores/              # Zustand state stores
├── api/                 # API client functions
├── types/               # Domain-specific types
└── index.tsx            # Module entry (exports routes)
```

### Hot-Path Services (`core/services/`)

| Rule | Example | Anti-Pattern |
|------|---------|-------------|
| Lowercase, kebab-case directory | `realtime`, `media` | `livekit-service` |
| Python package: snake_case | `src/realtime/` | `src/realtime-service/` |

Each hot-path service:
```
core/services/<name>/
├── src/<package>/
│   ├── __init__.py
│   ├── main.py          # FastAPI application entrypoint
│   ├── routes/
│   └── core/
├── tests/
├── Dockerfile
├── pyproject.toml
└── README.md
```

### Bridges (`bridges/`)

External platform connectors. Each bridge encapsulates a third-party API.

```
bridges/<platform>/
├── __init__.py
├── client.py            # Platform API client
├── webhook.py           # Ingress webhook handler
├── events.py            # Bridge-specific events
└── schemas.py           # Platform-specific schemas
```

Planned bridges: LINE, Telegram, Discord, Firebase.

### MCP Adapters (`mcp/`)

Thin wrapper layer that exposes Core API endpoints as MCP tools. The MCP server never touches the database directly.

```
mcp/<server-name>/
├── server.py            # MCP server entrypoint
├── tools/               # Tool definitions
└── README.md
```

### Stations (`stations/`)

Standalone local tools that do not depend on the core database. Each station is self-contained.

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

### Shared Libraries (`libs/`)

Shared code used by **2 or more modules or services**. If there is only one consumer, keep it local to that consumer.

```
libs/
├── python/                  # Python shared libraries
│   ├── src/corelib/         # Can be imported as `from corelib import ...`
│   ├── pyproject.toml
│   └── README.md
└── typescript/              # TypeScript shared libraries
    ├── src/
    │   ├── components/      # Shared UI components
    │   ├── hooks/           # Shared React hooks
    │   ├── types/           # Shared TypeScript types
    │   └── utils/           # Shared utilities
    ├── package.json
    └── README.md
```

### Infrastructure (`infra/`)

```
infra/
├── docker/                  # docker-compose files, base Dockerfiles
├── nginx/                   # Nginx config, routing rules
├── observability/           # OTel collector config, Grafana dashboards, SigNoz setup
└── scripts/                 # Deployment scripts, CI/CD helpers
```

### Documentation (`docs/`)

Cross-domain documentation only. Domain-specific documentation lives in the `README.md` of each module/service.

```
docs/
├── architecture/            # System architecture, ADRs
├── blueprint/               # Implementation blueprints
├── reference/               # Reference materials
├── vision/                  # Platform vision documents
│   ├── workshop-manifesto.md    # What is Workshop
│   ├── domain-catalog.md        # 10 Core Modules + 5 Project Ideas
│   ├── composition-model.md     # Lego Composition Model
│   └── roadmap.md               # Four-Phase Roadmap
└── guides/                  # Developer Guides (Doc Management, Feature Lifecycle)
```

**Translation Workflow**: `docs/` is written in Traditional Chinese (source of truth). `docs-en/` is an English backup. Versioning is tracked via YAML frontmatter (`doc_version` + `content_hash`).

### Scripts (`scripts/`)

```
scripts/
└── translate-docs.py        # Automatically translate docs to Traditional Chinese (Gemini CLI)
```

### Lab (`lab/`)

POC experiments and prototypes. Nothing here should be imported by production code.

| Rule | Example | Anti-Pattern |
|------|---------|-------------|
| Suffix with `<name>-poc` | `finance-poc/` | `finance/` (Conflicts with module) |
| Each POC has a README.md | Documents goals, hypotheses, conclusions | No documentation, orphaned output |

Each lab directory:
```
lab/<name>-poc/
├── README.md              # Goals, hypotheses, conclusions (even if it failed)
├── outputs/               # Skill / script outputs (.md, .json, etc.)
└── scripts/               # Quick validation scripts
```

**Lifecycle**: `lab/<name>-poc/` → Validate → Promote to `core/src/modules/` + `workbench/src/modules/` → Archive or delete the lab project.

## Domain Mapping

Domains are mapped vertically between backend and frontend modules:

```
                  core/src/modules/finance/           ← Backend Logic
Finance Domain ──
                  workbench/src/modules/finance/      ← Frontend UI

                  core/src/modules/auth/              ← Backend Logic
Auth Domain ─────
                  workbench/src/modules/auth/         ← Frontend UI (Login, Register)

                  core/services/media/                ← Standalone service, no frontend
Media Domain ────
                  (No frontend module)
```

## Core Principles

1. **Three-Tier Classification** — Core Modules (DB-backed) / Stations (Local Tools) / Bridges (Connectors)
2. **Modular Monolith** — Organize by business domain within a single deployable unit
3. **Module Boundaries** — No cross-module model imports; use service layers or events
4. **Shared Code is Explicit** — Only share content from `libs/` and `shared/`
5. **Convention Over Configuration** — Consistent naming means less documentation is needed
6. **One README.md Per Unit** — Every service and significant module has its own README
7. **Traditional Chinese as Source of Truth** — `docs/` is written in Traditional Chinese (source of truth), with `docs-en/` as an English backup
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3063ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3393ms
