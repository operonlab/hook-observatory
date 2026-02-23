---
doc_version: 3
content_hash: 2ec4dc04
source_version: 3
translated_at: 2026-02-23
---

# Service Catalog

> Unified catalog of all Workshop services. No distinction between "core modules" and "projects" — everything is a composable service block.

---

> For the LEGO Composition Model and Composition Recipes, see [architecture/composition-model.md](../architecture/composition-model.md)

---

## Services

### Foundation

#### auth — Authentication & Authorization

| Property | Value |
|----------|-------|
| **Dependencies** | None (prerequisite for all) |
| **Depended by** | All |
| **MCP Server** | `workshop-auth` |
| **V1 Status** | Exists (GitHub OAuth, Google OAuth, email/password) |

**Capabilities**:
- Multi-provider login (GitHub, Google, Email, future: LINE Login)
- Session management (cookie-based, `workshop_session`)
- Space management (create/invite/permissions)
- Module-level access control (per-space, per-user, per-module)
- API Key management (for MCP / external integrations)

**Space Model** (sharing scope):
```
spaces: id, name, type(personal/family/friends/org), owner_id
space_members: space_id, user_id, role(owner/admin/member/guest), modules[]
```

---

#### admin — Platform Management

| Property | Value |
|----------|-------|
| **Dependencies** | auth |
| **MCP Server** | `workshop-admin` (to be built) |
| **V1 Status** | V1 has sysmon + agent-metrics (merged into gateway) |

**Capabilities**:
- System health monitoring (evolved from sysmon)
- User management
- Module enable/disable control
- System configuration
- Audit logging

---

### Domain Services

#### finance — Accounting & Finance

| Property | Value |
|----------|-------|
| **Dependencies** | auth |
| **MCP Server** | `pulso-finance` (existing, pending rename → `workshop-finance`) |
| **V1 Status** | MCP Server operational (9 tools) |

**Capabilities**:
- Personal/family accounting (income/expense tracking)
- Subscription management (subscription lifecycle)
- Financial insights (monthly summary, category analysis)
- Budget planning (budget per category)

**Growth path** (Progressive Complexity):
```
Phase 1: Personal accounting
Phase 2: + Family shared ledger
Phase 3: + Budget/analysis
Phase 4: + Inventory management / POS
```

---

#### quest — Tasks & Dispatch

| Property | Value |
|----------|-------|
| **Dependencies** | auth, dojo (for quantified mode) |
| **Bidirectional** | finance (task ↔ order) |
| **MCP Server** | `pulso-quest` (existing, pending rename → `workshop-quest`) |
| **V1 Status** | MCP Server operational (10 tools) |

**Capabilities**:
- **Simple Mode**: To-do list (checkbox, due date)
- **Quantified Mode**: Story points, skill requirements, complexity assessment
- **Dispatch Mode**: Task pool + passive assignment + active pickup
- **Commercial Mode**: Task = order, with quotation and acceptance

**RPG Metaphor** (from Quest Design Doc):
- Equipment = Knowledge, Skills = Competencies, Stats = Core Attributes
- Achievements = Track Record, Streak/Completion Rate = Attitude (inferred from behavior)

**Growth path**:
```
Phase 1: Checkbox to-do
Phase 2: + Story points
Phase 3: + Skill requirements + Task pool
Phase 4: + Orders / quotation / acceptance
```

---

#### muse — Ideas & Knowledge Graph

| Property | Value |
|----------|-------|
| **Dependencies** | auth |
| **MCP Server** | `pulso-muse` (existing, pending rename → `workshop-muse`) |
| **V1 Status** | MCP Server operational (8 tools) |

**Capabilities**:
- Spark (idea notes): Quick capture of thoughts
- Link (connections): Directed links between Sparks
- Graph (knowledge graph): Visual network of ideas
- Inbox: Pending ideas for processing
- Search (semantic search): Across all Sparks

---

#### scout — Daily Intelligence

| Property | Value |
|----------|-------|
| **Dependencies** | auth, lore (for personalization) |
| **MCP Server** | `workshop-scout` (to be built) |
| **V1 Status** | Does not exist |

**Capabilities**:
- RSS / social media source management
- Automatic summary generation (LLM-powered)
- Daily briefing push
- Keyword / topic tracking
- Integration with muse (intelligence → ideas)

---

#### lore — LLM Memory Persistence

| Property | Value |
|----------|-------|
| **Dependencies** | auth |
| **Depended by** | dojo, scout |
| **MCP Server** | `kas-memory` (existing, 8 tools) |
| **V1 Status** | MCP Server v0.2.0 (semantic search + profile) |

**Capabilities**:
- SessionEnd → automatic memory extraction
- UserPromptSubmit → automatic recall of relevant memories
- Semantic search (OpenAI embedding, switchable to Ollama)
- Memory promotion / editing / tagging
- KAS Profile (user characteristic summary)
- **V2 direction**: Better forgetting, cross-space isolation, multi-agent support

---

#### dojo — Skill Trees & Learning Paths

| Property | Value |
|----------|-------|
| **Dependencies** | auth, lore |
| **Depended by** | nexus, roster |
| **MCP Server** | `workshop-dojo` (to be built) |
| **V1 Status** | Does not exist |

**Capabilities**:
- Skill definition and categorization (tech tree structure)
- Learning path planning (prerequisite chain)
- Course/resource matching (skill gaps → learning resources)
- Capability verification (assessment, certification tracking)
- Skill levels (beginner → intermediate → advanced → expert)

---

#### roster — Resource Management

| Property | Value |
|----------|-------|
| **Dependencies** | auth, dojo |
| **Depended by** | nexus |
| **MCP Server** | `workshop-roster` (to be built) |
| **V1 Status** | Does not exist |

**Capabilities**:
- **Unified Resource Abstraction**: human = machine = service = AI agent
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

**Growth path**:
```
Phase 1: Personal task tracking
Phase 2: + Team hours
Phase 3: + Machine/service resource pool
Phase 4: + Full ERP resource management
```

---

#### nexus — Matching Engine

| Property | Value |
|----------|-------|
| **Dependencies** | auth, dojo, roster |
| **MCP Server** | `workshop-nexus` (to be built) |
| **V1 Status** | Does not exist |

**Capabilities**:
- Talent × job matching
- Capability × task pairing (engine behind quest dispatch)
- Learning resource recommendations (skill gap → course suggestion)
- Multi-dimensional scoring (skills match, availability, cost, history)
- Three use cases on same model: matching, assignment, learning path

---

### Integration Services (Bridges)

#### social-hooks — Social Platform Connectors

| Property | Value |
|----------|-------|
| **Classification** | Bridge |
| **Priority** | LINE > Telegram > Discord > Facebook > X |
| **Provides to** | All Core Modules via Event Bus routing |

**Capabilities**:
- Unified messaging: All platform messages → unified inbox
- Event routing: Route messages to Modules based on rules
  - ` @Library/Developer/Xcode/iOS DeviceSupport/iPhone16,2 26.2.1 (23C71)/Symbols/System/Library/PrivateFrameworks/MemoryAccounting.framework/MemoryAccounting lunch 120` → finance
  - ` @.cache/uv/simple-v20/pypi/pycryptodomex.rkyv buy milk` → quest
  - ` @Claude/backups/2026-02-23/2026-02-16-macos-memory-pressure-reboot.md maybe we could...` → muse
- Bidirectional sync: Module events → push to platforms
- Bot commands: Each Module exposes bot commands

**Architecture**:
```
LINE/Telegram/Discord → Social Bridge → Event Bus → Core Modules
Core Modules → Event Bus → Social Bridge → LINE/Telegram/Discord
```

---

#### notification — Notification Platform

| Property | Value |
|----------|-------|
| **Classification** | Bridge |
| **Prerequisite** | PWA (sw.js + manifest.json) |
| **Technology** | Web Push API + VAPID (primary), ntfy (fallback) |

**Capabilities**:
- Push notifications: PWA push (desktop + mobile browser)
- Notification preferences: Per-module, per-event-type toggle
- Notification aggregation: Prevent bombing, intelligent batching
- Multi-channel dispatch: Push + Email + Social Hooks
- Notification history: Traceable log

---

#### media — Media Processing

| Property | Value |
|----------|-------|
| **Classification** | Hot-path Service (in `core/services/`) |
| **Capabilities** | STT, TTS, Image processing, OCR |

**Current**: Part of core hot-path services.
**Growth**: Extensible for domain-specific processing (Music OCR, legal document OCR, product catalog OCR).

---

### Stations (Standalone Tools)

> Standalone local tools that don't necessarily need a database. May be CLIs, desktop utilities, or analysis scripts.
> Stations can run independently without FastAPI Core, but may optionally push data to Core.

- Disk analysis / system resource monitoring
- LLM usage tracking
- Local file management tools
- Claude Code Skills (diagram-gen, pdf, ocr, etc.)

---

## Composition Recipes

> For full Composition Recipes, see [architecture/composition-model.md](../architecture/composition-model.md)

Planned compositions:
- **Legal Advisor** = lore + scout + muse + media
- **Church Music** = media + lore + muse
- **Virtual CS** = nexus + social-hooks + quest + finance
- **ERP/POS** = finance + quest + roster + nexus

---

## Dependency Graph

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
                   │  scout  │
                   └─────────┘

     ┌─────────┐   ┌─────────┐   ┌───────────┐
     │  lore   │──►│  dojo   │──►│  roster   │
     └─────────┘   └────┬────┘   └─────┬─────┘
                        │              │
                        └──────┬───────┘
                          ┌────▼────┐
                          │  nexus  │
                          └─────────┘

     ┌─────────┐
     │  admin  │ ← reads from all, writes to none
     └─────────┘
```

**Dependency Chain Interpretation**:
1. `auth` is the foundation for everything
2. `finance ↔ quest` bidirectional (tasks can be orders, orders are a type of task)
3. `lore → dojo → nexus → roster` is the knowledge-to-execution chain
4. `scout` depends on `lore` for personalization
5. `admin` is a read-only observer

---

## Service Index

| Service | Type | Status | MCP Server | Tools |
|---------|------|--------|------------|-------|
| auth | Foundation | V1 exists | `workshop-auth` | TBD |
| admin | Foundation | Partial V1 | `workshop-admin` | TBD |
| finance | Domain | MCP operational | `workshop-finance` | 9 |
| quest | Domain | MCP operational | `workshop-quest` | 10 |
| muse | Domain | MCP operational | `workshop-muse` | 8 |
| scout | Domain | Not started | `workshop-scout` | TBD |
| lore | Domain | MCP v0.2.0 | `kas-memory` | 8 |
| dojo | Domain | Not started | `workshop-dojo` | TBD |
| roster | Domain | Not started | `workshop-roster` | TBD |
| nexus | Domain | Not started | `workshop-nexus` | TBD |
| social-hooks | Bridge | Not started | — | — |
| notification | Bridge | Not started | — | — |
| media | Hot-path | In core/services/ | — | — |

---

## Classification Summary

| Type | Items | Data Residency |
|------|-------|---------------|
| **Foundation** | auth, admin | PostgreSQL |
| **Domain Service** | finance, quest, muse, scout, lore, dojo, roster, nexus | PostgreSQL (schema-per-module) |
| **Bridge** | social-hooks, notification | External + Event Bus |
| **Hot-path Service** | media (STT/TTS/image), realtime (LiveKit) | Stateless processing |
| **Station** | Disk analysis, LLM Usage, local tools, Claude Code Skills | Local / Optional DB |
| **Composition** | Legal Advisor, Church Music, Virtual CS, ERP/POS | Assembly of above services |
