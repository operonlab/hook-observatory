---
doc_version: 4
content_hash: 1dafee87
source_version: 4
target_lang: en
translated_at: 2026-02-24
source_hash: bcf86c2f
source_lang: zh-TW
---

# Workshop Vision Document

> Workshop Platform Vision — Defining what we build, why, and how the services compose.

## Document List

| File | Content |
|------|----------|
| [workshop-manifesto.md](./workshop-manifesto.md) | What Workshop is, LEGO composition philosophy, service classification, design principles |
| [domain-catalog.md](./domain-catalog.md) | Unified service catalog + composition recipes + dependency graph |
| [architecture-decisions.md](../architecture/architecture-decisions.md) | 7 ADRs: Monolith, MCP Adapter, Space Model, Widget, Resource, Event, Progressive |
| [composition-model.md](./composition-model.md) | LEGO composition model: pincer movement, composition recipes, decision flow |
| [roadmap.md](./roadmap.md) | Four-phase roadmap: Personal → Knowledge → Team → Commercial |

## Translation

`docs/` is written in Traditional Chinese (source of truth). `docs-en/` is the English backup (original English version).

## Quick Reference

### LEGO Composition Model

There is no distinction between "projects" and "modules" — everything is a composable service:

```
Bottom-Up: Build service blocks (auth, finance, quest, muse, ...)
Top-Down:  Analyze requirements, design blueprints
Meeting:   Compose services into solutions (Legal Advisor, ERP, ...)
```

### Service Types

| Type | Example | Data Residency |
|------|----------|---------------|
| **Foundation** | auth, admin | PostgreSQL |
| **Domain** | finance, quest, muse, scout, lore, dojo, roster, nexus | PostgreSQL (schema-per-module) |
| **Bridge** | social-hooks, notification | External + Event Bus |
| **Station** | system-monitor, llm-usage, envkit, sandbox-executor | Local / Optional DB |
| **Composition** | Legal Advisor, Church Music, Virtual CS, ERP/POS | Composition of the above services |

### Architecture Pattern
```
Claude Code → MCP Server (adapter) → FastAPI Core (monolith) → PostgreSQL
                                          ↕
Single React App ─────────────────► FastAPI Core
  ├── Layer 1: Module SPA Pages         (HTTP REST)
  ├── Layer 2: Dashboard Widgets        (HTTP REST)
  └── Layer 3: LLM Chat Overlay         (SSE streaming)
                                          ↕
Social Bridges (LINE/TG/DC) ─────► FastAPI Core
```

### Phase Summary
1. **Phase 1**: auth + finance + quest + muse + LINE bot + Widget Dashboard
2. **Phase 2**: lore v2 + dojo + scout + church music
3. **Phase 3**: roster + task dispatch + multi-platform social
4. **Phase 4**: Commercialization (ERP/POS/legal/virtual CS)
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3133ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3541ms
