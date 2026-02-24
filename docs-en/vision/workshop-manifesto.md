---
doc_version: 1
content_hash: 13aa3c09
source_version: 1
target_lang: en
translated_at: 2026-02-24
source_hash: adea8345
source_lang: zh-TW
---

# Workshop Manifesto

> Workshop is a unified workstation that starts with personal tools and grows into a consumer-grade platform ecosystem.

## What is Workshop?

Workshop is more than just a project folder—it is Jones's **digital workstation**, covering everything from disk analysis to enterprise-grade ERP.
From small tools like LLM usage tracking and hardware monitoring, to full-scale accounting, task scheduling, talent matching, and POS systems—
everything exists under the same architecture, sharing authentication, event streams, and data exchange.

### Core Philosophy

1.  **Personal → Platform**: Every feature first serves an individual (+ family/friends), and is opened as a platform service after validation.
2.  **Flexible but Bounded**: Leave room for expansion, but prevent uncontrolled sprawl—manage complexity through domain boundaries.
3.  **Documentation First**: Think clearly, write clearly, and then implement (Lesson learned: premature sprints in T1/T2 led to a full rollback).
4.  **Real-world Validation**: No mock tests or smoke tests—validate with real tasks and real results.
5.  **MCP as a First-Class Interface**: Claude Code Skills + MCP Servers are first-class citizens; UI is secondary.

---

## Three-Layer Taxonomy: Core / Stations / Bridges

All Workshop functions are divided into three tiers based on **data residency**:

### Core Modules

> Data resides in Workshop's own database (PostgreSQL), managed by the FastAPI Core Monolith.

These are the backbone of Workshop—requiring persistent data, business logic, and multi-user sharing.

| Module | Description |
|---|---|
| **auth** | Authentication + Space-based permissions (prerequisite for all features) |
| **finance** | Accounting, subscription management, financial insights |
| **quest** | To-dos → Quantified tasks → Scheduling → Orders (progressive complexity) |
| **muse** | Inspiration notes, knowledge graph, inbox |
| **scout** | Daily intelligence, auto-summaries, RSS/social monitoring |
| **lore** | KAS Memory v2 (LLM memory persistence) |
| **dojo** | Skill tree, learning paths, capability verification |
| **roster** | Resource management (a unified abstraction for humans/machines/services/AI agents) |
| **nexus** | Matching engine (talent × jobs, skills × tasks) |
| **admin** | Platform administration, system monitoring, configuration |

### Stations

> Standalone local tools that do not necessarily require a database. Could be CLIs, desktop tools, or analysis scripts.

-   **system-monitor** — Disk analysis + hardware resource stress monitoring
-   **llm-usage** — Unified LLM Token/Cost tracking (including LiteLLM Proxy)
-   **envkit** — Environment snapshot + one-click migration tool
-   **tmux-webui** — tmux browser control + system metrics
-   **session-redactor** — Transcript sensitive data redaction (SessionEnd hook)
-   **sandbox-executor** — Batch code execution engine (MCP Server)

Stations can run independently without the FastAPI Core, but can optionally push data to the Core.

### Vendor

> Third-party community tools that are not refactored into the V2 architecture. Used directly, with upstream updates via `git pull`.

-   **observability** — Real-time multi-agent monitoring dashboard for Claude Code hooks ([@disler](https://github.com/disler))

### Bridges

> Adapters connecting to external ecosystems. They do not own data—they only handle bidirectional synchronization.

-   **Social Hooks**: LINE, Telegram, Discord, Facebook
-   **Notification Platforms**: Firebase Cloud Messaging / PWA Push
-   **External APIs**: OpenAI, Google Calendar, GitHub, etc.
-   **OCR / AI Services**: Wrappers for external AI models

The output of a Bridge typically flows to a Core module (e.g., a LINE message → creates a to-do item in quest).

---

## Design Principles

### 1. Domain Boundary is King

Each Core module has its own:
-   Database schema (one schema per module, not one DB per module)
-   Event definitions (publish/subscribe)
-   MCP Server (thin adapter)
-   API routes (`/api/{module}/...`)

Cross-module communication is only via: the Event Bus or public APIs. Direct imports between modules are forbidden.

### 2. Multi-User Support From Day One

This is not an afterthought. A Space-based sharing model is designed into the data model from day one:
-   `space_id` appears in all data tables
-   Space = a shared scope (personal / family / friends / organization)
-   Each Space can enable/disable different modules

### 3. Progressive Complexity

Features start simple and increase in complexity based on demand:
-   quest: checkbox → story points → skill requirements → task pool → commercial order
-   finance: personal bookkeeping → shared family ledger → inventory → POS
-   nexus: manual matching → conditional filtering → AI recommendation

### 4. MCP First, UI Second

Each Core module first gets an MCP Server (so Claude Code can operate it directly),
followed by the module page UI and Dashboard Widget.
MCP Servers are thin adapters for the Core API—they never touch the database directly.

### 5. Three-Layer Frontend Architecture

Workshop's frontend consists of three coexisting layers:

```
┌─────────────────────────────────────────────┐
│  Layer 3: LLM Chat Overlay                  │ ← Global, always available for conversation
│  (Similar to Google Gemini embedded in Chrome) │
├─────────────────────────────────────────────┤
│  Layer 2: Dashboard Widget View             │ ← Drag-and-drop composition of widgets from various modules
├─────────────────────────────────────────────┤
│  Layer 1: Module SPA Pages                  │ ← /finance/*, /quest/* ...
│  Each module has its own full routing and UI   │
└─────────────────────────────────────────────┘
```

-   **Layer 1 — Module Pages**: Each module has a full, route-based SPA page (for accounting, task management, etc.)
-   **Layer 2 — Dashboard Widgets**: An additional dashboard view for freely dragging, dropping, and combining widgets extracted from various modules.
-   **Layer 3 — LLM Chat Overlay**: A conversational interface that spans all pages, allowing interaction with the LLM without leaving the current page.

The Widget Dashboard is a **supplement** to the module pages, not a replacement. The LLM Chat is a global overlay that can be invoked from any page.

---

## What Workshop Is Not

-   **Not a Microservice**: It is a Modular Monolith—a single deployment unit.
-   **Not a Single-User Tool**: It supports multi-user from day one.
-   **Not an Enterprise SaaS**: It is a personal workstation, but its architecture allows it to grow into a platform.
-   **Not Code-First**: Documentation first, implementation after validation.
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2651ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2784ms
