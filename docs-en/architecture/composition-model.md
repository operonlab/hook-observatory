---
doc_version: 2
content_hash: 1b18bfd2
source_version: 2
translated_at: 2026-02-23
---

# LEGO Composition Model — Workshop Development Methodology

> Services are reusable building blocks. Projects are the assembly of blocks. There is no distinction between "projects" and "modules" — only services and composition.

---

## Two-Way Attack

The Workshop development model advances simultaneously from top-down and bottom-up:

```
Top-Down (Requirement Analysis → Blueprint → Todo)
    │
    ▼         ┌───────────────────────────┐
    ├────────►│  Convergence: Block Capability ≥ Requirement │
    │         │  = Project Completed, Ready for Delivery    │
    ▲         └───────────────────────────┘
    │
Bottom-Up (Building Reusable Service Blocks)
```

### Bottom-Up: Building Service Blocks

Every service is a piece of LEGO:
- Clear **capability boundaries** (finance manages money, quest manages tasks, nexus manages matching)
- Clear **API surface** (REST endpoints + MCP tools + Event types)
- Clear **expansion path** (Progressive Complexity, adding new capabilities each Phase)

### Top-Down: Analyzing Requirements

When a new requirement arises ("I want a legal consultant", "I want to build a POS"):
1. Analyze which capabilities are needed
2. Inventory which existing services already cover them
3. Design a blueprint: what to expand, what to add
4. Deconstruct into a todo list

### Convergence: The Compound Interest Effect

Every new project expansion of the capability scope of existing services:
- Expanding lore for a legal consultant → RAG capabilities simultaneously strengthen lore itself
- Expanding nexus for a virtual customer service → the matching engine becomes more generic simultaneously

The more services and the more mature they are, the faster assembling new projects becomes — this is the **Compound Interest Effect**.

---

## Composition Recipes

> The essence of a "Project": Selecting service blocks → Expanding required capabilities → Assembling into a customized solution.

### Recipe 1: Legal Consultant

```
lore   ──► Legal Document RAG (Judicial Document Embedding)
scout  ──► Precedent Search (Judicial Yuan + Regulatory Database)
muse   ──► Strategy Compilation (Legal Argument Knowledge Graph)
media  ──► Physical Document OCR
```

| Service | Capabilities to Expand |
|------|-------------|
| lore | Legal document embedding pipeline (RAG over judicial database) |
| scout | Judicial Yuan Judgments / National Laws and Regulations Database connectors |
| muse | Strategy compilation templates, legal argument knowledge graph |
| media | Legal document OCR (Physical → Digital) |

**Expected Workflow**:
1. Input case details → scout searches relevant precedents and laws
2. lore retrieves similar past analyses via RAG
3. muse constructs a strategy knowledge graph (arguments + counter-arguments)
4. Moot Court: LLM reasoning based on all inputs
5. Output: Strategy compilation document

**Data Sources**: Judicial Yuan Judgment Search System, National Laws and Regulations Database

---

### Recipe 2: Digitization of Church Hymns

```
media  ──► Sheet Music OCR (Paper → MusicXML/MIDI)
lore   ──► Music Metadata Archiving (Stroke Count, Key Signature, Time Signature)
muse   ──► Song Library Management (Index, Search)
media  ──► Audio Synthesis (Accompaniment + Vocals)
```

| Service | Capabilities to Expand |
|------|-------------|
| media | Sheet Music OCR → MusicXML/MIDI output |
| media | Audio synthesis (MIDI → accompaniment, melody+lyrics → vocals) |
| lore | Music metadata indexing (stroke count, key signature, time signature, original source) |
| muse | Sheet music library management, search/browse interface |

**Expected Workflow**:
1. Scan paper sheet music → media (Sheet Music OCR) → Digital format
2. Store in lore, with metadata attached
3. Browse/search via muse library
4. Generate accompaniment / synthesize vocals via media
5. Manual Review: Auto-generation → Manual editing → Publishing

---

### Recipe 3: Virtual Customer Service

```
media        ──► Product Catalog OCR (Physical → Structured Database)
nexus        ──► Requirement × Product Catalog → Ranking Suggestions
social-hooks ──► LINE Bot as Customer Frontend
quest        ──► Customer Inquiry → Auto-create Task Tracking
finance      ──► Quotation Generation (PDF/HTML)
```

| Service | Capabilities to Expand |
|------|-------------|
| media | Product Catalog OCR → Structured Database |
| nexus | Product Catalog × Requirement matching engine |
| quest | Customer Inquiry → Auto-create task tracking |
| finance | Quotation generation (PDF/HTML) |
| social-hooks | LINE Bot customer service dialogue flow |

---

### Recipe 4: ERP / POS

```
finance    ──► Inventory Management + POS Transaction Flow
quest      ──► Order Lifecycle (Quote → Accept → Deliver)
roster     ──► Machine/Equipment Resource Tracking
nexus      ──► Resource Allocation Optimization
```

| Service | Capabilities to Expand |
|------|-------------|
| finance | Inventory management, POS transaction flow, inventory tracking |
| quest | Order lifecycle (Quote → Accept → Deliver → Invoicing) |
| roster | Machine/equipment resource tracking, maintenance scheduling |
| nexus | Resource allocation optimization (Human + Machine) |

**Growth Path**: This is the natural convergence point where finance, quest, and roster each grow to Phase 4.

---

## Decision Process: What to do when a new requirement arrives?

```
New Requirement Arrives
    │
    ▼
Inventory: Which capabilities are needed?
    │
    ├──► Existing services cover it → Direct assembly, write composition recipe
    │
    ├──► Partial coverage → Expand existing service capabilities + Assembly
    │
    └──► Brand new domain → Evaluate if it's worth building a new service block
              │
              ├──► Worth it (will be reused by multiple recipes) → Build new service
              └──► Not worth it (one-time requirement) → Station or Script
```

## Relationship with Other Architecture Documents

| Document | Relationship |
|------|------|
| [principles.md](./principles.md) | Composition > Inheritance, KISS, YAGNI are the theoretical foundations of this model |
| [modular-monolith.md](./modular-monolith.md) | Technical implementation of service blocks |
| [event-driven.md](./event-driven.md) | Loose coupling between services via events — the glue of composition |
| [../vision/domain-catalog.md](../vision/domain-catalog.md) | Full catalog of all service blocks |
| [../blueprint/shared-layer-patterns.md](../blueprint/shared-layer-patterns.md) | Shared patterns within blocks (OOP patterns) |
