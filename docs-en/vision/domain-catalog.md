---
doc_version: 3
content_hash: 2ec4dc04
source_version: 3
target_lang: en
translated_at: 2026-02-24
source_hash: ebf3ba3e
source_lang: zh-TW
---

# Service Catalog

> A unified catalog for Workshop services. No distinction between "core modules" and "projects"—everything is a composable service building block.

---

> For more on the LEGO composition model and recipes, see [vision/composition-model.md](./composition-model.md)

---

## Services

### Foundation

#### auth — Authentication & Authorization

| Attribute | Value |
|----------|-------|
| **Dependencies** | None (Prerequisite for all services) |
| **Depended on by** | All services |
| **MCP Server** | `workshop-auth` |
| **V1 Status** | Exists (GitHub OAuth, Google OAuth, Email/Password) |

**Capabilities**:
- Multi-provider login (GitHub, Google, Email, Future: LINE Login)
- Session management (cookie-based, `workshop_session`)
- Space management (create/invite/permissions)
- Module-level access control (by space, by user, by module)
- API key management (for MCP / external integrations)

**Space Model** (Shared Scope):
```
spaces: id, name, type(personal/family/friends/org), owner_id
space_members: space_id, user_id, role(owner/admin/member/guest), modules[]
```

---

#### admin — Platform Administration

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth |
| **MCP Server** | `workshop-admin` (to be built) |
| **V1 Status** | V1 had sysmon + agent-metrics (merged into gateway) |

**Capabilities**:
- System health monitoring (evolved from sysmon)
- User management
- Module enable/disable control
- System configuration
- Audit logging

---

### Domain Services

#### finance — Accounting & Finance

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth |
| **MCP Server** | `workshop-finance` |
| **V1 Status** | MCP server operational (9 tools) |

**Capabilities**:
- Personal/family bookkeeping (income/expense tracking)
- Subscription management (subscription lifecycle)
- Financial insights (monthly summary, category analysis)
- Budget planning (budgeting by category)

**Growth Path** (Progressive Complexity):
```
Phase 1: Personal bookkeeping
Phase 2: + Family shared ledger
Phase 3: + Budgeting/Analysis
Phase 4: + Inventory Management / POS
```

---

#### quest — Tasks & Dispatch

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth, dojo (for quantitative mode) |
| **Bidirectional Link** | finance (Task ↔ Order) |
| **MCP Server** | `workshop-quest` |
| **V1 Status** | MCP server operational (10 tools) |

**Capabilities**:
- **Simple Mode**: To-do list (checkboxes, due dates)
- **Quantitative Mode**: Story points, skill requirements, complexity assessment
- **Dispatch Mode**: Task pool + passive allocation + active acceptance
- **Business Mode**: Task = Order, including quotation and acceptance

**RPG Metaphor** (from Quest design document):
- Equipment = Knowledge, Skills = Competencies, Attributes = Core Traits
- Achievements = Track Record, Streaks/Completion Rate = Attitude (inferred from behavior)

**Growth Path**:
```
Phase 1: Checkbox to-do list
Phase 2: + Story points
Phase 3: + Skill requirements + Task pool
Phase 4: + Orders / Quotations / Acceptance
```

---

#### muse — Inspiration & Knowledge Graph

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth |
| **MCP Server** | `workshop-muse` |
| **V1 Status** | MCP server operational (8 tools) |

**Capabilities**:
- Spark (Inspiration note): Quickly capture ideas
- Link: Directed connections between Sparks
- Graph (Knowledge Graph): A visual network of ideas
- Inbox: Ideas to be processed
- Search (Semantic Search): Search across all Sparks

---

#### scout — Search & Intelligence

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth, lore (for personalization) |
| **MCP Server** | `workshop-scout` (to be built) |
| **Integrated Skills** | smart-search, daily-briefing, company-intel, competitive-intel, content-writer |
| **V1 Status** | research_report service (port 8830) + smart-search skill v0.3.3 |

**Capabilities**:
- RSS / Social media source management
- Automatic summary generation (LLM-driven)
- Daily briefing push
- Keyword / Topic tracking
- Integration with muse (Intelligence → Inspiration)

---

#### lore — LLM Memory Persistence

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth |
| **Depended on by** | dojo, scout |
| **MCP Server** | `kas-memory` (existing, 8 tools) |
| **Integrated Skills** | kas-memory (MCP), meeting-insights |
| **V1 Status** | MCP server v0.2.0 (semantic search + user profile) |

**Capabilities**:
- Session end → Automatic memory extraction
- User prompt submission → Automatic recall of relevant memories
- Semantic search (OpenAI embedding, switchable to Ollama)
- Memory promotion / editing / tagging
- KAS Profile (user trait summary)
- **V2 Direction**: Better forgetting mechanism, cross-space isolation, multi-agent support

---

#### dojo — Skill Tree & Learning Path

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth, lore |
| **Depended on by** | nexus, roster |
| **MCP Server** | `workshop-dojo` (to be built) |
| **Integrated Skills** | skill-catalog, skill-graph, skill-optimizer, model-mentor |
| **V1 Status** | Does not exist |

**Capabilities**:
- Skill definition and classification (tech tree structure)
- Learning path planning (prerequisite chain)
- Course/resource matching (skill gap → learning resources)
- Competency validation (assessment, certification tracking)
- Skill levels (Beginner → Intermediate → Advanced → Expert)

---

#### roster — Resource Management

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth, dojo |
| **Depended on by** | nexus |
| **MCP Server** | `workshop-roster` (to be built) |
| **Integrated Skills** | maestro, team-tasks, scheduler |
| **V1 Status** | Does not exist |

**Capabilities**:
- **Unified Resource Abstraction**: Human = Machine = Service = AI Agent
- Common attributes: capabilities[], capacity, availability, cost_rate, status
- Workload tracking (current load vs. max capacity)
- Scheduling / availability management

**Unified Resource Model**:
```
resources:
  id, type(human/machine/service/agent),
  name, capabilities[], capacity,
  availability_schedule, cost_rate, status
```

**Growth Path**:
```
Phase 1: Personal task tracking
Phase 2: + Team timesheets
Phase 3: + Machine/service resource pool
Phase 4: + Full ERP resource management
```

---

#### nexus — Matching Engine

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth, dojo, roster |
| **MCP Server** | `workshop-nexus` (to be built) |
| **V1 Status** | Does not exist |

**Capabilities**:
- Talent × Position matching
- Competency × Task pairing (the engine behind quest dispatch)
- Learning resource recommendation (skill gap → course suggestion)
- Multi-dimensional scoring (skill match, availability, cost, history)
- Three use cases for the same model: matching, allocation, learning path

---

### Integration Services (Bridges)

#### social-hooks — Social Platform Connectors

| Attribute | Value |
|----------|-------|
| **Category** | Bridge |
| **Priority** | LINE > Telegram > Discord > Facebook > X |
| **Provides to** | Routed to all core modules via Event Bus |

**Capabilities**:
- Unified messaging: All platform messages → unified inbox
- Event routing: Route messages to modules based on rules
  - ` @Library/Developer/Xcode/iOS DeviceSupport/iPhone16,2 26.2.1 (23C71)/Symbols/System/Library/PrivateFrameworks/MemoryAccounting.framework/MemoryAccounting lunch 120` → finance
  - ` @.cache/uv/simple-v20/pypi/pycryptodomex.rkyv buy milk` → quest
  - ` @.tmux/logs/memory-guardian.log maybe we could...` → muse
- Bidirectional sync: Module events → Push to platforms
- Bot commands: Each module exposes bot commands

**Architecture**:
```
LINE/Telegram/Discord → Social Bridge → Event Bus → Core Modules
Core Modules → Event Bus → Social Bridge → LINE/Telegram/Discord
```

---

#### notification — Notification Platform

| Attribute | Value |
|----------|-------|
| **Category** | Bridge |
| **Prerequisite** | PWA (sw.js + manifest.json) |
| **Technology** | Web Push API + VAPID (primary), ntfy (fallback) |

**Capabilities**:
- Push notifications: PWA push (desktop + mobile browser)
- Notification preferences: Toggle by module, by event type
- Notification aggregation: Prevent message bombing, smart batching
- Multi-channel delivery: Push + Email + Social Hooks
- Notification history: Traceable log

---

#### media — Media Processing

| Attribute | Value |
|----------|-------|
| **Category** | Hot-path Service (located in `core/services/`) |
| **Capabilities** | STT, TTS, Image Processing, OCR |

**Current**: Part of the core hot-path services.
**Growth**: Can be extended for domain-specific processing (Music OCR, Legal Document OCR, Product Catalog OCR).

---

### Stations (Standalone Tools)

> Standalone local tools. Stations that need to push data to the Core API or provide a Widget should reference `libs/python/station-sdk/` for shared scheduling, API push, Widget formatting, and notification integration (see [AD-8](../architecture/architecture-decisions.md#ad-8-station-sdk--工作站共享層)).

#### system-monitor — System Monitor

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | Disk analysis operational (`~/.claude/data/disk-report/`, daily launchd) |
| **V2 Changes** | Frequency changed to weekly + added hardware resource pressure monitoring |

**Capabilities**:
- Disk space analysis (weekly report + monthly report + manual real-time scan)
- Hardware resource monitoring (CPU, RAM, Swap, Temperature, Battery)
- Pressure level determination (normal → warning → critical → danger)
- AI analysis report (two-layer LLM routing: API → offline fallback)
- Workbench Widget (system health status card)

---

#### llm-usage — LLM Usage Tracking

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | model-policy (boost/normal toggle) + LiteLLM Proxy |
| **V2 Changes** | Unified token/cost tracking, integrate all Providers |

**Capabilities**:
- Unified cross-provider tracking (Anthropic + OpenAI + Google + Ollama)
- Unified cross-CLI tracking (Claude Code + Codex + Gemini + LiteLLM)
- Multi-dimensional cost analysis (by Provider, Model, Caller, Time, Purpose)
- Cache efficiency statistics
- Monthly budget tracking and alerts
- Workbench Widget (cost dashboard)

---

#### envkit — Environment Toolkit

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | `~/dotfiles/` has a basic list, but lacks classification, validation, and one-click bootstrap |
| **V2 Changes** | Complete classified inventory + sequential bootstrap + validation + diff |

**Capabilities**:
- Classified inventory (AI tools, terminal, development, services, applications)
- Config map (config file location for each tool + tracking status)
- 8-stage Bootstrap Pipeline (installation flow with dependency order)
- Environment snapshot + validation (snapshot vs. actual environment comparison)
- Dual-machine Diff (compare environment differences between two machines)

---

#### tmux-webui — tmux Browser Control

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | Operational (`~/Claude/projects/tmux-webui/`, port 8765) |

**Capabilities**:
- Manage tmux sessions / windows / panes from a browser
- Send commands to a pane from the web
- Real-time system metrics display (CPU, RAM, Disk, Network)
- LLM usage at a glance

---

#### session-redactor — Transcript Sensitive Data Cleaner

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | Operational (SessionEnd hook + Daily 4 AM sweep) |

**Capabilities**:
- SessionEnd hook automatically scans .jsonl transcripts
- 16 types of sensitive pattern detection (API key, password, token, SSH, DB credentials)
- Atomic write to ensure data integrity
- SQLite to track cleaning history
- First step in SessionEnd pipeline (redact → lore extract → observability)

---

#### sandbox-executor — Batch Execution Engine

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | Operational (MCP Server, 2 tools) |

**Capabilities**:
- Python/JS sandbox execution
- SDK Helpers auto-injected (http_get/post, read_file/write_file, output)
- Batch operations (replaces multiple individual tool calls)

---

### Third-party Tools (Vendor)

> Third-party community tools that will not be refactored into the V2 architecture. Used directly, upstream updates via `git pull`.

#### observability — Multi-Agent Observability

| Attribute | Value |
|----------|-------|
| **Category** | Third-party (Vendor) |
| **Source** | [ @disler](https://github.com/disler/claude-code-hooks-multi-agent-observability) |
| **Technology** | Bun + SQLite + Vue.js |

**Capabilities**:
- Claude Code hooks real-time event tracking
- Multi-agent session monitoring
- WebSocket real-time dashboard
- Event filtering and searching

---

## Composition Recipes

> For the complete set of composition recipes, see [vision/composition-model.md](./composition-model.md)

Planned compositions:
- **Legal Advisor** = lore + scout + muse + media
- **Church Music** = media + lore + muse
- **Virtual CS** = nexus + social-hooks + quest + finance
- **ERP/POS** = finance + quest + roster + nexus

---

## Dependency Graph

```
                    ┌─────────┐
                    │  auth   │ ← Prerequisite for all services
                    └────┬────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
     │ finance │◄──►  quest  │   │  muse   │
     └─────────┘   └────┬────┘   └─────────┘
                        │
                   ┌────▼────┐
                   │  scout  │
                   └─────────┘

     ┌─────────┐   ┌─────────┐   ┌─────────┐
     │  lore   │──►│  dojo   │──►│ roster  │
     └─────────┘   └────┬────┘   └────┬────┘
                        │              │
                        └──────┬───────┘
                          ┌────▼────┐
                          │  nexus  │
                          └─────────┘

     ┌─────────┐
     │  admin  │ ← Reads from all services, does not write to any service
     └─────────┘
```

**Dependency Chain Interpretation**:
1. `auth` is the foundation for everything
2. `finance ↔ quest` bidirectional link (a task can be an order, an order is a type of task)
3. `lore → dojo → nexus → roster` is the chain from knowledge to execution
4. `scout` depends on `lore` for personalization
5. `admin` is a read-only observer

---

## Service Index

| Service | Type | Status | MCP Server | # Tools |
|---------|------|--------|------------|-------|
| auth | Foundation | V1 Exists | `workshop-auth` | TBD |
| admin | Foundation | Partial V1 | `workshop-admin` | TBD |
| finance | Domain Service | MCP Operational | `workshop-finance` | 9 |
| quest | Domain Service | MCP Operational | `workshop-quest` | 10 |
| muse | Domain Service | MCP Operational | `workshop-muse` | 8 |
| scout | Domain Service | Not started | `workshop-scout` | TBD |
| lore | Domain Service | MCP v0.2.0 | `kas-memory` | 8 |
| dojo | Domain Service | Not started | `workshop-dojo` | TBD |
| roster | Domain Service | Not started | `workshop-roster` | TBD |
| nexus | Domain Service | Not started | `workshop-nexus` | TBD |
| social-hooks | Bridge | Not started | — | — |
| notification | Bridge | Not started | — | — |
| media | Hot-path | In core/services/ | — | — |
| system-monitor | Station | V1 Operational | — | — |
| llm-usage | Station | Partial V1 | — | — |
| envkit | Station | Redesign | — | — |
| tmux-webui | Station | V1 Operational | — | — |
| session-redactor | Station | V1 Operational | — | — |
| sandbox-executor | Station | V1 Operational | MCP (2 tools) | 2 |
| observability | Vendor | Operational | — | — |

---

## Classification Summary

| Type | Item | Data Storage |
|------|-------|---------------|
| **Foundation** | auth, admin | PostgreSQL |
| **Domain Service** | finance, quest, muse, scout, lore, dojo, roster, nexus | PostgreSQL (one schema per module) |
| **Bridge** | social-hooks, notification | External + Event Bus |
| **Hot-path Service** | media (STT/TTS/Image), Live Chat (LiveKit) | Stateless processing |
| **Station** | system-monitor, llm-usage, envkit, tmux-webui, session-redactor, sandbox-executor | Local / Optional PostgreSQL |
| **Vendor** | observability ( @disler) | Runs independently |
| **Composition** | Legal Advisor, Church Music, Virtual CS, ERP/POS | Combination of the above services |
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2424ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2567ms
