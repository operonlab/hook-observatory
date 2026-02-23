# Core (Modular Monolith)

核心服務 — 事件驅動的 Modular Monolith。

## Run
```bash
uvicorn src.main:app --host 127.0.0.1 --port 8800
```

## Modules (10 domains)
| Module | Domain | Phase |
|--------|--------|-------|
| auth | 認證授權 (RBAC+ABAC) | 1 |
| finance | 記帳理財 | 1 |
| quest | 任務冒險 | 1 |
| muse | 靈感筆記 | 1 |
| admin | 系統管理 | 1 |
| scout | 每日情報 | 2 |
| lore | LLM 記憶 | 2 |
| dojo | 技能樹 | 2 |
| roster | 資源管理 | 3 |
| nexus | 配對引擎 | 3 |

## Hot-Path Services
- `services/realtime/` — LiveKit WebRTC gateway (port 8830)
- `services/media/` — STT/TTS/image processing (port 8831)
