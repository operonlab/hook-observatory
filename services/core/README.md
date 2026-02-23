# Core Service (Modular Monolith)

核心服務 — 事件驅動的 Modular Monolith。

## Run
```bash
uvicorn core.main:app --host 127.0.0.1 --port 8800
```

## Modules
- auth: 認證授權 (RBAC+ABAC)
- finance: 記帳理財
- quest: 任務冒險
- muse: 靈感筆記
- admin: 系統管理
