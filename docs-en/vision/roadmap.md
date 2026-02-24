---
doc_version: 1
content_hash: f8683532
source_version: 1
target_lang: en
translated_at: 2026-02-24
source_hash: b80736b0
source_lang: zh-TW
---

# Workshop Roadmap

> A four-phase development roadmap: from personal and family use to commercial applications.

---

## Overview

```
Phase 1              Phase 2              Phase 3              Phase 4
Personal + Family    Knowledge + Growth   Team + Dispatch      Commercial
──────────────────►──────────────────►──────────────────►──────────────────►

auth ✓               lore v2              roster               nexus v3
finance              dojo                 quest dispatch       quest commercial
quest (simple)       scout                nexus v2             legal advisor
muse                 nexus v1             resource pool        virtual CS
notification         church music         social hooks v2      ERP/POS
social hooks v1                                                full platform
```

---

## Phase 1: Personal & Family

> Goal: The workshop becomes a daily tool for Jones and his family.

### Core Modules

| Module | Goal | Completion Criteria |
|--------|--------|-------------------|
| **auth** | Multi-login provider support + space model | 2+ users, including personal and family spaces |
| **finance** | Personal/family accounting | Income/expense tracking, subscription management, monthly reports, usable by my wife |
| **quest** | Simple mode to-do list | Checkbox + due date + basic widget |
| **muse** | Idea notes | CRUD for Sparks + links + graph visualization |

### Bridges

| Bridge | Goal | Completion Criteria |
|--------|--------|-------------------|
| **Social Hooks v1** | Basic LINE bot integration | Perform accounting/to-do tasks via LINE commands |
| **Notification** | PWA push notifications | Basic push notification capability |

### Infrastructure

- [ ] FastAPI Core Monolith + modular structure
- [ ] PostgreSQL with an independent schema for each module + all tables include space_id
- [ ] Event bus (in-process)
- [ ] Dashboard Widget framework (react-grid-layout + Container Queries) — a supplementary view outside of module pages
- [ ] LLM Chat overlay — a global LLM conversation interface (similar to Gemini in Chrome)
- [ ] MCP Servers for finance, quest, and muse (connected to core APIs)
- [ ] PWA + Service Worker (base already exists)
- [ ] Basic CI/CD

### Phase 1 Deliverables

- Module pages functional: finance, quest, muse each have a complete route-based UI
- Dashboard functional: Homepage dashboard has at least 4 widgets (financial summary, recent transactions, task list, quick note)
- LLM Chat overlay functional: Can call LLM conversation from any page
- LINE bot functional: Basic `@accounting`, `@todo` commands
- Family account functional: Wife can log in and view shared accounting
- MCP functional: Claude Code can directly operate all modules

---

## Phase 2: Knowledge & Growth

> Goal: The workshop becomes a personal knowledge management and growth platform.

### Core Modules

| Module | Goal | Completion Criteria |
|--------|--------|-------------------|
| **lore** | KAS Memory v2 | Automatic extraction, semantic search, cross-phase recall |
| **dojo** | Skill tree v1 | Skill definitions, levels, learning paths |
| **scout** | Daily intel v1 | RSS subscriptions, auto-summaries, briefings |
| **nexus v1** | Basic matching | Skill × learning resource recommendations |

### Sites

| Site | Goal | Completion Criteria |
|---------|--------|-------------------|
| **Church Music** | Sheet music digitization | OCR → library → basic search |

### Phase 2 Deliverables

- Lore v2 live: Claude Code's memory is more accurate and structured
- Skill tree visualization: A widget displaying the personal skill map
- Daily briefing: Automatically receive news/social media summaries every morning
- Sheet music library: Church hymns are searchable and browseable

---

## Phase 3: Team & Dispatch

> Goal: Upgrade the workshop from a personal tool to a small team collaboration platform.

### Core Modules

| Module | Goal | Completion Criteria |
|--------|--------|-------------------|
| **roster** | Resource management v1 | Human + AI agent capability/load tracking |
| **quest dispatch** | Task dispatch | Task pool + passive assignment + active claiming |
| **nexus v2** | Advanced matching | Talent × task multi-dimensional scoring |

### Bridges

| Bridge | Goal | Completion Criteria |
|--------|--------|-------------------|
| **Social Hooks v2** | Full platform integration | LINE + Telegram + Discord |

### Phase 3 Deliverables

- Task pool functional: Friends can claim tasks from the task pool
- Resource dashboard: View the load status of all resources (human/AI)
- Multi-platform notifications: Task assignment/completion notifications pushed to all social platforms

---

## Phase 4: Commercialization

> Goal: Apply the workshop's domain knowledge to commercial scenarios.

### Applications

| Project | Goal | Built On |
|---------|--------|----------|
| **Quest Commercial** | Orders/quotes/acceptance | quest + finance |
| **Legal Advisor** | Legal advisory service | RAG + LLM inference |
| **Virtual CS** | Virtual customer service | nexus + social hooks |
| **ERP/POS** | Inventory management system | finance + quest + roster |
| **Full Platform** | Open platform | All modules + plugin system |

### Phase 4 Deliverables

- At least one commercial case implemented (virtual customer service or ERP/POS)
- Mature plugin system: Third parties can develop workshop plugins
- Public API documentation
- Multi-space organization management

---

## Cross-Cutting Concerns (Across All Phases)

| Item | Description |
|------|-------------|
| **Documentation** | Complete phase specifications before starting, update architecture documents after completion |
| **Testing** | Real-world scenario validation (no mocks), at least one end-to-end flow per module |
| **Security** | auth reaches production level from phase 1 — no shortcuts |
| **Observability** | Establish OpenTelemetry tracing + structured logging from phase 1 |
| **MCP** | Each new module simultaneously generates an MCP Server |
| **Widget** | Each new module simultaneously generates at least one dashboard widget |

---

## Priorities (Within Each Phase)

Priorities within each phase are as follows:

1. **Infrastructure** → Foundation first
2. **auth** → Identity first
3. **Data Model** → Structure first
4. **Core API** → Backend first
5. **MCP Server** → CLI interface first
6. **Widget** → UI last
7. **Documentation** → Throughout

---

## Known Risks

| Risk | Mitigation Strategy |
|------|-------------------|
| Scope creep | Strict phase boundaries — do not start phase N+1 before completing phase N |
| Technical debt | Documentation first + real validation — refuse quick temporary fixes |
| Motivation decline | Each phase produces a usable product — daily use = sustained motivation |
| Context explosion | Wayne's memory system + HANDOFF.md + domain-specific documents |
| Over-engineering | Progressive complexity principle: build the simplest version first |
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3053ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2453ms
