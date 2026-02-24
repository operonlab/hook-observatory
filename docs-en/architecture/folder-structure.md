---
doc_version: 4
content_hash: adfe14e5
source_version: 4
target_lang: en
translated_at: 2026-02-24
source_hash: d80d2646
source_lang: zh-TW
---

# Directory Structure and Naming Conventions

## Three-Tier Classification

Workshop organizes all functionality into three tiers:

| Tier | Description | Location |
|------|-------------|----------|
| **Core Modules** | Database-backed business domains (10 modules) | `core/src/modules/` |
| **Stations** | Standalone local tools (no dependency on the core database) | `stations/` |
| **Bridges** | External platform connectors | `bridges/` |

## Overview

```
~/workshop/
├── core/                        # Modular Monolith (Python/FastAPI)
│   ├── src/
│   │   ├── events/              # Event Bus Engine
│   │   ├── hooks/               # Hooks/Plugin Engine
│   │   ├── modules/             # Core Modules (10 Domains)
│   │   │   ├── auth/            # Auth & Authorization
│   │   │   ├── finance/         # Accounting & Finance
│   │   │   ├── quest/           # Quests & Scheduling
│   │   │   ├── muse/            # Ideas & Knowledge Graph
│   │   │   ├── scout/           # Daily Intelligence
│   │   │   ├── lore/            # LLM Memory Persistence
│   │   │   ├── dojo/            # Skill Trees & Learning Paths
│   │   │   ├── roster/          # Resource Management
│   │   │   ├── nexus/           # Matching Engine
│   │   │   └── admin/           # Platform Administration
│   │   ├── middleware/          # Auth, CORS, OTel Middleware
│   │   ├── shared/              # Shared types, utils
│   │   └── routes/              # Route aggregation
│   ├── services/                # Hot-path services (deployed independently)
│   │   ├── realtime/            # LiveKit WebRTC Gateway
│   │   └── media/               # STT/TTS/Image Processing
│   ├── plugins/                 # Installed plugins
│   ├── migrations/              # Database migrations (all schemas)
│   └── tests/
├── workbench/                   # Single React application
│   ├── src/
│   │   ├── shell/               # App shell (layout, navigation, auth)
│   │   ├── modules/             # Domain UI modules (correspond to core modules)
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
├── mcp/                         # MCP adapter layer (thin wrappers around core APIs)
├── stations/                    # Standalone local tools
│   ├── system-monitor/          # Disk analysis + hardware resource monitoring
│   ├── llm-usage/               # Unified LLM Token/Cost tracking
│   ├── envkit/                  # Environment snapshots + one-click migration
│   ├── tmux-webui/              # tmux browser control interface
│   ├── session-redactor/        # Transcript sensitive data redaction
│   └── sandbox-executor/        # Sandbox code execution MCP server
├── vendor/                      # Third-party community tools (unmodified)
│   └── observability/           # Multi-Agent Observability (@disler)
├── bridges/                     # External platform connectors
│   └── (LINE, Telegram, Discord, Firebase — planned)
├── plugins/                     # Plugin packages (git-based)
├── libs/
│   ├── python/                  # Python shared libraries (corelib + station-sdk)
│   └── typescript/              # TypeScript shared libraries
├── infra/
│   ├── docker/                  # docker-compose, Dockerfiles
│   ├── nginx/                   # Nginx config, routing rules
│   ├── observability/           # LGTM/SigNoz config, dashboards
│   └── scripts/                 # Deployment scripts, CI/CD helpers
├── docs/
│   ├── architecture/            # System architecture documents
│   ├── blueprint/               # Implementation blueprints
│   ├── reference/               # Reference materials
│   ├── vision/                  # Platform vision (manifesto, domains, composition model, roadmap)
│   └── guides/                  # Developer guides (doc management, feature lifecycle)
├── scripts/                     # Build/translate/deploy scripts
│   └── translate-docs.py       # Automatically translate docs to Traditional Chinese (zh-TW) via Gemini CLI
├── lab/                         # POC experiments
├── pyproject.toml               # Python workspace root (uv)
└── package.json                 # JS workspace root (pnpm)
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

| Module | Domain | Phase | Database Schema |
|--------|--------|-------|-----------|
| `auth` | Auth & Authorization | 1 | `auth` |
| `finance` | Accounting & Finance | 1 | `finance` |
| `quest` | Quests & Scheduling | 1 | `quest` |
| `muse` | Ideas & Knowledge Graph | 1 | `muse` |
| `scout` | Daily Intelligence | 2 | `scout` |
| `lore` | LLM Memory Persistence | 2 | `lore` |
| `dojo` | Skill Trees & Learning Paths | 2 | `dojo` |
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
├── pages/               # Route-level components
├── hooks/               # Domain-specific hooks
├── stores/              # Zustand state stores
├── api/                 # API client functions
├── types/               # Domain-specific types
└── index.tsx            # Module entrypoint (exports routes)
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
├── webhook.py           # Incoming webhook handler
├── events.py            # Bridge-specific events
└── schemas.py           # Platform-specific schemas
```

Planned bridges: LINE, Telegram, Discord, Firebase.

### MCP Adapters (`mcp/`)

A thin wrapper layer that exposes core API endpoints as MCP tools. MCP servers never touch the database directly.

```
mcp/<server-name>/
├── server.py            # MCP server entrypoint
├── tools/               # Tool definitions
└── README.md
```

### Stations (`stations/`)

Standalone local tools. Stations that need to push data to the Core API or provide a Workbench Widget can optionally reference `libs/python/station-sdk/` (see [AD-8](./architecture-decisions.md#ad-8-station-sdk--工作站共享層)).

```
stations/<name>/
├── src/                 # Source code
├── README.md
└── package.json / pyproject.toml
```

**Station Classification**:

| Station | Language | Uses SDK | Positioning |
|---------|------|:--------:|------|
| system-monitor | Python/Shell | ✅ | Disk + hardware monitoring, weekly report generation |
| llm-usage | Python | ✅ | Unified LLM Token/Cost tracking |
| envkit | Python/Shell | ❌ | Environment snapshot + one-click migration CLI |
| tmux-webui | Python | ❌ | tmux browser control + system metrics |
| session-redactor | Python | ❌ | SessionEnd hook for sensitive data redaction |
| sandbox-executor | Node.js | ❌ | Batch execution MCP Server |

### Third-Party Tools (`vendor/`)

Third-party community tools that are not being refactored into the V2 architecture. Used directly, with upstream updates via `git pull`.

```
vendor/
└── <name>/
    └── README.md            # Note on source, purpose, and integration method
```

**Current**:
| Tool | Source | Description |
|------|------|------|
| observability | [@disler](https://github.com/disler/claude-code-hooks-multi-agent-observability) | Real-time monitoring dashboard for Claude Code hooks |

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

Shared code used by **2 or more modules or services**. If there is only one user, keep the code in that user's directory.

```
libs/
├── python/                  # Python shared libraries
│   ├── corelib/             # Shared among Core modules (importable as `from corelib import ...`)
│   ├── station-sdk/         # Shared SDK for Stations (optional dependency)
│   │   ├── api_client.py    # Core API push (unified auth + endpoint)
│   │   ├── scheduler.py     # launchd plist generation / management
│   │   ├── widget_schema.py # Workbench Widget JSON standard format
│   │   └── notifier.py      # Notification channel abstraction
│   ├── pyproject.toml
│   └── README.md
└── typescript/              # TypeScript shared libraries
    ├── src/
    │   ├── components/      # Shared UI components
    │   ├── hooks/           # Shared React hooks
    │   ├── types/           # Shared TypeScript types
    │   └── utils/           # Shared utils
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

Only for cross-domain documentation. Domain-specific documentation is located in the `README.md` of each module/service.

```
docs/
├── architecture/            # System architecture, ADRs
├── blueprint/               # Implementation blueprints
├── reference/               # Reference materials
├── vision/                  # Platform vision documents
│   ├── workshop-manifesto.md    # What is Workshop
│   ├── domain-catalog.md        # 10 core modules + 5 project ideas
│   ├── composition-model.md     # Lego composition model
│   └── roadmap.md               # Four-phase roadmap
└── guides/                  # Developer guides (doc management, feature lifecycle)
```

**Translation Workflow**: `docs/` is written in Traditional Chinese (source of truth). `docs-en/` is the English backup. Version tracking is done via YAML frontmatter (`doc_version` + `content_hash`).

### Scripts (`scripts/`)

```
scripts/
└── translate-docs.py        # Automatically translate docs to Traditional Chinese (Gemini CLI)
```

### Lab (`lab/`)

POC experiments and prototypes. Nothing here is imported by production code.

| Rule | Example | Anti-Pattern |
|------|---------|-------------|
| `<name>-poc` suffix | `finance-poc/` | `finance/` (conflicts with module) |
| Each POC has a README.md | Documents goal, hypothesis, conclusion | No documentation, orphaned output |

Each experiment directory:
```
lab/<name>-poc/
├── README.md              # Goal, hypothesis, conclusion (even if it failed)
├── outputs/               # Skill / script outputs (.md, .json, etc.)
└── scripts/               # Quick validation scripts
```

**Lifecycle**: `lab/<name>-poc/` → validate → promote to `core/src/modules/` + `workbench/src/modules/` → archive or delete experiment.

## Domain Mapping

Domains are mapped vertically between backend and frontend modules:

```
                  core/src/modules/finance/           ← Backend logic
Finance Domain ──
                  workbench/src/modules/finance/      ← Frontend UI

                  core/src/modules/auth/              ← Backend logic
Auth Domain ─────
                  workbench/src/modules/auth/         ← Frontend UI (login, registration)

                  core/services/media/                ← Standalone service, no frontend
Media Domain ────
                  (No frontend module)
```

## Core Principles

1.  **Four-Tier Classification** — Core Modules (DB-backed) / Stations (local tools) / Bridges (connectors) / Vendor (third-party)
2.  **Modular Monolith** — Organized by business domain within a single deployable unit
3.  **Module Boundaries** — No cross-module model imports; use service layers or events
4.  **Shared Code is Explicit** — Only share content from `libs/` and `shared/`
5.  **Convention over Configuration** — Consistent naming means less documentation is needed
6.  **One README.md per Unit** — Every service and significant module has its own README
7.  **Traditional Chinese as Source of Truth** — `docs/` is written in Traditional Chinese (source of truth), `docs-en/` is the English backup
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2536ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2452ms
