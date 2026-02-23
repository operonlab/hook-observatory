---
doc_version: 1
content_hash: ace23419
---

# Domain Catalog

> Complete directory of all Workshop domains: 10 Core Modules + 5 Project Ideas + classification index.

---

## Core Modules (10)

### 1. auth — Authentication & Authorization

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | None (prerequisite for all Modules) |
| **Depended by** | All |
| **MCP Server** | `workshop-auth` |
| **V1 Status** | Exists (GitHub OAuth, Google OAuth, email/password) |

**Scope**:
- Multi-provider login (GitHub, Google, Email, future: LINE Login)
- Session management (cookie-based, `workshop_session`)
- Space management (create/invite/permissions)
- Module-level access control (per-space, per-user, per-module)
- API Key management (for MCP / external integrations)

**Space Model Core Tables**:
```
spaces: id, name, type(personal/family/friends/org), owner_id
space_members: space_id, user_id, role(owner/admin/member/guest), modules[]
```

---

### 2. finance — Accounting & Finance

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth |
| **MCP Server** | `pulso-finance` (existing, pending rename) |
| **V1 Status** | MCP Server operational |

**Scope**:
- Personal/family accounting (income/expense tracking)
- Subscription management (subscription lifecycle)
- Financial insights (monthly summary, category analysis)
- Budget planning (budget per category)
- **Growth path**: personal accounting → family shared ledger → inventory management → POS

**Widget Concepts**:
- Monthly summary card (small)
- Recent transactions list (medium)
- Category pie chart (medium)
- Full accounting interface (large)

---

### 3. quest — Tasks & Dispatch

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, skill (for quantified mode) |
| **Bidirectional** | finance (task ↔ order) |
| **MCP Server** | `pulso-quest` (existing, pending rename) |
| **V1 Status** | MCP Server operational |

**Scope**:
- **Simple Mode**: To-do list (checkbox, due date)
- **Quantified Mode**: Story points, skill requirements, complexity assessment
- **Dispatch Mode**: Task pool + passive assignment + active pickup
- **Commercial Mode**: Task = order, with quotation and acceptance

**RPG Metaphor** (from Quest Design Doc):
- Equipment = Knowledge, Skills = Competencies, Stats = Core Attributes
- Achievements = Track Record, Streak/Completion Rate = Attitude (inferred from behavior)

**Growth path**: checkbox → story points → skill requirements → task pool → order

---

### 4. muse — Ideas & Knowledge Graph

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth |
| **MCP Server** | `pulso-muse` (existing, pending rename) |
| **V1 Status** | MCP Server operational |

**Scope**:
- Spark (idea notes): Quick capture of thoughts
- Link (connections): Directed links between Sparks
- Graph (knowledge graph): Visual network of ideas
- Inbox: Pending ideas for processing
- Search (semantic search): Across all Sparks

**Widget Concepts**:
- Quick note input (small)
- Inbox list (medium)
- Knowledge graph thumbnail (large)

---

### 5. intel — Daily Intelligence

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, memory (for personalization) |
| **MCP Server** | `workshop-intel` (to be built) |
| **V1 Status** | Does not exist |

**Scope**:
- RSS / social media source management
- Automatic summary generation (LLM-powered)
- Daily briefing push
- Keyword / topic tracking
- Integration with muse (intelligence → ideas)

---

### 6. memory — LLM Memory Persistence

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth |
| **Depended by** | skill, intel |
| **MCP Server** | `kas-memory` (existing) |
| **V1 Status** | MCP Server v0.2.0 (semantic search + profile) |

**Scope**:
- SessionEnd → automatic memory extraction
- UserPromptSubmit → automatic recall of relevant memories
- Semantic search (OpenAI embedding, switchable to Ollama)
- Memory promotion / editing / tagging
- KAS Profile (user characteristic summary)
- **V2 direction**: Better forgetting mechanisms, cross-space memory isolation, multi-agent support

---

### 7. skill — Skill Trees & Learning Paths

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, memory |
| **Depended by** | matching, workforce |
| **MCP Server** | `workshop-skill` (to be built) |
| **V1 Status** | Does not exist |

**Scope**:
- Skill definition and categorization (tech tree structure)
- Learning path planning (prerequisite chain)
- Course/resource matching (matching learning resources to skill gaps)
- Capability verification (assessment, certification tracking)
- Skill levels (beginner → intermediate → advanced → expert)

---

### 8. workforce — Resource Management

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, skill |
| **Depended by** | matching |
| **MCP Server** | `workshop-workforce` (to be built) |
| **V1 Status** | Does not exist |

**Scope**:
- **Resource Abstraction** (unified model): human = machine = service = AI agent
- Common attributes: capabilities[], capacity, availability, cost_rate, status
- Workload tracking (current load vs max capacity)
- Scheduling / availability management
- **Growth path**: personal task tracking → team hours → machine/service resource pool → full ERP

**Unified Resource Model**:
```
resources:
  id, type(human/machine/service/agent),
  name, capabilities[], capacity,
  availability_schedule, cost_rate, status
```

---

### 9. matching — Matching Engine

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, skill, workforce |
| **MCP Server** | `workshop-matching` (to be built) |
| **V1 Status** | Does not exist |

**Scope**:
- Talent × job matching
- Capability × task pairing (engine behind quest dispatch)
- Learning resource recommendations (skill gap → course suggestion)
- Multi-dimensional scoring (skills match, availability, cost, history)
- **Three use cases**: matching, assignment, learning path recommendation — all on the same data model

---

### 10. admin — Platform Management

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth |
| **MCP Server** | `workshop-admin` (to be built) |
| **V1 Status** | V1 has sysmon + agent-metrics (merged into gateway) |

**Scope**:
- System health monitoring (evolved from sysmon)
- User management
- Module enable/disable control
- System configuration
- Audit logging

---

## Project Ideas (5 Standalone Projects)

The following are larger-scale projects that may become independent Stations or Core Modules.

### P1. Legal Advisor

| Property | Value |
|----------|-------|
| **Classification** | Station → upgradable to Core Module |
| **Core Function** | Case law search + statute lookup + court hearing simulation |
| **Technical Focus** | RAG over legal documents, LLM reasoning |

**Envisioned Features**:
1. **Case Law Search**: Input case details, find relevant precedents and cited statutes
2. **Legal Document Generation**: Draft legal documents based on case details
3. **Court Hearing Simulation**: Simulate judge's stance + opposing counsel's arguments (based on publicly available data)
4. **Strategy Compilation**: Compile our strategy based on simulation results

**Data Sources**: Judicial Yuan judgment query system, National Legislation Database (Taiwan)

---

### P2. Church Music Digitization

| Property | Value |
|----------|-------|
| **Classification** | Station |
| **Core Function** | Sheet music OCR → digital archive → auto accompaniment/vocal synthesis |
| **Technical Focus** | Music OCR, Audio synthesis |

**Envisioned Features**:
1. **Sheet Music Scanning + OCR**: Paper scores → digital format (MusicXML / MIDI)
2. **Library Management**: Indexed by stroke count, metadata (key, time signature, original source)
3. **Accompaniment Generation**: MIDI → backing tracks (piano/guitar/strings)
4. **Electronic Vocal Synthesis**: Melody + lyrics → synthesized vocals
5. **Human Review Workflow**: Auto-generate → human review/edit → publish

---

### P3. Virtual Customer Service

| Property | Value |
|----------|-------|
| **Classification** | Bridge + Core Module |
| **Core Function** | Requirement understanding → product matching → quotation generation |
| **Technical Focus** | NLU, Product catalog OCR, LINE Bot |

**Envisioned Features**:
1. **Product Digitization**: Physical product catalogs via OCR → structured database
2. **Requirement Understanding**: Customer describes needs → keyword extraction → condition matching
3. **Product Recommendation**: Requirements × product catalog → ranked suggestions
4. **Quotation Generation**: Selected products → auto-generate quotation (PDF/HTML)
5. **LINE Bot Frontend**: Customer completes entire flow via LINE chat

**Integration with Workshop**:
- Product catalog → Core Module (similar to muse's knowledge base)
- Quotation → finance module
- Customer service conversation → quest (auto-create task tracking)

---

### P4. Social Platform Hooks

| Property | Value |
|----------|-------|
| **Classification** | Bridge |
| **Priority Order** | LINE > Telegram > Discord > Facebook > X |
| **Technical Focus** | Webhook, Bot API, Event routing |

**Envisioned Features**:
1. **Unified Messaging**: All platform messages flow into a unified inbox
2. **Event Routing**: Route messages to corresponding Modules based on rules
   - `@accounting lunch 120` → finance
   - `@todo buy milk` → quest
   - `@memo maybe we could...` → muse
3. **Bidirectional Sync**: Module events → push to designated platforms
4. **Bot Commands**: Each Module exposes bot commands

**Integration Architecture**:
```
LINE/Telegram/Discord → Social Bridge → Event Bus → Core Modules
Core Modules → Event Bus → Social Bridge → LINE/Telegram/Discord
```

---

### P5. Notification Platform

| Property | Value |
|----------|-------|
| **Classification** | Bridge |
| **Technology Options** | Firebase Cloud Messaging / Web Push API / ntfy |
| **Prerequisite** | PWA already designed into Workshop Web (sw.js + manifest.json) |

**Envisioned Features**:
1. **Push Notifications**: PWA push (desktop + mobile browser)
2. **Notification Preferences**: Per-module, per-event-type toggle
3. **Notification Aggregation**: Prevent notification bombing, intelligent batching
4. **Multi-Channel Dispatch**: Push + Email + Social Hooks (P4)
5. **Notification History**: Traceable notification log

**Technology Assessment**:
- **Firebase Cloud Messaging**: Most mature, but vendor lock-in
- **Web Push API + VAPID**: Standards-based, self-controlled
- **ntfy**: Open source, self-hosted, lightweight
- **Recommendation**: Start with Web Push API (PWA native), with ntfy as fallback

---

## Domain Dependency Graph

```
                    ┌─────────┐
                    │  auth   │ ← prerequisite for ALL
                    └────┬────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
     │ finance │◄──►  quest  │   │  muse   │
     └─────────┘   └────┬────┘   └─────────┘
                        │
                   ┌────▼────┐
                   │  intel  │
                   └─────────┘

     ┌─────────┐   ┌─────────┐   ┌───────────┐
     │ memory  │──►│  skill  │──►│ workforce │
     └─────────┘   └────┬────┘   └─────┬─────┘
                        │              │
                        └──────┬───────┘
                          ┌────▼────┐
                          │matching │
                          └─────────┘

     ┌─────────┐
     │  admin  │ ← reads from all, writes to none
     └─────────┘
```

**Dependency Chain Interpretation**:
1. `auth` is the foundation for everything
2. `finance ↔ quest` bidirectional (tasks can be orders, orders are a type of task)
3. `memory → skill → matching → workforce` is the knowledge-to-execution chain
4. `intel` depends on `memory` for personalization
5. `admin` is a read-only observer

---

## Taxonomy Classification Summary

| Type | Items | Data Residency |
|------|-------|---------------|
| **Core Module** | auth, finance, quest, muse, intel, memory, skill, workforce, matching, admin | PostgreSQL |
| **Station** | Disk analysis, LLM Usage, local tools, Legal Advisor, Church Music | Local / Optional DB |
| **Bridge** | Social Hooks, Notification, External APIs, OCR Services, Virtual CS | External + Event Bus |
