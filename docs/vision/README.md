---
doc_version: 1
content_hash: 25063671
---

# Workshop Vision Documents

> 2026-02-23 brainstorming session output — Complete record of the Workshop platform vision.

## Documents

| File | Contents |
|------|----------|
| [workshop-manifesto.md](./workshop-manifesto.md) | What Workshop is, Core/Stations/Bridges taxonomy, design principles |
| [domain-catalog.md](./domain-catalog.md) | 10 Core Modules + 5 Project Ideas + dependency graph + classification index |
| [architecture-decisions.md](./architecture-decisions.md) | 7 ADRs: Monolith, MCP Adapter, Space Model, Widget, Resource, Event, Progressive |
| [roadmap.md](./roadmap.md) | Four-phase roadmap: Personal → Knowledge → Team → Commercial |

## Translations

Chinese (Traditional) translations are available in [`zh-TW/`](./zh-TW/) for quick reading.
English versions are the source of truth — Claude Code reads these.

## Quick Reference

### Three-Tier Taxonomy
- **Core Modules**: DB-backed business domains (auth, finance, quest, muse, intel, memory, skill, workforce, matching, admin)
- **Stations**: Standalone local tools (disk analyzer, LLM usage, legal advisor, church music)
- **Bridges**: External connectors (LINE, Telegram, Discord, Firebase, external APIs)

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
2. **Phase 2**: memory v2 + skill + intel + church music
3. **Phase 3**: workforce + task dispatch + multi-platform social
4. **Phase 4**: commercial (ERP/POS/legal/virtual CS)
