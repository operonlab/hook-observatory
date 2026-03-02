---
source_hash: d0cb8d23
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Core (Modular Monolith)

Core services — an event-driven Modular Monolith.

## Run
```bash
uvicorn src.main:app --host 127.0.0.1 --port 8800
```

## Modules (10 domains)
| Module | Domain | Phase |
|--------|--------|-------|
| auth | Authentication & Authorization (RBAC+ABAC) | 1 |
| finance | Finance / Bookkeeping | 1 |
| quest | Quests / Adventures | 1 |
| muse | Inspiration / Notes | 1 |
| admin | System Administration | 1 |
| scout | Daily Intelligence | 2 |
| lore | LLM Memory | 2 |
| dojo | Skill Tree | 2 |
| roster | Resource Management | 3 |
| nexus | Matching Engine | 3 |

## Hot-Path Services
- `services/realtime/` — LiveKit WebRTC gateway (port 8830)
- `services/media/` — STT/TTS/image processing (port 8831)
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3039ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2491ms
