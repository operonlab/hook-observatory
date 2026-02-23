---
doc_version: 4
content_hash: 7d49d210
source_version: 4
translated_at: 2026-02-23
---

# Documentation Management

## Hybrid Model: Centralized + Distributed

### Centralized (`docs/`)

Cross-domain, system-level documentation that applies to the whole platform.

```
docs/
├── architecture/        # System design decisions
│   ├── modular-monolith.md      # Backend architecture guide
│   ├── frontend.md              # Frontend architecture guide
│   ├── event-driven.md          # Event-driven architecture
│   ├── plugin-system.md         # Hook/Plugin system
│   ├── observability.md         # Observability strategy
│   ├── auth.md                  # Auth & permissions
│   ├── communication.md         # Communication patterns
│   ├── folder-structure.md      # Layout and naming rules
│   ├── tech-stack.md            # Technology choices
│   ├── rwd-pwa.md               # RWD + PWA standards
│   ├── docs-management.md       # This file
│   ├── feature-lifecycle.md     # POC → production workflow
│   └── adr/                     # Architecture Decision Records
│       └── 001-template.md
├── api/                 # API design standards
│   ├── conventions.md         # Naming, versioning, error format
│   └── openapi/               # OpenAPI specs
├── runbooks/            # Operational procedures
│   ├── deploy.md
│   ├── rollback.md
│   └── incident-response.md
└── guides/              # Developer guides
    ├── getting-started.md     # New developer onboarding
    ├── add-new-module.md      # How to add a new domain module
    └── create-plugin.md       # How to create a plugin
```

### Distributed (per domain)

Domain-specific documentation lives **inside** each module/service as `README.md`.

```
core/README.md                           ← How to run, env vars, module overview
core/src/modules/finance/                ← Module-level docs in code comments
core/services/realtime/README.md         ← Realtime service setup
workbench/README.md                      ← Frontend development guide
```

## What Goes Where?

| Content | Location | Example |
|---------|----------|---------|
| Architecture decisions | `docs/architecture/` | "Why Modular Monolith over microservices" |
| API design standards | `docs/api/` | "All endpoints use camelCase" |
| Deployment procedures | `docs/runbooks/` | "How to deploy core service" |
| Onboarding guide | `docs/guides/` | "Set up dev environment" |
| Module-specific setup | `core/README.md` | "Core needs CORE_DB_URL env var" |
| Plugin development | `docs/guides/create-plugin.md` | "How to build a plugin" |
| Shared lib usage | `libs/<lang>/README.md` | "Import corelib.db for connections" |

## ADR (Architecture Decision Records)

For significant technical decisions, create an ADR in `docs/architecture/adr/`:

```markdown
# ADR-NNN: <Title>

## Status
Accepted | Proposed | Deprecated

## Context
What situation prompted this decision?

## Decision
What did we decide?

## Consequences
What are the trade-offs?
```

## Translation Workflow (zh-TW → en)

### Structure

Traditional Chinese documentation is the **source of truth** (`docs/`). English translations are automatically generated to `docs-en/`, mirroring the `docs/` structure:

```
docs/architecture/modular-monolith.md     →  docs-en/architecture/modular-monolith.md
docs/vision/roadmap.md                    →  docs-en/vision/roadmap.md
CLAUDE.md                                 →  docs-en/CLAUDE.md
```

### Version Tracking

Every `.md` file has YAML frontmatter with version tracking:

```yaml
---
doc_version: 3
content_hash: a1b2c3d4
---
```

- `content_hash`: SHA-256 of file body (first 8 hex chars). Changes when content changes.
- `doc_version`: Auto-increments when `content_hash` changes. Used to detect translation staleness.

### Translation Script

```bash
# Translate all changed docs to English (via Gemini CLI)
python3 scripts/translate-docs.py

# Check which docs need translation updates
python3 scripts/translate-docs.py --status

# Dry run (show what would be translated)
python3 scripts/translate-docs.py --dry-run

# Update version numbers only (no translation)
python3 scripts/translate-docs.py --version-only

# Force re-translate all docs
python3 scripts/translate-docs.py --force
```

### Rules

1. **Never edit docs-en/ files directly** — they are auto-generated from Chinese sources
2. **Run translation after doc changes** — `python3 scripts/translate-docs.py` detects changed files
3. **Claude Code reads docs/** — docs-en/ is for English-only contexts

## Maintenance Rules

1. **Update docs with code** — if you change behavior, update the relevant doc in the same PR
2. **README.md is mandatory** — every service and significant module must have one
3. **No stale docs** — delete docs for removed features; outdated docs are worse than no docs
4. **Translate after changes** — run `python3 scripts/translate-docs.py` after updating any doc
