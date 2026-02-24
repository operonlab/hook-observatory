---
doc_version: 3
content_hash: 4ad88f87
source_version: 3
target_lang: en
translated_at: 2026-02-24
source_hash: da064234
source_lang: zh-TW
---

# Lego Combo Model — Workshop Development Methodology

> Services are reusable blocks. Projects are assemblies of blocks. No distinction between "projects" and "modules" - only services and combinations.

---

## Dual-pronged Attack

The Workshop development model proceeds both top-down and bottom-up simultaneously:

```
Top-down (Requirements → Blueprint → To-do List)
    │
    ▼         ┌───────────────────────────────┐
    ├────────►│  Convergence Point: Block Capabilities  │
    │         │  ≥ Requirements = Ready to ship     │
    ▲         └───────────────────────────────┘
    │
Bottom-up (Building reusable service blocks)
```

### Bottom-up: Building Service Blocks

Each service is a Lego block with:
- A clear **capability boundary** (finance handles money, quest handles tasks, nexus handles matching)
- A clear **API interface** (REST endpoints + MCP tools + event types)
- A clear **growth path** (progressive complexity — new capabilities added at each stage)

### Top-down: Analyzing Requirements

When a new requirement arrives ("I want a legal advisor," "I want a POS system"):
1. Analyze what capabilities are needed
2. Inventory which existing services already cover them
3. Design a blueprint: what needs to be extended, what needs to be added
4. Break down into to-do items

### Convergence Point: Compounding Effect

Each new project expands the capabilities of existing services:
- Expanding lore for the legal advisor → The RAG capability strengthens lore itself
- Expanding nexus for the virtual agent → The matching engine becomes more generic

The more numerous and mature the services, the faster new projects can be assembled—this is the **compounding effect**.

---

## Combination Recipes

> The essence of a "project": Select service blocks → Extend required capabilities → Assemble into a dedicated solution.

### Recipe One: Legal Advisor

```
lore   ──► Legal document RAG (judicial document embedding)
scout  ──► Case law search (judicial database + legal database)
muse   ──► Strategy compilation (legal argument knowledge graph)
media  ──► Paper document OCR
```

| Service | Capabilities to Extend |
|---|---|
| lore | Legal document embedding pipeline (RAG based on judicial database) |
| scout | Judicial Yuan judgments / National laws database connector |
| muse | Strategy compilation templates, legal argument knowledge graph |
| media | Legal document OCR (paper → digital) |

**Expected Flow**:
1. Input case details → scout searches for relevant precedents and laws
2. lore retrieves past similar analyses via RAG
3. muse constructs a strategy knowledge graph (arguments + counter-arguments)
4. Simulate court hearing: LLM reasons based on all inputs
5. Output: Strategy compilation document

**Data Sources**: Taiwan Judicial Yuan Judgment Inquiry System, National Laws and Regulations Database

---

### Recipe Two: Church Music Digitization

```
media  ──► Sheet music OCR (paper → MusicXML/MIDI)
lore   ──► Music metadata indexing (stroke count, key, time signature)
muse   ──► Music library management (indexing, search)
media  ──► Audio synthesis (accompaniment + vocals)
```

| Service | Capabilities to Extend |
|---|---|
| media | Sheet music OCR → MusicXML/MIDI output |
| media | Audio synthesis (MIDI → accompaniment, melody+lyrics → vocals) |
| lore | Music metadata indexing (stroke count, key, time signature, original source) |
| muse | Music library management, search/browse interface |

**Expected Flow**:
1. Scan paper sheet music → media (sheet music OCR) → digital format
2. Save to lore with associated metadata
3. Browse/search through the muse music library
4. Generate accompaniment / synthesize vocals via media
5. Manual review: Auto-generate → Manual edit → Publish

---

### Recipe Three: Virtual Agent

```
media        ──► Product catalog OCR (paper → structured database)
nexus        ──► Requirements × Product Catalog → Ranked recommendations
social-hooks ──► LINE Bot as client-side frontend
quest        ──► Customer inquiry → Auto-create task for tracking
finance      ──► Quote generation (PDF/HTML)
```

| Service | Capabilities to Extend |
|---|---|
| media | Product catalog OCR → Structured database |
| nexus | Product catalog × requirements matching engine |
| quest | Customer inquiry → Auto-create task for tracking |
| finance | Quote generation (PDF/HTML) |
| social-hooks | LINE Bot customer service conversational flow |

---

### Recipe Four: ERP / POS

```
finance    ──► Inventory management + POS transaction flow
quest      ──► Order lifecycle (quote → order acceptance → shipping)
roster     ──► Machine/equipment resource tracking
nexus      ──► Resource allocation optimization
```

| Service | Capabilities to Extend |
|---|---|
| finance | Inventory management, POS transaction flow, inventory tracking |
| quest | Order lifecycle (quote → order acceptance → shipping → invoicing) |
| roster | Machine/equipment resource tracking, maintenance scheduling |
| nexus | Resource allocation optimization (manpower + machines) |

**Growth Path**: This is the natural convergence point when finance + quest + roster each mature to Phase 4.

---

## Decision Process: What to do when a new requirement arrives?

```
New requirement arrives
    │
    ▼
Inventory: What capabilities are needed?
    │
    ├──► Covered by existing services → Assemble directly, write combination recipe
    │
    ├──► Partially covered → Extend existing service capabilities + Assemble
    │
    └──► Completely new domain → Evaluate if it's worth building a new service block
              │
              ├──► Worth it (will be reused by multiple recipes) → Build new service
              └──► Not worth it (one-time need) → Station or Script
```

## Relationship with Other Architecture Documents

| Document | Relationship |
|---|---|
| [principles.md](../architecture/principles.md) | Composition over inheritance, KISS, and YAGNI are the theoretical foundations of this model |
| [modular-monolith.md](../architecture/modular-monolith.md) | The technical implementation method for service blocks |
| [event-driven.md](../architecture/event-driven.md) | Services are loosely coupled via events—the glue for composition |
| [domain-catalog.md](./domain-catalog.md) | The complete catalog of all service blocks |
| [shared-layer-patterns.md](../architecture/shared-layer-patterns.md) | Shared patterns within blocks (OOP patterns) |
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2488ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2647ms
