---
doc_version: 1
content_hash: 13aa3c09
---

# Workshop Manifesto

> Workshop is a unified workstation that starts as personal tools and grows into a consumer-grade platform ecosystem.

## What is Workshop?

Workshop is not just a project folder — it is Jones's **digital workstation**, housing everything from disk analysis to enterprise-grade ERP.
From small utilities like LLM usage tracking and hardware monitoring, to full-scale accounting, task dispatch, talent matching, and POS systems —
everything lives under one architecture, sharing authentication, event streams, and data exchange.

### Core Philosophy

1. **Personal → Platform**: Every feature serves the individual (+ family/friends) first, then opens up as a platform service once validated
2. **Flexible but Bounded**: Leave room for expansion but prevent uncontrolled sprawl — domain boundaries manage complexity
3. **Documentation First**: Think clearly, write clearly, then build (lesson learned: T1/T2 premature sprint led to full rollback)
4. **Real Validation**: No mock tests or smoke tests — validate with real tasks and real results
5. **MCP as First-Class Interface**: Claude Code Skills + MCP Servers are first-class citizens; UI comes second

---

## Three-Tier Taxonomy: Core / Stations / Bridges

All Workshop functionality is classified into three tiers based on **data residency**:

### Core Modules

> Data lives in Workshop's own database (PostgreSQL), managed by the FastAPI Core Monolith.

These are the backbone of Workshop — with persistent data, business logic, and multi-user sharing needs.

| Module | Description |
|--------|-------------|
| **auth** | Authentication + Space-based permissions (prerequisite for all) |
| **finance** | Accounting, subscription management, financial insights |
| **quest** | To-do → quantified tasks → dispatch → orders (progressive complexity) |
| **muse** | Idea notes, knowledge graph, inbox |
| **intel** | Daily intelligence, auto-summaries, RSS/social monitoring |
| **memory** | KAS Memory v2 (LLM memory persistence) |
| **skill** | Skill trees, learning paths, capability verification |
| **workforce** | Resource management (human/machine/service/AI agent unified abstraction) |
| **matching** | Matching engine (talent×jobs, capability×tasks) |
| **admin** | Platform management, system monitoring, configuration |

### Stations

> Standalone local tools that don't necessarily need a database. May be CLIs, desktop utilities, or analysis scripts.

- Disk analysis / system resource monitoring
- LLM usage tracking
- Local file management tools
- Claude Code Skills (diagram-gen, pdf, ocr, etc.)

Stations can run independently without FastAPI Core, but may optionally push data to Core.

### Bridges

> Adapters connecting to external ecosystems. They don't own data — they only handle bidirectional sync.

- **Social Hooks**: LINE, Telegram, Discord, Facebook
- **Notification Platform**: Firebase Cloud Messaging / PWA Push
- **External APIs**: OpenAI, Google Calendar, GitHub, etc.
- **OCR / AI Services**: Wrappers around external AI models

Bridge outputs typically flow into Core Modules (e.g., LINE message → quest creates a to-do).

---

## Design Principles

### 1. Domain Boundary is King

Each Core Module has its own:
- Database schema (schema-per-module, not DB-per-module)
- Event definitions (publish/subscribe)
- MCP Server (thin adapter)
- API routes (`/api/{module}/...`)

Cross-module communication only via: Event Bus or Public API. Direct imports between modules are forbidden.

### 2. Multi-User from Day 1

Not bolted on after the fact. The Space-based sharing model is designed into the data model from day one:
- `space_id` appears on all data tables
- Space = sharing scope (personal / family / friends / org)
- Each Space can enable/disable different Modules

### 3. Progressive Complexity

Features start simple and grow complexity on demand:
- quest: checkbox → story points → skill requirements → task pool → commercial order
- finance: personal accounting → family shared ledger → inventory → POS
- matching: manual pairing → conditional filtering → AI recommendations

### 4. MCP-First, UI-Second

Each Core Module gets an MCP Server first (so Claude Code can operate it directly),
then a Widget UI (for Dashboard visual interaction).
MCP Servers are thin adapters to the Core API — they never touch the database directly.

### 5. Widget-Based Dashboard

Instead of traditional "one app, one page" routing, Workshop uses an Android-style Widget Dashboard:
- Each Module provides multiple Widgets (different sizes, different functions)
- Users freely drag, drop, and resize
- Widgets exchange data via EventBus
- Widgets are self-responsive via CSS Container Queries

---

## What Workshop is NOT

- **Not microservices**: It's a Modular Monolith — single deployment unit
- **Not a solo-user tool**: Multi-user from day one
- **Not enterprise SaaS**: It's a personal workstation, but the architecture allows growth into a platform
- **Not code-first**: Documentation first, validate then implement
