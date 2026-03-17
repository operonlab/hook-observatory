---
source_hash: ef012c6a
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Intelflow Module (Backend)

> Smart Search V2 + Daily Briefing — A structured storage and intelligence management engine for search reports.

## Positioning

The `intelflow` module of Workshop Core integrates three existing systems:
1.  **research_report service** (V1: `~/Claude/services/research_report/`, migrated) — Report CRUD + Qdrant
2.  **smart-search skill** (`~/.claude/skills/smart-search/`) — Multi-source search engine
3.  **daily-briefing skill** (`~/.claude/skills/daily-briefing/`) — Three-AI-analyst debate

## Core Capabilities

| Capability | Description |
|---|---|
| **Report Management** | CRUD + Semantic Search (Qdrant hybrid search) |
| **Deduplication** | Before a new search, query for existing similar reports to avoid duplication |
| **Topic Graph** | Automatically extract topics + build a relation graph (force-directed graph) |
| **Daily Briefing** | Independent analysis by three AI analysts + cross-debate |
| **NL Q&A** | Natural language question answering (DB-first, vector search assisted) |

## DB Schema (`intelflow` schema)

```sql
-- Search/Research Reports
CREATE TABLE intelflow.reports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    query       TEXT NOT NULL,            -- Original search query
    content     TEXT NOT NULL,            -- Full report content in Markdown format
    sources     JSONB DEFAULT '[]',       -- Source URLs + titles
    tags        TEXT[] DEFAULT '{}',
    skill_name  TEXT,                     -- The skill that generated this report (e.g., smart-search)
    embedding   vector(768),              -- legacy storage, search via Qdrant
    space_id    UUID NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Topics
CREATE TABLE intelflow.topics (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT UNIQUE NOT NULL,
    display_name TEXT,
    report_count INT DEFAULT 0,
    embedding    vector(768),
    space_id     UUID NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- Reports ↔ Topics (many-to-many)
CREATE TABLE intelflow.report_topics (
    report_id UUID REFERENCES intelflow.reports(id) ON DELETE CASCADE,
    topic_id  UUID REFERENCES intelflow.topics(id) ON DELETE CASCADE,
    relevance FLOAT DEFAULT 1.0,
    PRIMARY KEY (report_id, topic_id)
);

-- Topic Relations
CREATE TABLE intelflow.topic_relations (
    source_topic_id UUID REFERENCES intelflow.topics(id),
    target_topic_id UUID REFERENCES intelflow.topics(id),
    weight          FLOAT DEFAULT 1.0,
    PRIMARY KEY (source_topic_id, target_topic_id)
);

-- Briefing Topics (dynamically managed, replaces the 6 hardcoded domains in V1)
CREATE TABLE intelflow.briefing_topics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,              -- Internal identifier name (finance, ai, weather...)
    display_name  TEXT NOT NULL,              -- Display name (Financial Markets, AI Trends, Weather...)
    description   TEXT,                       -- Topic description
    enabled       BOOLEAN DEFAULT true,
    priority      INT DEFAULT 0,             -- Priority (higher number means higher priority)
    prompt_template TEXT,                     -- Analyst prompt template (customizable)
    sources       JSONB DEFAULT '[]',        -- Preferred data sources (RSS URLs, search keywords, etc.)
    schedule      TEXT DEFAULT 'daily',      -- daily / weekday / weekly
    space_id      UUID NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Briefing Subtopics (e.g., "Taipei, Tokyo, New York" under "Weather")
CREATE TABLE intelflow.briefing_subtopics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id      UUID REFERENCES intelflow.briefing_topics(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,              -- Subtopic name
    parameters    JSONB DEFAULT '{}',        -- Subtopic parameters (e.g., region: "Taipei", lat/lon, etc.)
    enabled       BOOLEAN DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Daily Briefings (now linked to briefing_topics)
CREATE TABLE intelflow.briefings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date        DATE NOT NULL,
    topic_id    UUID REFERENCES intelflow.briefing_topics(id), -- Link to dynamic topic (replaces hardcoded domain)
    domain      TEXT NOT NULL,            -- Backward compatibility field (= briefing_topics.name)
    raw_data    JSONB,                    -- Raw data summary
    analyses    JSONB,                    -- {claude: ..., codex: ..., gemini: ...}
    debate      TEXT,                     -- Cross-debate conclusion
    embedding   vector(768),
    space_id    UUID NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (date, topic_id)              -- One entry per topic per day
);

-- Search Sessions
CREATE TABLE intelflow.search_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query       TEXT NOT NULL,
    source      TEXT,                     -- smart-search / manual / api
    result_type TEXT,                     -- found_existing / new_report
    report_id   UUID REFERENCES intelflow.reports(id),
    space_id    UUID NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX idx_reports_embedding ON intelflow.reports USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_reports_tags ON intelflow.reports USING GIN (tags);
CREATE INDEX idx_reports_created ON intelflow.reports (created_at DESC);
CREATE INDEX idx_topics_embedding ON intelflow.topics USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_briefings_date ON intelflow.briefings (date DESC);
CREATE INDEX idx_briefings_topic ON intelflow.briefings (topic_id);
CREATE INDEX idx_subtopics_topic ON intelflow.briefing_subtopics (topic_id);
```

## API Endpoints (`/api/intelflow/`)

### Reports

| Method | Path | Description |
|---|---|---|
| GET | `/reports` | List (filter by topic, filter by tag, pagination) |
| GET | `/reports/:id` | Single report full content |
| POST | `/reports` | Create report (write endpoint for smart-search Skill) |
| PUT | `/reports/:id` | Update report |
| DELETE | `/reports/:id` | Delete report |

### Search

| Method | Path | Description |
|---|---|---|
| POST | `/search` | Semantic search (query + limit + threshold) |
| POST | `/search/check` | Deduplication check (returns exists + matches) |
| POST | `/ask` | NL Q&A (DB-first, vector-assisted) |

### Topics

| Method | Path | Description |
|---|---|---|
| GET | `/topics` | List topics |
| POST | `/topics` | Create topic |
| GET | `/topics/:id/related` | Related topics |
| GET | `/topics/graph` | Topic relation graph (nodes + edges) |

### Briefing Topic Management

| Method | Path | Description |
|---|---|---|
| GET | `/briefings/topics` | List topics (with enabled status, subtopic count) |
| POST | `/briefings/topics` | Add a new topic (name, description, schedule frequency) |
| PUT | `/briefings/topics/:id` | Update topic (can rename, enable/disable, adjust prompt) |
| DELETE | `/briefings/topics/:id` | Delete topic (also deletes subtopics) |
| PATCH | `/briefings/topics/:id/toggle` | Quickly enable/disable a topic |
| POST | `/briefings/topics/:id/subtopics` | Add a subtopic (e.g., Weather → Taipei) |
| PUT | `/briefings/topics/:id/subtopics/:sid` | Update subtopic |
| DELETE | `/briefings/topics/:id/subtopics/:sid` | Delete subtopic |

### Briefings

| Method | Path | Description |
|---|---|---|
| GET | `/briefings` | List briefings (date range, topic filter) |
| GET | `/briefings/:date` | Briefings for a specific date (all topics) |
| GET | `/briefings/:date/:topic` | Briefing for a specific date and topic |
| POST | `/briefings` | Create/trigger briefing generation (can specify topic) |
| POST | `/briefings/run` | Trigger the complete briefing process (all enabled topics) |

### Statistics

| Method | Path | Description |
|---|---|---|
| GET | `/dashboard` | Statistics summary (report count, topic count, trends) |
| GET | `/dashboard/timeline` | Data for timeline chart |

## Directory Structure (Plan)

```
core/src/modules/intelflow/
├── README.md             ← This document
├── __init__.py
├── routes.py             ← API routes
├── schemas.py            ← Pydantic models
├── models.py             ← SQLAlchemy models
├── service.py            ← Business logic (CRUD + search)
├── search.py             ← Qdrant hybrid search engine
├── topic_extractor.py    ← Automatic topic extraction + relation graph
├── briefing_pipeline.py  ← Three-analyst debate pipeline
└── events.py             ← Event definitions (intelflow.report.created, etc.)
```

## Daily Briefing Topic Management (New in V2)

### Problem

The 6 briefing topics in V1 were completely hardcoded in `run.sh` (line 530). Adding or modifying topics required changing the shell script.

```
V1 (hardcoded): finance | ai | tech | geopolitics | weather | devtools
  ↓
V2 (dynamic): Users can manage topics + subtopics themselves via the UI
```

### Topic Structure

Each topic can have multiple subtopics, which carry specific parameters:

```yaml
- name: weather
  display_name: "Weather"
  schedule: daily
  subtopics:
    - name: "Taipei"
      parameters: { region: "Taipei", lat: 25.03, lon: 121.56 }
    - name: "Tokyo"
      parameters: { region: "Tokyo", lat: 35.68, lon: 139.69 }
    - name: "New York"
      parameters: { region: "New York", lat: 40.71, lon: -74.00 }

- name: finance
  display_name: "Financial Markets"
  schedule: weekday
  subtopics:
    - name: "US Stocks"
      parameters: { market: "US", indices: ["SPX", "NDX", "DJI"] }
    - name: "TW Stocks"
      parameters: { market: "TW", indices: ["TAIEX"] }
    - name: "Cryptocurrency"
      parameters: { assets: ["BTC", "ETH", "SOL"] }

- name: ai
  display_name: "AI Trends"
  schedule: daily
  subtopics:
    - name: "Model Releases"
      parameters: { sources: ["arxiv", "huggingface"] }
    - name: "Product Updates"
      parameters: { companies: ["Anthropic", "OpenAI", "Google", "Meta"] }
    - name: "Open Source Tools"
      parameters: { sources: ["github-trending"] }
```

### UI Pages

| Page | Path | Function |
|---|---|---|
| Topic Management | `/intelflow/briefings/settings` | CRUD topics + subtopics, schedule settings |
| Briefing Browser | `/intelflow/briefings` | View briefings by date for each topic |
| Briefing Details | `/intelflow/briefings/:date/:topic` | Three-analyst analysis + debate |

**Topic Management UI Concept**:

```
┌─── Briefing Topic Management ───────────────────────┐
│                                                      │
│  [+ New Topic]                                       │
│                                                      │
│  ☑ Financial Markets      weekday       3 subtopics  │
│    ├── ☑ US Stocks                                   │
│    ├── ☑ TW Stocks                                   │
│    └── ☑ Cryptocurrency                              │
│    [+ New Subtopic]                                  │
│                                                      │
│  ☑ AI Trends              daily         3 subtopics  │
│    ├── ☑ Model Releases                              │
│    ├── ☑ Product Updates                             │
│    └── ☑ Open Source Tools                           │
│    [+ New Subtopic]                                  │
│                                                      │
│  ☑ Weather                daily         3 subtopics  │
│    ├── ☑ Taipei                                      │
│    ├── ☑ Tokyo                                       │
│    └── ☑ New York                                    │
│    [+ New Subtopic]                                  │
│                                                      │
│  ☐ Geopolitics            weekly        0 subtopics  │
│    (Disabled)                                        │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Three-Analyst Pipeline (Preserving V1 Design)

The three-analyst debate model from V1 is fully preserved but now reads from the dynamic topic settings:

```
Daily Trigger (cron or API)
    │
    ├── Read briefing_topics (enabled=true)
    │
    ├── For each topic + subtopic:
    │   ├── Data Collection (RSS + WebSearch + topic.sources)
    │   │
    │   ├── Independent Analysis by Three Analysts:
    │   │   ├── Claude Haiku  → Analysis A
    │   │   ├── Codex         → Analysis B
    │   │   └── Gemini Flash  → Analysis C
    │   │
    │   ├── Cross-Debate: Determine extreme positions + identify overlooked angles
    │   │
    │   └── Write to intelflow.briefings
    │
    └── Send Notification (optional)
```

### V1 Default Topic Migration

On first launch, the 6 topics from V1 will be automatically created as defaults:

| V1 domain | V2 topic | Default subtopics |
|---|---|---|
| finance | Financial Markets | US Stocks, TW Stocks, Cryptocurrency |
| ai | AI Trends | Model Releases, Product Updates, Open Source Tools |
| tech | Tech Industry | Software, Hardware, Cloud |
| geopolitics | Geopolitics | US-China, Taiwan Strait, Europe |
| weather | Weather | Taipei |
| devtools | Dev Tools | CLI, IDE, Frameworks |

## Migration Plan

1.  Create schema + models → Import existing `workshop_research` DB data
2.  Backfill 52 `.md` fallback files into the DB
3.  Implement Core API (replicating research_report endpoints)
4.  Switch smart-search Skill endpoint from `localhost:8830` → Core API
5.  Integrate daily-briefing three-analyst pipeline
6.  Decommission V1 `~/Claude/services/research_report/`

## Dependent Modules

-   **auth** — `space_id` isolation
-   **memvault** — Search reports can trigger memory creation (cross-module event)
-   **mcp/intelflow** — MCP tool integration

## Skill Integration

In addition to smart-search and daily-briefing, the outputs of the following Skills will also be stored in the intelflow DB:

| Skill | Integration Method |
|---|---|
| **company-intel** | Report stored in `intelflow.reports` (tag: company-intel) |
| **competitive-intel** | Report stored in `intelflow.reports` (tag: competitive-intel) |
| **content-writer** | Article stored in `intelflow.reports` (tag: content-article), source links stored in `sources` JSONB |

Once all research outputs are unified in the database, they can be semantically searched across skills, preventing information silos.

## References

-   V1 research_report (migrated): `~/Claude/services/research_report/`
-   Existing smart-search skill: `~/.claude/skills/smart-search/SKILL.md`
-   Existing daily-briefing skill: `~/.claude/skills/daily-briefing/`
-   Existing company-intel skill: `~/.claude/skills/company-intel/SKILL.md`
-   Existing competitive-intel skill: `~/.claude/skills/competitive-intel/SKILL.md`
-   Existing content-writer skill: `~/.claude/skills/content-writer/SKILL.md`
-   V1 Frontend Research Hub: port 3005
