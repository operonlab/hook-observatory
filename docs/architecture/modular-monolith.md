---
doc_version: 3
content_hash: 87cf60a6
source_version: 3
target_lang: zh-TW
translated_at: 2026-02-23
---

# 模組化單體架構指南 (Modular Monolith Architecture Guide)

## 設計原則

### 1. 單一部署與模組邊界

後端是一個**單一的可部署單元**，具有清晰分離的領域模組。每個模組擁有其業務邏輯、資料庫 schema 和 API 路由——但它們都運行在同一個程序（process）中。

```
                    ┌─────────────────────────────────────┐
                    │          Core Monolith (port 8800)   │
                    │                                     │
                    │  ┌────────┐ ┌────────┐ ┌────────┐  │
                    │  │  auth  │ │finance │ │  taskflow │  │
                    │  └────────┘ └────────┘ └────────┘  │
                    │  ┌────────┐ ┌────────┐ ┌────────┐  │
                    │  │  ideagraph  │ │ intelflow  │ │  memvault  │  │
                    │  └────────┘ └────────┘ └────────┘  │
                    │  ┌────────┐ ┌────────┐ ┌────────┐  │
                    │  │  skillpath  │ │ workpool │ │ matchcore  │  │
                    │  └────────┘ └────────┘ └────────┘  │
                    │  ┌────────┐                        │
                    │  │ admin  │                        │
                    │  └────────┘                        │
                    │                                     │
                    │  ┌─────────────────────────────┐    │
                    │  │  Event Bus  │  Hook Engine  │    │
                    │  └─────────────────────────────┘    │
                    └─────────────────────────────────────┘
                              │            │
                    ┌─────────┴──┐   ┌─────┴────────┐
                    │  Realtime  │   │    Media      │
                    │  (LiveKit) │   │  (STT/TTS)   │
                    │  port 8830 │   │  port 8831   │
                    └────────────┘   └──────────────┘
```

**為何選擇模組化單體而非微服務：**
- 更簡單的部署與運維（一個程序，一個容器）
- 模組之間沒有網路延遲（進程內調用）
- 更容易進行調試與追蹤（單一日誌流）
- 模組邊界強制執行開發紀律，且無運維開銷
- 如果某個模組確實需要獨立擴展，以後可以輕鬆提取為微服務

### 2. 模組權限歸屬

每個模組擁有**一個**業務領域：

| 模組 | 擁有內容 | 資料庫 Schema | 階段 |
|--------|------|-----------------|-------|
| `auth` | Users, sessions, spaces, permissions | `auth` | 1 |
| `finance` | Transactions, budgets, subscriptions | `finance` | 1 |
| `taskflow` | Quests, tasks, dispatch, rewards | `taskflow` | 1 |
| `ideagraph` | Sparks, links, knowledge graph | `ideagraph` | 1 |
| `intelflow` | RSS feeds, daily briefings, topic tracking | `intelflow` | 2 |
| `memvault` | LLM memories, semantic search, profiles | `memvault` | 2 |
| `skillpath` | Skill trees, learning paths, assessments | `skillpath` | 2 |
| `workpool` | Resources (human/machine/agent), scheduling | `workpool` | 3 |
| `matchcore` | Talent-job matching, task pairing | `matchcore` | 3 |
| `admin` | Platform management, audit logs, system health | `admin` | 1 |

### 3. 模組邊界規則

**硬性規則：**
- 模組**不得**直接導入另一個模組的 models 或資料庫 tables
- 模組**不得**直接寫入另一個模組的 schema
- 跨模組讀取需通過**服務導入 (service imports)**（調用另一個模組的 service 層）
- 跨模組的狀態變更需通過 **Event Bus**

```python
# 正確：模組 A 透過服務導入讀取模組 B 的資料
from src.modules.finance.services import get_user_balance

# 正確：模組 A 透過事件通知模組 B
await event_bus.publish("taskflow.task.completed", {"quest_id": "...", "user_id": "..."})

# 錯誤：模組 A 直接導入模組 B 的 models
from src.modules.finance.models import Transaction  # 禁止行為
```

### 4. 獨立資料儲存

所有模組共享一個 PostgreSQL 實例，但使用**獨立的 schemas**：

```sql
CREATE SCHEMA auth;       -- 由 auth 模組擁有 (Phase 1)
CREATE SCHEMA finance;    -- 由 finance 模組擁有 (Phase 1)
CREATE SCHEMA taskflow;      -- 由 taskflow 模組擁有 (Phase 1)
CREATE SCHEMA ideagraph;       -- 由 ideagraph 模組擁有 (Phase 1)
CREATE SCHEMA intelflow;      -- 由 intelflow 模組擁有 (Phase 2)
CREATE SCHEMA memvault;       -- 由 memvault 模組擁有 (Phase 2)
CREATE SCHEMA skillpath;       -- 由 skillpath 模組擁有 (Phase 2)
CREATE SCHEMA workpool;     -- 由 workpool 模組擁有 (Phase 3)
CREATE SCHEMA matchcore;      -- 由 matchcore 模組擁有 (Phase 3)
CREATE SCHEMA admin;      -- 由 admin 模組擁有 (Phase 1)
```

跨 schema 查詢在技術上是可行的，但在**架構上是被禁止的**。如果模組 A 需要來自模組 B 的資料，它必須調用 B 的 service 層。

## 模組結構

每個模組遵循一致的內部佈局：

```
core/src/modules/<name>/
├── __init__.py          # 模組註冊
├── routes.py            # FastAPI 路由 (或 routes/ 目錄)
├── models.py            # SQLAlchemy / Pydantic 模型 (模組作用域)
├── schemas.py           # Pydantic 請求/響應 schemas
├── services.py          # 業務邏輯 (此模組的公共 API)
├── events.py            # 事件處理程序 (訂閱者)
├── hooks.py             # 此模組公開的 Hook 點
└── deps.py              # FastAPI 依賴項
```

`services.py` 是每個模組的**公共介面**。其他模組應從此處導入，絕不從 `models.py` 或 `routes.py` 導入。

## 模組間通訊

| 模式 | 適用時機 | 範例 |
|---------|------|---------|
| 服務導入 (同步) | 從另一個模組讀取資料 | `finance.services.get_balance(user_id)` |
| Event Bus (非同步) | 其他模組可能感興趣的狀態變更 | `taskflow.task.completed` 觸發 finance 獎勵 |
| `src.shared` 中的共享類型 | 2 個以上模組使用的通用類型 | `UserId`, `Pagination`, `ErrorResponse` |

詳情請參閱 [事件驅動架構 (Event-Driven Architecture)](./event-driven.md) 以了解詳細的事件模式。

## 熱點路徑服務 (Hot-Path Services)

有兩個服務運行在單體**之外**，因為它們具有根本不同的運行時需求：

### 實時服務 (Realtime Service, port 8830)

- **功能**：LiveKit WebRTC 網關 + agents
- **為何分離**：WebRTC 需要持久連接、媒體處理，以及不同的擴展模式
- **通訊方式**：用於 token 生成的 REST API，以及用於狀態同步的 Redis 事件

### 媒體服務 (Media Service, port 8831)

- **功能**：STT、TTS、圖像處理流水線
- **為何分離**：CPU/GPU 密集型，需要獨立的資源分配
- **通訊方式**：來自 core 的 HTTP API 調用，結果以事件形式發布

## 埠位分配

| 埠位 | 服務 |
|------|---------|
| 8800 | 核心單體 (Core Monolith) |
| 8830 | 實時服務 (LiveKit) |
| 8831 | 媒體服務 (STT/TTS) |
| 3000 | 前端開發伺服器 |

## 配置

使用 `pydantic-settings` 配合環境變數。模組特定的配置使用帶前綴的環境變數：

```python
from pydantic_settings import BaseSettings

class CoreSettings(BaseSettings):
    port: int = 8800
    db_url: str = "postgresql://localhost/workshop"
    redis_url: str = "redis://localhost:6379"
    debug: bool = False

    model_config = {"env_prefix": "CORE_"}
```

## 健康檢查

單體架構公開了一個單一的健康檢查端點，並包含各模組的狀態：

```json
{
  "status": "healthy",
  "service": "core",
  "version": "0.1.0",
  "modules": {
    "auth": "healthy",
    "finance": "healthy",
    "taskflow": "healthy",
    "ideagraph": "healthy",
    "intelflow": "healthy",
    "memvault": "healthy",
    "skillpath": "healthy",
    "workpool": "healthy",
    "matchcore": "healthy",
    "admin": "healthy"
  }
}
```

## 模組註冊

模組在啟動時向核心應用程式註冊自身：

```python
# core/src/app.py
from src.modules import auth, finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore, admin

def create_app() -> FastAPI:
    app = FastAPI()

    # 註冊模組路由 (Phase 1)
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(finance.router, prefix="/api/finance", tags=["finance"])
    app.include_router(taskflow.router, prefix="/api/taskflow", tags=["taskflow"])
    app.include_router(ideagraph.router, prefix="/api/ideagraph", tags=["ideagraph"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

    # 註冊模組路由 (Phase 2)
    app.include_router(intelflow.router, prefix="/api/intelflow", tags=["intelflow"])
    app.include_router(memvault.router, prefix="/api/memvault", tags=["memvault"])
    app.include_router(skillpath.router, prefix="/api/skillpath", tags=["skillpath"])

    # 註冊模組路由 (Phase 3)
    app.include_router(workpool.router, prefix="/api/workpool", tags=["workpool"])
    app.include_router(matchcore.router, prefix="/api/matchcore", tags=["matchcore"])

    # 初始化事件總線與 Hook 引擎
    app.state.event_bus = EventBus()
    app.state.hook_engine = HookEngine()

    # 註冊模組事件處理程序
    auth.register_events(app.state.event_bus)
    finance.register_events(app.state.event_bus)
    taskflow.register_events(app.state.event_bus)

    return app
```

## 未來展望：提取模組

如果某個模組的規模超出了單體的負荷（例如，媒體處理需要 GPU 擴展），提取路徑如下：

1. 模組已經具有清晰的邊界（service 層、事件、無跨模型導入）
2. 將進程內服務導入替換為 HTTP 用戶端調用
3. 將進程內事件替換為 Redis Streams 事件
4. 作為獨立服務部署
5. 其他模組無需更改（它們已經在使用 service/event 介面）

這就是從第一天起就強制執行模組邊界的核心優勢。
