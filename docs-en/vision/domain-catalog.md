---
doc_version: 3
content_hash: 2ec4dc04
source_version: 3
target_lang: en
translated_at: 2026-02-24
source_hash: e891bdd9
source_lang: zh-TW
---

# Service Catalog

> A unified catalog for Workshop services. No distinction between "core modules" and "projects"——everything is a composable service building block.

---

> For LEGO composition models and recipes, please see [vision/composition-model.md](./composition-model.md)

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

**Functional Capabilities**:
- Multi-provider login (GitHub, Google, Email, future: LINE Login)
- Session management (cookie-based, `workshop_session`)
- Space management (create/invite/permissions)
- Module-level access control (by space, by user, by module)
- API key management (for MCP / external integrations)

**Space Model** (shared scope):
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

**Functional Capabilities**:
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
| **V1 Status** | MCP server is operational (9 tools) |

**Functional Capabilities**:
- Personal/family bookkeeping (income/expense tracking)
- Subscription management (subscription lifecycle)
- Financial insights (monthly summaries, category analysis)
- Budget planning (budgeting by category)

**Growth Path** (progressive complexity):
```
Stage 1: Personal bookkeeping
Stage 2: + Shared family ledger
Stage 3: + Budgeting/Analysis
Stage 4: + Inventory Management / POS
```

---

#### quest — Tasks & Dispatch

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth, dojo (for quantified mode) |
| **Bidirectional Link** | finance (task ↔ order) |
| **MCP Server** | `workshop-quest` |
| **V1 Status** | MCP server is operational (10 tools) |

**Functional Capabilities**:
- **Simple Mode**: To-do list (checkboxes, due dates)
- **Quantified Mode**: Story points, skill requirements, complexity assessment
- **Dispatch Mode**: Task pool + passive assignment + active acceptance
- **Business Mode**: Task = Order, including quotes and acceptance

**RPG Metaphor** (from Quest design document):
- Equipment = Knowledge, Skills = Competencies, Attributes = Core Traits
- Achievements = Track Record, Streaks/Completion Rate = Attitude (inferred from behavior)

**Growth Path**:
```
Stage 1: Checkbox to-do list
Stage 2: + Story points
Stage 3: + Skill requirements + Task pool
Stage 4: + Orders / Quotes / Acceptance
```

---

#### muse — Inspiration & Knowledge Graph

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth |
| **MCP Server** | `workshop-muse` |
| **V1 Status** | MCP server is operational (8 tools) |

**Functional Capabilities**:
- Spark (Inspiration Note): Quickly capture ideas
- Link: Directed connections between Sparks
- Graph (Knowledge Graph): A visual network of ideas
- Inbox: unprocessed inspirations
- Search (Semantic Search): Search across all Sparks

---

#### scout — Search & Intelligence

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth, lore (for personalization) |
| **MCP Server** | `workshop-scout` (to be built) |
| **Integrated Skills** | smart-search, daily-briefing, company-intel, competitive-intel, content-writer |
| **V1 Status** | research_report service (port 8830) + smart-search skill v0.3.3 |

**Functional Capabilities**:
- RSS / social media source management
- Automatic summary generation (LLM-driven)
- Daily briefing push
- Keyword / topic tracking
- Integration with muse (intelligence → inspiration)

---

#### lore — LLM Memory Persistence

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth |
| **Depended on by** | dojo, scout |
| **MCP Server** | `kas-memory` (existing, 8 tools) |
| **Integrated Skills** | kas-memory (MCP), meeting-insights |
| **V1 Status** | MCP server v0.2.0 (semantic search + user profile) |

**Functional Capabilities**:
- Session end → automatic memory extraction
- User prompt submission → automatic recall of relevant memories
- Semantic search (OpenAI embedding, switchable to Ollama)
- Memory promotion / editing / tagging
- KAS Profile (user trait summary)
- **V2 Direction**: Better forgetting mechanisms, cross-space isolation, multi-agent support

---

#### dojo — Skill Tree & Learning Path

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth, lore |
| **Depended on by** | nexus, roster |
| **MCP Server** | `workshop-dojo` (to be built) |
| **Integrated Skills** | skill-catalog, skill-graph, skill-optimizer, model-mentor |
| **V1 Status** | Does not exist |

**Functional Capabilities**:
- Skill definition and categorization (tech tree structure)
- Learning path planning (prerequisite chains)
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

**Functional Capabilities**:
- **Unified Resource Abstraction**: Human = Machine = Service = AI Agent
- Common attributes: capabilities[], capacity, availability, cost_rate, status
- Workload tracking (current load vs max capacity)
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
Stage 1: Personal task tracking
Stage 2: + Team timesheets
Stage 3: + Machine/Service resource pool
Stage 4: + Full ERP resource management
```

---

#### nexus — Matching Engine

| Attribute | Value |
|----------|-------|
| **Dependencies** | auth, dojo, roster |
| **MCP Server** | `workshop-nexus` (to be built) |
| **V1 Status** | Does not exist |

**Functional Capabilities**:
- Talent × Position matching
- Capability × Task pairing (the engine behind quest dispatch)
- Learning resource recommendation (skill gap → course suggestions)
- Multi-dimensional scoring (skill match, availability, cost, history)
- Three use cases with the same model: matching, allocation, learning paths

---

### Integration Services (Bridges)

#### social-hooks — Social Platform Connectors

| Attribute | Value |
|----------|-------|
| **Category** | Bridge |
| **Priority** | LINE > Telegram > Discord > Facebook > X |
| **Provided to** | Routed to all core modules via Event Bus |

**Functional Capabilities**:
- Unified Messaging: All platform messages → unified inbox
- Event Routing: Route messages to various modules based on rules
  - ` @Library/Developer/Xcode/iOS DeviceSupport/iPhone16,2 26.2.1 (23C71)/Symbols/System/Library/PrivateFrameworks/MemoryAccounting.framework/MemoryAccounting lunch 120` → finance
  - ` @.cache/uv/simple-v20/pypi/pycryptodomex.rkyv buy milk` → quest
  - ` @.tmux/logs/memory-guardian.log maybe we could...` → muse
- Bidirectional Sync: Module events → push to platforms
- Bot Commands: Each module exposes bot commands

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

**Functional Capabilities**:
- Push Notifications: PWA push (desktop + mobile browser)
- Notification Preferences: Toggle by module, by event type
- Notification Aggregation: Prevents message bombing, intelligent batching
- Multi-channel Delivery: Push + Email + Social Hooks
- Notification History: Traceable log

---

#### media — Media Processing

| Attribute | Value |
|----------|-------|
| **Category** | Hot-path service (located in `core/services/`) |
| **Functional Capabilities**| STT, TTS, Image Processing, OCR |

**Current**: Part of the core hot-path services.
**Growth**: Can be extended for domain-specific processing (Music OCR, Legal Document OCR, Product Catalog OCR).

---

### Stations (Independent Tools)

> Standalone local tools. Stations that need to push data to Core APIs or provide Widgets should reference `libs/python/station-sdk/` for shared scheduling, API push, widget formatting, and notification integration (see [AD-8](../architecture/architecture-decisions.md#ad-8-station-sdk--工作站共享層)).

#### system-monitor — System Monitor

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | Disk analysis is operational (`~/.claude/data/disk-report/`, daily launchd) |
| **V2 Changes** | Frequency changed to weekly + new hardware resource pressure monitoring |

**Functional Capabilities**:
- Disk space analysis (weekly + monthly reports + manual on-demand scan)
- Hardware resource monitoring (CPU, RAM, Swap, Temperature, Battery)
- Pressure level determination (normal → warning → critical → danger)
- AI analysis report (two-layer LLM routing: API → offline fallback)
- Workbench Widget (system health status card)

---

#### llm-usage — LLM Usage Tracker

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | model-policy (boost/normal switching) + LiteLLM Proxy |
| **V2 Changes** | Unified token/cost tracking, integrate all providers |

**Functional Capabilities**:
- Unified tracking across providers (Anthropic + OpenAI + Google + Ollama)
- Unified tracking across CLIs (Claude Code + Codex + Gemini + LiteLLM)
- Multi-dimensional cost analysis (by Provider, Model, Caller, Time, Purpose)
- Cache efficiency statistics
- Monthly budget tracking and alerts
- Workbench Widget (cost dashboard)

---

#### envkit — Environment Toolkit

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | `~/dotfiles/` has a basic list, but lacks categorization, validation, one-click bootstrap |
| **V2 Changes** | Complete categorized inventory + sequential bootstrap + validation + diff |

**Functional Capabilities**:
- Categorized inventory (AI tools, terminal, development, services, applications)
- Config mapping table (config file location for each tool + tracking status)
- 8-stage Bootstrap Pipeline (installation process with dependency order)
- Environment snapshot + validation (snapshot vs. actual environment comparison)
- Two-machine Diff (compare environment differences between two machines)

---

#### sandbox-executor — Batch Execution Engine

| Attribute | Value |
|----------|-------|
| **Category** | Station |
| **V1 Status** | Operational (MCP Server, 2 tools) |

**Functional Capabilities**:
- Python/JS sandbox execution
- SDK Helpers auto-injection (http_get/post, read_file/write_file, output)
- Batch operations (replaces multiple individual tool calls)

---

## Composition Recipes

> For complete composition recipes, please see [vision/composition-model.md](./composition-model.md)

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
     │  admin  │ ← Reads from all services, writes to none
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

| Service | Type | Status | MCP Server | Tool Count |
|---------|------|--------|------------|-------|
| auth | Foundation | V1 Exists | `workshop-auth` | TBD |
| admin | Foundation | Partial V1 | `workshop-admin` | TBD |
| finance | Domain Service | MCP Operational | `workshop-finance` | 9 |
| quest | Domain Service | MCP Operational | `workshop-quest` | 10 |
| muse | Domain Service | MCP Operational | `workshop-muse` | 8 |
| scout | Domain Service | Not Started | `workshop-scout` | TBD |
| lore | Domain Service | MCP v0.2.0 | `kas-memory` | 8 |
| dojo | Domain Service | Not Started | `workshop-dojo` | TBD |
| roster | Domain Service | Not Started | `workshop-roster` | TBD |
| nexus | Domain Service | Not Started | `workshop-nexus` | TBD |
| social-hooks | Bridge | Not Started | — | — |
| notification | Bridge | Not Started | — | — |
| media | Hot-path | In core/services/ | — | — |
| system-monitor | Station | V1 Operational | — | — |
| llm-usage | Station | Partial V1 | — | — |
| envkit | Station | Redesign | — | — |
| sandbox-executor | Station | V1 Operational | MCP (2 tools) | 2 |

---

## Classification Summary

| Type | Item | Data Storage |
|------|-------|---------------|
| **Foundation** | auth, admin | PostgreSQL |
| **Domain Service** | finance, quest, muse, scout, lore, dojo, roster, nexus | PostgreSQL (one schema per module) |
| **Bridge** | social-hooks, notification | External + Event Bus |
| **Hot-path Service** | media (STT/TTS/Image), real-time messaging (LiveKit) | Stateless processing |
| **Station** | system-monitor, llm-usage, envkit, sandbox-executor | Local / Optional PostgreSQL |
| **Composition** | Legal Advisor, Church Music, Virtual CS, ERP/POS | Combination of the above services |
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2437ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2448ms
