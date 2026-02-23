---
doc_version: 1
content_hash: f8683532
---

# Workshop Roadmap

> Four-phase development roadmap: from personal + family to commercial applications.

---

## Overview

```
Phase 1              Phase 2              Phase 3              Phase 4
Personal + Family    Knowledge + Growth   Team + Dispatch      Commercial
──────────────────►──────────────────►──────────────────►──────────────────►

auth ✓               memory v2            workforce            matching v3
finance              skill                quest dispatch       quest commercial
quest (simple)       intel                matching v2          legal advisor
muse                 matching v1          resource pool        virtual CS
notification         church music         social hooks v2      ERP/POS
social hooks v1                                                full platform
```

---

## Phase 1: Personal + Family

> Goal: Workshop becomes a daily tool for Jones + family.

### Core Modules

| Module | Target | Completion Criteria |
|--------|--------|-------------------|
| **auth** | Multi-provider login + Space model | 2+ users, personal + family space |
| **finance** | Personal/family accounting | Income/expense tracking, subscription management, monthly reports, wife can use |
| **quest** | Simple mode to-do | Checkbox + due date + basic Widget |
| **muse** | Idea notes | Spark CRUD + Link + Graph visualization |

### Bridges

| Bridge | Target | Completion Criteria |
|--------|--------|-------------------|
| **Social Hooks v1** | Basic LINE bot integration | Accounting/to-do via LINE commands |
| **Notification** | PWA Push | Basic push notification capability |

### Infrastructure

- [ ] FastAPI Core Monolith + Module structure
- [ ] PostgreSQL schema-per-module + space_id on all tables
- [ ] Event Bus (in-process)
- [ ] Widget Dashboard framework (react-grid-layout + Container Queries)
- [ ] MCP Servers for finance, quest, muse (adapter to Core API)
- [ ] PWA + Service Worker (foundation already exists)
- [ ] Basic CI/CD

### Phase 1 Deliverables

- Dashboard functional: at least 4 Widgets (finance summary, recent transactions, quest list, quick note)
- LINE bot functional: `@accounting`, `@todo` basic commands
- Family accounts functional: wife can log in and see shared accounting
- MCP functional: Claude Code can directly operate all Modules

---

## Phase 2: Knowledge + Growth

> Goal: Workshop becomes a personal knowledge management and growth platform.

### Core Modules

| Module | Target | Completion Criteria |
|--------|--------|-------------------|
| **memory** | KAS Memory v2 | Auto extraction, semantic search, cross-session recall |
| **skill** | Skill tree v1 | Skill definitions, levels, learning paths |
| **intel** | Daily intelligence v1 | RSS subscriptions, auto summaries, briefing |
| **matching v1** | Basic matching | Skill × learning resource recommendations |

### Stations

| Station | Target | Completion Criteria |
|---------|--------|-------------------|
| **Church Music** | Sheet music digitization | OCR → library → basic search |

### Phase 2 Deliverables

- Memory v2 live: Claude Code's memory is more accurate and structured
- Skill tree visualization: Widget showing personal skill map
- Daily briefing: Auto-receive news/social media summaries each morning
- Music library: Church hymns searchable and browsable

---

## Phase 3: Team + Dispatch

> Goal: Workshop upgrades from personal tool to small team collaboration platform.

### Core Modules

| Module | Target | Completion Criteria |
|--------|--------|-------------------|
| **workforce** | Resource management v1 | Human + AI agent capability/load tracking |
| **quest dispatch** | Task dispatch | Task pool + passive assignment + active pickup |
| **matching v2** | Advanced matching | Talent × task multi-dimensional scoring |

### Bridges

| Bridge | Target | Completion Criteria |
|--------|--------|-------------------|
| **Social Hooks v2** | Full platform integration | LINE + Telegram + Discord |

### Phase 3 Deliverables

- Task pool functional: friends can pick up tasks from pool
- Resource dashboard: see load status for all resources (human/AI)
- Multi-platform notifications: task assignment/completion notifications pushed to all social platforms

---

## Phase 4: Commercial

> Goal: Workshop's domain knowledge applied to commercial scenarios.

### Applications

| Project | Target | Built On |
|---------|--------|----------|
| **Quest Commercial** | Orders/quotation/acceptance | quest + finance |
| **Legal Advisor** | Legal advisory service | RAG + LLM reasoning |
| **Virtual CS** | Virtual customer service | matching + social hooks |
| **ERP/POS** | Inventory management system | finance + quest + workforce |
| **Full Platform** | Open platform | All Modules + Plugin system |

### Phase 4 Deliverables

- At least one commercial case landed (Virtual CS or ERP/POS)
- Plugin system mature: third parties can develop Workshop plugins
- Public API documentation
- Multi-Space organizational management

---

## Cross-Cutting Concerns (Spanning All Phases)

| Item | Description |
|------|-------------|
| **Documentation** | Complete Phase spec before starting, update architecture docs upon completion |
| **Testing** | Real scenario validation (no mocks), at least one end-to-end flow per Module |
| **Security** | auth is production-grade from Phase 1 — no shortcuts |
| **Observability** | OpenTelemetry traces + structured logging from Phase 1 |
| **MCP** | Each new Module simultaneously produces an MCP Server |
| **Widget** | Each new Module simultaneously produces at least 1 Dashboard Widget |

---

## Priority Order (within each Phase)

Priority within a Phase follows:

1. **Infrastructure** → foundation first
2. **auth** → identity first
3. **Data Model** → structure first
4. **Core API** → backend first
5. **MCP Server** → CLI interface first
6. **Widget** → UI last
7. **Documentation** → throughout

---

## Known Risks

| Risk | Mitigation Strategy |
|------|-------------------|
| Scope too large | Strict Phase boundaries — don't start Phase N+1 until Phase N is complete |
| Technical debt | Documentation first + real validation — no quick hacks |
| Motivation decline | Each Phase produces a usable product — daily use = sustained motivation |
| Context explosion | Wayne's memory system + HANDOFF.md + domain-specific docs |
| Over-engineering | Progressive Complexity principle: build simplest version first |
