---
doc_version: 2
content_hash: pending
---

# Workshop Vision Documents

> Workshop platform vision — defining what we build, why, and how services compose.

## Documents

| File | Contents |
|------|----------|
| [workshop-manifesto.md](./workshop-manifesto.md) | What Workshop is, LEGO composition philosophy, three-tier taxonomy, design principles |
| [domain-catalog.md](./domain-catalog.md) | Unified Service Catalog + Composition Recipes + dependency graph |
| [architecture-decisions.md](./architecture-decisions.md) | 7 ADRs: Monolith, MCP Adapter, Space Model, Widget, Resource, Event, Progressive |
| [roadmap.md](./roadmap.md) | Four-phase roadmap: Personal → Knowledge → Team → Commercial |

## Translations

Chinese (Traditional) translations are available in [`zh-TW/`](./zh-TW/) for quick reading.
English versions are the source of truth — Claude Code reads these.

## Quick Reference

### LEGO Composition Model

There is no distinction between "projects" and "modules" — everything is a composable service:

```
Bottom-Up: Build service blocks (auth, finance, quest, muse, ...)
Top-Down:  Analyze requirements, design blueprints
Meeting:   Compose services into solutions (Legal Advisor, ERP, ...)
```

### Service Types

| Type | Examples | Data Residency |
|------|----------|---------------|
| **Foundation** | auth, admin | PostgreSQL |
| **Domain** | finance, quest, muse, scout, lore, dojo, roster, nexus | PostgreSQL (schema-per-module) |
| **Bridge** | social-hooks, notification | External + Event Bus |
| **Station** | Disk analysis, LLM usage, local tools | Local / Optional DB |
| **Composition** | Legal Advisor, Church Music, Virtual CS, ERP/POS | Assembly of above |

### Architecture Pattern
```
Claude Code → MCP Server (adapter) → FastAPI Core (monolith) → PostgreSQL
                                          ↕
Web Dashboard (widgets) ──────────► FastAPI Core
                                          ↕
Social Bridges (LINE/TG/DC) ─────► FastAPI Core
```

### Phase Summary
1. **Phase 1**: auth + finance + quest + muse + LINE bot + Widget Dashboard
2. **Phase 2**: lore v2 + dojo + scout + church music
3. **Phase 3**: roster + task dispatch + multi-platform social
4. **Phase 4**: commercial (ERP/POS/legal/virtual CS)
