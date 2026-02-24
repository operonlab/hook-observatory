---
doc_version: 1
content_hash: pending
target_lang: en
source_hash: ef03fe55
source_lang: zh-TW
translated_at: 2026-02-24
---

# V2 Priority Development Blueprint

> Instead of a linear progression through Phases 1-4, development will be driven by **actual user pain points**, prioritizing the creation of the most valuable modules first.

---

## Priority Order

| Priority | Module | Objective | Why it's a priority |
|---|---|---|---|
| **P1** | lore (KAS Memory V2) | Persistent memory for Claude Code | Used daily; improving memory quality = improving the quality of all work. |
| **P2** | scout (Smart Search V2) | Structured storage for search reports + UI | Search is a high-frequency operation; scattered .md files have become a pain point. |

---

## P1: Lore Module — KAS Memory V2

### Current Situation Analysis

KAS Memory is currently a standalone project (`~/Claude/projects/kas-memory/`), using a file system architecture:

| Layer | Storage | Problem |
|---|---|---|
| Layer A | `MEMORY.md` (always-loaded, 200-line limit) | Limited space, requires careful selection |
| Layer B | `memories/YYYY-MM/*.md` + `tags.idx` | Plain text, concurrent write risks, no ACID |
| Layer C | `embeddings.json` (Ollama 768d) | Single JSON file, performance degrades as memory grows |

**MCP Server**: 9 tools (kas_recall, kas_extract, kas_promote, etc.), implemented in TypeScript
**SessionEnd Hook**: `extract-async.sh` → Gemini Flash + Haiku dual-LLM extraction → Galaxy reconstruction
**Galaxy Visualization**: `galaxy-data.json` → `galaxy-explorer.html` (K/A/S three-dimensional galaxy map)

### V2 Objectives

Refactor KAS Memory from a "file system tool" into a "Workshop Core module" while maintaining the MCP interface.

#### 1. Data Layer Migration: File → PostgreSQL + pgvector

```
Current: memories/*.md + tags.idx + embeddings.json
  ↓
Target: PostgreSQL (schema: lore)
  ├── lore_blocks       — memory blocks (replace .md files)
  ├── lore_tags         — tag index (replaces tags.idx)
  ├── lore_embeddings   — vector field (replaces embeddings.json, uses pgvector)
  ├── knowledge_domains — knowledge domains (replace knowledge/domains/*.md)
  └── kas_profiles      — KAS 4D Profile (replaces profile.json)
```

**Advantages**:
- ACID guarantees (solves concurrent write problems)
- Native vector search with pgvector (replaces custom JSON cosine similarity)
- Flexible SQL queries (time ranges, tag combinations, cross-table JOINs)
- Shares PostgreSQL infrastructure with other Workshop modules

#### 2. KS Galaxy (Knowledge-Skill Galaxy)

Automatically develop knowledge domains and skill graphs from extracted memories:

```
Session Dialogue
    │
    ▼
SessionEnd Hook Extraction
    │
    ├── Knowledge Fragments → Knowledge Domain Aggregation
    │     "Learned about pgvector's HNSW index" → accumulates into the Database knowledge domain
    │
    ├── Skill Validation → Skill Tree Growth
    │     "Successfully automated tests with playwright" → Browser Automation skill +1
    │
    └── Attitude Recording → Attitude Profile Evolution
          "Decided to adopt gradual refactoring instead of a complete rewrite" → Decision-making style updated
```

**Galaxy Visualization Upgrade**: Upgrade from static HTML to a Workbench Widget, reflecting the latest status in real-time.

#### 3. Multi-Agent Attitude System (Attitude Dimension)

The A (Attitude) in KAS is not just for recording the Master's decision-making style, but is the foundation for multi-agent collaboration:

```
┌──────────────────────────────────────────┐
│           Memory Core (Shared Memory Pool)         │
├──────────┬──────────┬────────────────────┤
│ Agent A  │ Agent B  │ Agent C            │
│ Optimist   │ Pessimist   │ Pragmatist              │
│ Explores new directions│ Questions risks  │ Weighs cost-benefit         │
└──────────┴──────────┴────────────────────┘
         │         │         │
         └─────────┼─────────┘
                   ▼
            Consensus Memory → Write back to Memory
```

- Each agent can have a different Attitude Profile (stance preference)
- After concurrent discussion among multiple agents, the conclusion is written back to the shared memory pool
- Attitude dimensions to track: risk_preference, decision_style, communication_style

#### 4. Recall Integration

The two "Recall" tools will coexist and complement each other:

| Tool | Purpose | Integration Method |
|---|---|---|
| `kas_recall` (MCP) | Structured memory search (tags + vector) | Auto-injected by UserPromptSubmit hook |
| `zippoxer/recall` (CLI TUI) | Full-text search of historical sessions | Manual query; recommended for use when kas_recall misses |

**Integration Flow**:
1. `kas_recall` searches structured memory first.
2. If the hit rate is low → Suggest: "No relevant content found in memory. You can use `recall` to search the original text of historical sessions."
3. From the original text found with `recall` → can manually trigger `kas_extract` to backfill it as structured memory.

### Technical Architecture

```
workbench/src/modules/lore/       ← Lore UI (Galaxy Widget, memory browser)
core/src/modules/lore/            ← Lore backend (API + DB + extraction engine)
mcp/lore/                         ← MCP Adapter (maintains existing 9 tool interfaces)
```

### Migration Strategy

1. **Phase A**: Create the lore schema + API in Core, import existing .md memories.
2. **Phase B**: Switch the MCP Server to be a thin adapter for the Core API (instead of reading files directly).
3. **Phase C**: Upgrade the SessionEnd Hook to write to the DB instead of .md files.
4. **Phase D**: Implement Workbench Widget (Galaxy + memory browser).

---

## P2: Scout Module — Smart Search V2

### Current Situation Analysis

Smart Search already has two components:

| Component | Location | Status |
|---|---|---|
| `smart-search` Skill | `~/.claude/skills/smart-search/` | Operational, v0.3.3 |
| `research_report` Service | `~/Claude/services/research_report/` | Operational, port 8830 |

**Existing Good Parts**:
- PostgreSQL + pgvector (schema `pulso_research`, 768d Ollama embedding)
- Complete REST API (CRUD + semantic search + topic graph + dashboard)
- Frontend Research Hub (port 3005)
- 52 .md fallback files pending backfill

**Excellent Designs from V1 Daily Briefing (Worth Keeping)**:
- Three AI analysts debating each other (Claude + Codex + Gemini)
- Five-domain classification (finance / ai / tech / geopolitics / weather)
- raw → analysis → debate three-stage pipeline
- Extreme stance detection +挖掘 overlooked perspectives

### V2 Objectives

Integrate scattered search/intelligence capabilities into the Workshop Core `scout` module.

#### 1. Data Layer Integration: Standalone Service → Core Module

```
Current:
  ~/Claude/services/research_report/  (Standalone FastAPI, port 8830)
  ~/Claude/skills/smart-search/*.md   (52 fallback files)
  ~/Claude/skills/daily-briefing/     (Static HTML)
  ↓
Target:
  core/src/modules/scout/             (Core Module)
  ├── schema: scout                   (PostgreSQL)
  │   ├── reports          — Search/research reports
  │   ├── report_embeddings — pgvector vectors (768d / 1536d)
  │   ├── topics           — Topic classification
  │   ├── topic_relations  — Topic relationship graph
  │   ├── briefings        — Daily intelligence summaries
  │   └── search_sessions  — Search history
  │
  └── API: /api/scout/
      ├── reports/         — CRUD + semantic search
      ├── topics/          — Topic management + relationship graph
      ├── briefings/       — Daily intelligence
      ├── search/          — Semantic search endpoint
      └── dashboard/       — Statistics + time-series graphs
```

#### 2. Smart Search Skill Integration

```
smart-search Skill (Claude Code)
    │
    ├── Pre-Search: POST /api/scout/search/check  ← Check for duplicates (pgvector similarity)
    │
    ├── Execute search (DeepWiki / Context7 / Perplexity / 9 platform communities)
    │
    └── Post-Search: POST /api/scout/reports      ← Write report + auto embedding
                                                     No longer falls back to .md
```

#### 3. UI Upgrade: Research Hub → Workbench Module

Retain the good designs of V1, rebuilding them as a Workbench module:

| Page | Function |
|---|---|
| `/scout` | Intelligence Overview (latest reports, trend charts, topic graph) |
| `/scout/reports` | Report List (full-text search + semantic search + tag filtering) |
| `/scout/reports/:id` | Report Details (Markdown rendering + source links) |
| `/scout/topics` | Topic Graph (Force-directed graph visualization) |
| `/scout/briefings` | Daily Briefings (three-analyst debate format) |
| Widget | Workbench homepage summary Widget (latest 5 + trends) |

#### 4. Daily Briefing Integration

Integrate V1's three-AI debate mode into the scout module:

```
Daily trigger (cron or manual)
    │
    ├── Data Collection: RSS + Communities + WebSearch
    │
    ├── Independent analysis by three analysts:
    │   ├── Claude  → analysis/claude.md
    │   ├── Codex   → analysis/codex.md
    │   └── Gemini  → analysis/gemini.md
    │
    ├── Cross-debate: debate/synthesis.md
    │
    └── Write to DB: POST /api/scout/briefings
        (including embeddings, allowing semantic search of historical briefings)
```

### Technical Architecture

```
workbench/src/modules/scout/      ← Scout UI (report browser, topic graph, intelligence overview)
core/src/modules/scout/           ← Scout backend (API + DB + pgvector + extraction)
mcp/scout/                        ← MCP Adapter (for direct manipulation by Claude Code)
```

### Migration Strategy

1. **Phase A**: Create the scout schema in Core, import data from the research_report DB + backfill the 52 .md files.
2. **Phase B**: Switch the smart-search Skill endpoint from `localhost:8830` → Core API.
3. **Phase C**: Implement the Workbench module (report browser + topic graph).
4. **Phase D**: Integrate Daily Briefing (three-analyst pipeline).

---

## P3: Station Integration — System Monitoring + LLM Usage + Environment Tools + Intelligence Topic Management

### Overview

Integrate scattered V1 tools into the Workshop `stations/` directory, and add dynamic topic management for Daily Briefing to the scout module.

### P3-A: System Monitor — Disk + Hardware Monitoring

**Current Situation**: V1 disk analysis works well (`~/.claude/data/disk-report/`, daily launchd schedule).

**V2 Changes**:
- Frequency adjustment: Daily → Weekly (Monday 05:00 UTC) + Monthly Report
- Add hardware resource monitoring: CPU / RAM / Swap / Temperature / Battery
- Stress level determination + alert notifications
- Workbench Widget (System Health Card)
- Core API endpoint (`/api/stations/system-monitor/`)

**Technical Architecture**:
```
stations/system-monitor/
├── collect.sh           ← Disk + hardware data collection
├── generate-report.sh   ← AI analysis report (dual-layer LLM routing)
└── config.json          ← Schedule, thresholds, notification settings
      ↓
workbench Widget ← Core API ← Report DB / real-time status
```

### P3-B: LLM Usage — Unified Token/Cost Tracking

**Current Situation**: LLM usage is scattered, model-policy only looks at CC ratio, LiteLLM has data but no UI.

**V2 Changes**:
- Sync LiteLLM DB → unified usage_records
- Multi-dimensional analysis: by Provider / Model / Caller / Time / Purpose
- Cache efficiency statistics
- Monthly budget tracking
- model-policy to read from the unified DB
- Workbench Widget (Cost Dashboard)

**Technical Architecture**:
```
Claude Code ─┐
Codex CLI   ─┼─► LiteLLM Proxy ─► collector.py ─► Unified DB
Gemini CLI  ─┘
                                         ↓
                    workbench Widget ← Core API
```

### P3-C: EnvKit — Environment Snapshot + One-Click Migration

**Current Situation**: `~/dotfiles/` has basic lists and scripts, but the Master feels V1 is "not what I want."

**V2 Redesign**:
- Categorized inventory (YAML, by AI tools / terminal / dev / services / apps)
- Config mapping table (location of each tool's config file + git tracking status)
- 8-stage Bootstrap Pipeline (installs in dependency order)
- `envkit snapshot` / `envkit verify` / `envkit diff` CLI tools
- Complements `~/dotfiles/` (dotfiles manage configs, envkit manages the whole environment picture)

### P3-D: Daily Briefing Topic Management (scout module extension)

**Current Situation**: V1's 6 briefing topics are completely hardcoded in the `run.sh` (a 530-line shell script).

**V2 Changes**:
- DB tables: `scout.briefing_topics` + `scout.briefing_subtopics`
- Dynamic CRUD: Add/modify/enable/disable topics + sub-categories
- Parameterized sub-categories: e.g., for weather, input regions of interest (Taipei, Tokyo, New York)
- Topic management UI: `/scout/briefings/settings` (tree structure, can check to enable/disable)
- Three-analyst pipeline retained: will now read dynamic topic settings
- V1 → V2 Migration: Automatically create the 6 default topics on first launch

### P3 Migration Strategy

```
P3-A (system-monitor): Copy V1 scripts → change frequency → add hardware monitoring → API + Widget
P3-B (llm-usage):      Parse LiteLLM DB → unify collection → API + Widget
P3-C (envkit):         Inventory ~/dotfiles/ → generate inventory.yaml → bootstrap pipeline
P3-D (briefing mgmt):  Create DB tables → migrate hardcoded topics → CRUD API → management UI
```

---

## Relationship with Existing Blueprints

| Existing Document | Action |
|---|---|
| `v2-blueprint.md` | Retain as a long-term vision reference, but the actual execution order will follow this document. |
| `v2-worktree-todos.md` | Retain, to be addressed after P1/P2 are complete. |
| `v1-feature-inventory.md` | Retain as a reference for V1 asset inventory. |

## Skill → Module Mapping Table

> Which of the existing Claude Code Skills will be incorporated into Workshop modules, serving as a planning reference for Phase 3+.

### scout — Search and Intelligence

P2 priority module. The research reports and analysis results produced by the following Skills should all be persisted to the scout DB:

| Skill | Current Output | Integration Method |
|---|---|---|
| **smart-search** | Search reports (.md) | Core of P2. Reports written to `scout.reports`, enabling pgvector semantic search |
| **daily-briefing** | Three-analyst briefings (HTML) | Incorporated in P2. Written to `scout.briefings`, retaining the debate format |
| **company-intel** | Company investigation reports | Report structure is identical, unified storage in `scout.reports` (tag: company-intel) |
| **competitive-intel** | Competitive analysis reports | Same as above (tag: competitive-intel) |
| **content-writer** | Articles with citations | Same as above (tag: content-article), source links stored in `sources` JSONB |

**Benefits of Integration**: All research outputs can be semantically searched across skills, avoiding situations like "not being able to find company-intel's output using smart-search."

### lore — Memory and Knowledge

P1 priority module. Outputs from the following Skills can serve as memory sources:

| Skill | Current Output | Integration Method |
|---|---|---|
| **kas-memory** (MCP) | Structured memory blocks | Core of P1. Migrate to `lore.blocks` + pgvector |
| **meeting-insights** | Communication pattern analysis | Analysis results written as lore blocks to track communication style evolution |

### dojo — Skills and Learning

Phase 2 module. Outputs from the following Skills can serve as data sources for dojo:

| Skill | Current Output | Integration Method |
|---|---|---|
| **skill-catalog** | 80+ skill inventory | → `dojo.skill_registry` (list of installed skills) |
| **skill-graph** | Skill synergy graph | → `dojo.skill_relations` (relationships between skills) |
| **skill-optimizer** | Optimization suggestions | → `dojo.optimization_logs` (tracking optimization history) |
| **model-mentor** | Model recommendations | → `dojo.tool_proficiency` (recording tool proficiency) |

**Vision**: Track "which skills the Master and Vane have honed together, and to what level," and visualize the growth trajectory in the Galaxy.

### roster — Resource Management

Phase 3 module. The following Skills correspond to agent/resource scheduling:

| Skill | Current Output | Integration Method |
|---|---|---|
| **maestro** | Three CLI dispatch records | → `roster.agent_sessions` (agent execution history) |
| **team-tasks** | Multi-agent coordination | → `roster.task_allocations` (task allocation records) |
| **scheduler** | Scheduled tasks | → `roster.schedules` (periodic task management) |

### nexus — Matching Engine

Phase 3 module. No direct corresponding Skill currently; will be newly created. Can integrate in the future:
- Quest task assignment → nexus scoring engine
- Dojo skill gaps → nexus learning resource recommendations

### media — Media Processing (`core/services/media/`)

Already planned as a hot-path service. The following Skills correspond to media processing capabilities:

| Skill | Function | Corresponding API |
|---|---|---|
| **tts** | Text-to-speech | `/api/media/tts` |
| **stt** | Speech-to-text | `/api/media/stt` |
| **video-core/edit/mix/audio** | Video/audio processing | `/api/media/video/*` |
| **image-gen/edit** | Image generation and editing | `/api/media/image/*` |
| **ocr**, **ocr-claude-api** | Text recognition | `/api/media/ocr` |

**Note**: media is a hot-path service (stateless processing), unlike domain modules (which have a DB).

### Skills Not to be Integrated into Modules

The following Skills will continue to operate independently and do not require an API/UI/MCP:

| Category | Skills | Reason |
|---|---|---|
| Development Flow | blueprint, executor, forge, spec-kit, tdd-enforcer | Development tools, do not produce persistent data |
| Code Quality | code-review-interceptor, verification-before-completion, four-step-debug | Real-time validation, no need for storage |
| Content Formatting | pdf, pptx, xlsx, docx, diagram-gen | File generation tools, output is already saved |
| CLI Dispatch | claude-code-headless, codex-cli-headless, gemini-cli-headless | Underlying dispatch mechanisms |
| Config Management | create-skill, create-agent, create-command, sync-config | Maintenance tools |

---

## Design Principles (Applicable throughout P1/P2)

1.  **Documentation First**: For each module, create a README.md + API spec before starting to code.
2.  **Complete Refactor, Not a Lift-and-Shift**: Do not just move V1 code to a new directory; redesign based on V2 architectural principles.
3.  **Retain Good Designs**: Preserve core concepts from V1 that have proven effective (e.g., the three-analyst debate, pgvector semantic search).
4.  **No Interruption to MCP Interface**: The backend refactor should not affect daily usage of Claude Code (MCP tool names and behaviors remain consistent).
5.  **Gradual Cutover**: Allow new and old systems to coexist during a transition period, gradually switching endpoints to ensure zero downtime.
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2488ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2508ms
