---
doc_version: 1
content_hash: pending
target_lang: en
source_hash: a5546c29
source_lang: zh-TW
translated_at: 2026-02-24
---

# V2 Priority Development Blueprint

> Instead of linear progression through Phases 1-4, development will be driven by **actual pain points**, prioritizing the creation of the most valuable modules first.

---

## Priority Order

| Priority | Module | Goal | Why It's a Priority |
|---|---|---|---|
| **P1** | lore (KAS Memory V2) | Persistent memory for Claude Code | Used daily; improving memory quality improves the quality of all work. |
| **P2** | scout (Smart Search V2) | Structured storage + UI for search reports | Searching is a high-frequency operation; scattered .md files have become a pain point. |

---

## P1: Lore Module — KAS Memory V2

### Current Situation Analysis

KAS Memory is currently a standalone project (`~/Claude/projects/kas-memory/`) using a file system architecture:

| Layer | Storage | Problems |
|---|---|---|
| Layer A | `MEMORY.md` (always-loaded, 200-line limit) | Limited space, requires careful curation. |
| Layer B | `memories/YYYY-MM/*.md` + `tags.idx` | Plain text, risk of concurrent write issues, no ACID. |
| Layer C | `embeddings.json` (Ollama 768d) | Single JSON file, performance degrades as memory grows. |

**MCP Server**: 9 tools (kas_recall, kas_extract, kas_promote, etc.), implemented in TypeScript.
**SessionEnd Hook**: `extract-async.sh` → Dual LLM extraction with Gemini Flash + Haiku → Galaxy rebuild.
**Galaxy Visualization**: `galaxy-data.json` → `galaxy-explorer.html` (K/A/S 3D star map).

### V2 Goals

Refactor KAS Memory from a "file system tool" into a "Workshop Core module" while maintaining the MCP interface.

#### 1. Data Layer Migration: File → PostgreSQL + pgvector

```
Current State: memories/*.md + tags.idx + embeddings.json
  ↓
Target State: PostgreSQL (schema: lore)
  ├── lore_blocks       — Memory blocks (replace .md files)
  ├── lore_tags         — Tag index (replace tags.idx)
  ├── lore_embeddings   — Vector column (replace embeddings.json, using pgvector)
  ├── knowledge_domains — Knowledge domains (replace knowledge/domains/*.md)
  └── kas_profiles      — KAS 4D Profile (replace profile.json)
```

**Advantages**:
- ACID guarantees (solves concurrent write problems).
- Native vector search with pgvector (replaces custom JSON cosine similarity).
- Flexible SQL queries (time ranges, tag combinations, cross-table JOINs).
- Shares PostgreSQL infrastructure with other Workshop modules.

#### 2. KS Galaxy (Knowledge-Skill Galaxy)

Automatically develop knowledge domains and a skill graph from extracted memories:

```
Session Dialogue
    │
    ▼
SessionEnd Hook Extraction
    │
    ├── Knowledge Fragments → Knowledge Domain Aggregation
    │     "Learned about HNSW indexes in pgvector" → Contributes to the Database knowledge domain
    │
    ├── Skill Validation → Skill Tree Growth
    │     "Successfully automated tests with Playwright" → Browser Automation skill +1
    │
    └── Attitude Recording → Attitude Profile Evolution
          "Decided to adopt progressive refactoring over a full rewrite" → Decision-making style updated
```

**Galaxy Visualization Upgrade**: Upgrade from a static HTML file to a Workbench Widget that reflects the latest state in real-time.

#### 3. Multi-Agent Attitude System (Attitude Dimension)

The A (Attitude) in KAS is not just for recording the user's decision-making style, but also a foundation for multi-agent collaboration:

```
┌──────────────────────────────────────────┐
│           Memory Core (Shared Memory Pool) │
├──────────┬──────────┬────────────────────┤
│ Agent A  │ Agent B  │ Agent C            │
│ Optimist │ Pessimist│ Pragmatist         │
│ Explores new directions │ Questions risks │ Weighs costs and benefits │
└──────────┴──────────┴────────────────────┘
         │         │         │
         └─────────┼─────────┘
                   ▼
            Consensus Memory → Written back to Memory
```

- Each agent can have a different Attitude Profile (stance preference).
- After concurrent discussion among multiple agents, the conclusion is written back to the shared memory pool.
- Attitude dimensions to track: risk_preference, decision_style, communication_style.

#### 4. Recall Integration

Two "Recall" tools will coexist and complement each other:

| Tool | Purpose | Integration Method |
|---|---|---|
| `kas_recall` (MCP) | Structured memory search (tags + vector) | Automatically injected via UserPromptSubmit hook. |
| `zippoxer/recall` (CLI TUI) | Full-text search of historical session transcripts | Manual query; recommended when `kas_recall` misses. |

**Integration Flow**:
1. `kas_recall` first searches structured memory.
2. If the hit rate is low → suggest: "No relevant content found in memory. You can use `recall` to search historical session transcripts."
3. From the original text found with `recall` → can manually trigger `kas_extract` to backfill it as structured memory.

### Technical Architecture

```
workbench/src/modules/lore/       ← Lore UI (Galaxy Widget, memory browser)
core/src/modules/lore/            ← Lore backend (API + DB + extraction engine)
mcp/lore/                         ← MCP Adapter (maintains existing 9 tool interfaces)
```

### Migration Strategy

1. **Phase A**: Create the `lore` schema + API in Core, import existing .md memories.
2. **Phase B**: Switch the MCP Server to be a thin adapter for the Core API (instead of reading files directly).
3. **Phase C**: Upgrade the SessionEnd Hook to write to the DB instead of .md files.
4. **Phase D**: Develop the Workbench Widget (Galaxy + memory browser).

---

## P2: Scout Module — Smart Search V2

### Current Situation Analysis

Smart Search already has two components:

| Component | Location | Status |
|---|---|---|
| `smart-search` Skill | `~/.claude/skills/smart-search/` | Operational, v0.3.3 |
| `research_report` Service | `~/Claude/services/research_report/` | Operational, port 8830 |

**Existing Good Things**:
- PostgreSQL + pgvector (schema `pulso_research`, 768d Ollama embedding).
- Complete REST API (CRUD + semantic search + topic graph + dashboard).
- Frontend Research Hub (port 3005).
- 52 .md fallback files waiting to be backfilled.

**Excellent Design of V1 Daily Briefing** (worth preserving):
- Three AI analysts debating each other (Claude + Codex + Gemini).
- Five-domain classification (finance / ai / tech / geopolitics / weather).
- Three-layer pipeline: raw → analysis → debate.
- Extreme stance detection +挖掘 ignored perspectives.

### V2 Goals

Integrate the scattered search/intelligence capabilities into a Workshop Core `scout` module.

#### 1. Data Layer Integration: Standalone Service → Core Module

```
Current State:
  ~/Claude/services/research_report/  (Standalone FastAPI, port 8830)
  ~/Claude/skills/smart-search/*.md   (52 fallback files)
  ~/Claude/skills/daily-briefing/     (Static HTML)
  ↓
Target State:
  core/src/modules/scout/             (Core Module)
  ├── schema: scout                   (PostgreSQL)
  │   ├── reports          — Search/research reports
  │   ├── report_embeddings — pgvector vectors (768d / 1536d)
  │   ├── topics           — Topic classification
  │   ├── topic_relations  — Topic relation graph
  │   ├── briefings        — Daily intelligence summaries
  │   └── search_sessions  — Search history
  │
  └── API: /api/scout/
      ├── reports/         — CRUD + semantic search
      ├── topics/          — Topic management + relation graph
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
    ├── Execute Search (DeepWiki / Context7 / Perplexity / 9 platform communities)
    │
    └── Post-Search: POST /api/scout/reports      ← Write report + auto-embedding
                                                     No longer falls back to .md
```

#### 3. UI Upgrade: Research Hub → Workbench Module

Rebuild using the good designs from V1 as a Workbench module:

| Page | Function |
|---|---|
| `/scout` | Intelligence Dashboard (latest reports, trend charts, topic graph) |
| `/scout/reports` | Report List (full-text search + semantic search + tag filtering) |
| `/scout/reports/:id` | Report Details (Markdown rendering + source links) |
| `/scout/topics` | Topic Graph (Force-directed graph visualization) |
| `/scout/briefings` | Daily Briefing (three-analyst debate format) |
| Widget | Workbench homepage summary Widget (latest 5 reports + trends) |

#### 4. Daily Briefing Integration

Integrate the V1 three-AI debate model into the `scout` module:

```
Daily Trigger (cron or manual)
    │
    ├── Data Collection: RSS + Communities + WebSearch
    │
    ├── Three Analysts Independent Analysis:
    │   ├── Claude  → analysis/claude.md
    │   ├── Codex   → analysis/codex.md
    │   └── Gemini  → analysis/gemini.md
    │
    ├── Cross-Debate: debate/synthesis.md
    │
    └── Write to DB: POST /api/scout/briefings
        (includes embedding, allows semantic search of historical briefings)
```

### Technical Architecture

```
workbench/src/modules/scout/      ← Scout UI (report browser, topic graph, intelligence dashboard)
core/src/modules/scout/           ← Scout backend (API + DB + pgvector + extraction)
mcp/scout/                        ← MCP Adapter (for direct operation by Claude Code)
```

### Migration Strategy

1. **Phase A**: Create the `scout` schema in Core, import data from the `research_report` DB + backfill the 52 .md files.
2. **Phase B**: Switch the `smart-search` Skill endpoint from `localhost:8830` → Core API.
3. **Phase C**: Develop the Workbench module (report browser + topic graph).
4. **Phase D**: Integrate Daily Briefing (three-analyst pipeline).

---

## P3: Station Integration — System Monitoring + LLM Usage + Env Tools + Intelligence Topic Management

### Overview

Integrate scattered V1 tools into the Workshop `stations/` directory and add dynamic Daily Briefing topic management for the scout module.

### P3-A: System Monitor — Disk + Hardware Monitoring

**Current Situation**: V1 disk analysis works well (`~/.claude/data/disk-report/`, daily launchd schedule).

**V2 Changes**:
- Frequency Adjustment: Daily → Weekly (Monday 05:00 UTC) + Monthly report
- Add Hardware Resource Monitoring: CPU / RAM / Swap / Temperature / Battery
- Stress Level Assessment + Alert Notifications
- Workbench Widget (System Health Card)
- Core API Endpoint (`/api/stations/system-monitor/`)

**Technical Architecture**:
```
stations/system-monitor/
├── collect.sh           ← Disk + hardware data collection
├── generate-report.sh   ← AI analysis report (dual-layer LLM routing)
└── config.json          ← Schedule, thresholds, notification settings
      ↓
workbench Widget ← Core API ← Report DB / real-time status
```

### P3-B: LLM Usage — Dual-Track Usage Tracking

**Current Situation**: LLM usage is split between two worlds — the usage ratio of subscription-based CLI tools (CC/Codex/Gemini) + separately purchased API services (LiteLLM). It's impossible to give a unified answer to "How much was spent this month in total?"

**V2 Changes**:
- **Subscription Tracking**: Monthly fees of each CLI tool + usage quota consumption ratio
- **API Tracking**: Sync with LiteLLM DB → token count + actual cost (for Agent SDK scenarios, etc.)
- Dual-Track Analysis: Subscription (fixed monthly fee + quota) vs. API (pay-per-use)
- API Budget Tracking + Cache Efficiency Statistics
- `model-policy` to read from a unified DB
- Workbench Widget (dual-track cost dashboard)

**Technical Architecture**:
```
── Subscription ────────────────────────
CC / Codex / Gemini CLI → hooks + logs → subscription.py → DB

── API (Pay-per-use) ───────────────────
Agent SDK / custom services → LiteLLM Proxy → api_collector.py → DB

                                    ↓
                 workbench Widget ← Core API
```

### P3-C: EnvKit — Complete Environment Management (replaces ~/dotfiles/)

**Current Situation**: `~/dotfiles/` has an installation list but lacks categorization, config backups, and a restoration order. The user said, "This is not what I want."

**V2 Redesign (replaces dotfiles, not complementary)**:
- 5-Tier Environment Inventory: Tier 1 Core settings (tmux/zsh/CC) → Tier 2 Important tools → Tier 3 CLI → Tier 4 Services → Tier 5 GUI
- Config Backup: Four strategies - file copy, export/restore, git tracking, cloud sync
- 9-Stage Bootstrap Pipeline (install + restore configs in dependency order)
- `envkit snapshot/backup/bootstrap/verify/diff` CLI
- Archive `~/dotfiles/` after stabilization

### P3-D: Daily Briefing Topic Management (scout module extension)

**Current Situation**: V1's 6 intelligence topics are completely hardcoded in `run.sh` (a 530-line shell script).

**V2 Changes**:
- DB Tables: `scout.briefing_topics` + `scout.briefing_subtopics`
- Dynamic CRUD: Can add/modify/enable/disable topics + sub-categories
- Sub-category Parameterization: e.g., for weather → input regions of interest (Taipei, Tokyo, New York)
- Topic Management UI: `/scout/briefings/settings` (tree structure, can check to enable/disable)
- Three-Analyst Pipeline Preserved: Will read dynamic topic settings instead
- V1 → V2 Migration: Automatically create the 6 default topics on first launch

### P3 Migration Strategy

```
P3-A (system-monitor): Copy V1 script → change frequency → add hardware monitoring → API + Widget
P3-B (llm-usage):      Organize subscription plans + parse LiteLLM DB → dual-track collection → API + Widget
P3-C (envkit):         Scan Mac Mini → inventory.yaml + config backup → bootstrap pipeline → archive ~/dotfiles/
P3-D (briefing management): Create DB tables → migrate hardcoded topics → CRUD API → management UI
```

---

## Relationship with Existing Blueprints

| Existing Document | Action |
|---|---|
| `v2-blueprint.md` | Keep as a long-term vision reference, but the actual execution order will follow this document. |
| `v2-worktree-todos.md` | Keep, will revisit after P1/P2 are completed. |
| `v1-feature-inventory.md` | Keep as a reference for V1 asset inventory. |

## Skill → Module Mapping Table

> Which existing Claude Code Skills will be incorporated into Workshop modules, as a reference for Phase 3+ planning.

### scout — Search & Intelligence

P2 priority module. Research reports and analysis results from the following Skills should all be persisted to the `scout` DB:

| Skill | Current Output | Integration Method |
|---|---|---|
| **smart-search** | Search reports (.md) | P2 core. Reports written to `scout.reports`, enabling pgvector semantic search. |
| **daily-briefing** | Three-analyst intelligence (HTML) | Incorporated in P2. Written to `scout.briefings`, preserving debate format. |
| **company-intel** | Company investigation reports | Report structure is the same, unified storage in `scout.reports` (tag: company-intel). |
| **competitive-intel** | Competitor analysis reports | Same as above (tag: competitive-intel). |
| **content-writer** | Articles with citations | Same as above (tag: content-article), source links stored in `sources` JSONB. |

**Consolidation Benefit**: All research outputs can be semantically searched across skills, avoiding situations like "can't find `company-intel` output with `smart-search`".

### lore — Memory & Knowledge

P1 priority module. Outputs from the following Skills can serve as memory sources:

| Skill | Current Output | Integration Method |
|---|---|---|
| **kas-memory** (MCP) | Structured memory blocks | P1 core. Migrate to `lore.blocks` + pgvector. |
| **meeting-insights**| Communication pattern analysis | Analysis results written as lore blocks to track communication style evolution. |

### dojo — Skills & Learning

Phase 2 module. Outputs from the following Skills can serve as data sources for `dojo`:

| Skill | Current Output | Integration Method |
|---|---|---|
| **skill-catalog** | List of 80+ skills | → `dojo.skill_registry` (list of installed skills). |
| **skill-graph** | Skill synergy graph | → `dojo.skill_relations` (relationships between skills). |
| **skill-optimizer** | Optimization suggestions | → `dojo.optimization_logs` (tracking of optimization history). |
| **model-mentor** | Model recommendations | → `dojo.tool_proficiency` (record of tool proficiency). |

**Vision**: Track "which skills the user and I have honed together, and to what level," and observe the growth trajectory through the Galaxy visualization.

### roster — Resource Management

Phase 3 module. The following Skills correspond to agent/resource dispatching:

| Skill | Current Output | Integration Method |
|---|---|---|
| **maestro** | Three-CLI dispatch records | → `roster.agent_sessions` (agent execution history). |
| **team-tasks** | Multi-agent coordination | → `roster.task_allocations` (task allocation records). |
| **scheduler** | Scheduled tasks | → `roster.schedules` (periodic task management). |

### nexus — Matchmaking Engine

Phase 3 module. No direct corresponding Skill currently; will be newly created. Can integrate in the future:
- Quest task assignment → nexus scoring engine
- `dojo` skill gaps → nexus learning resource recommendations

### media — Media Processing (`core/services/media/`)

Already planned as a hot-path service. The following Skills correspond to media processing capabilities:

| Skill | Function | Corresponding API |
|---|---|---|
| **tts** | Text-to-Speech | `/api/media/tts` |
| **stt** | Speech-to-Text | `/api/media/stt` |
| **video-core/edit/mix/audio** | Video/Audio Processing | `/api/media/video/*` |
| **image-gen/edit** | Image Generation & Editing | `/api/media/image/*` |
| **ocr**, **ocr-claude-api** | Text Recognition | `/api/media/ocr` |

**Note**: `media` is a hot-path service (stateless processing), different from domain modules (which have a DB).

### Skills Not to Be Integrated into Modules

The following Skills will remain standalone and do not require an API/UI/MCP:

| Category | Skills | Reason |
|---|---|---|
| Dev Workflow | blueprint, executor, forge, spec-kit, tdd-enforcer | Development tools, do not produce persistent data. |
| Code Quality | code-review-interceptor, verification-before-completion, four-step-debug | Real-time validation, no storage needed. |
| Content Format | pdf, pptx, xlsx, docx, diagram-gen | File generation tools, output is already saved as files. |
| CLI Dispatch | claude-code-headless, codex-cli-headless, gemini-cli-headless | Underlying dispatch mechanisms. |
| Config Management | create-skill, create-agent, create-command, sync-config | Maintenance tools. |

---

## Design Principles (Applicable to P1/P2)

1. **Documentation First**: Each module starts with a `README.md` + API spec before any code is written.
2. **Complete Refactor, Not Just Moving Files**: This is not about moving V1 code to a new directory, but about redesigning based on V2 architecture principles.
3. **Preserve Good Designs**: Concepts validated in V1 (like the three-analyst debate, pgvector semantic search) should have their core ideas preserved.
4. **No Interruption to MCP Interface**: Backend refactoring should not affect the daily use of Claude Code (MCP tool names and behaviors remain consistent).
5. **Progressive Cutover**: Allow new and old systems to coexist during a transition period, gradually switching endpoints to ensure zero downtime.
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2467ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2373ms
