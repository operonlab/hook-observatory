---
doc_version: 3
content_hash: pending
---

# Shared Layer Design — OOP Pattern Catalog

> Workshop 全 scope 的共用模式分析。每個 pattern 說明：誰用、用什麼 OOP 技術、怎麼用。

---

## Decisions

| 項目 | 決策 |
|------|------|
| ID 格式 | UUID v7 (`uuid-utils` library) |
| CRUD Service | BaseCRUD (標準) + helpers (特殊) 並存 |
| get_current_user | canonical 在 shared/deps.py，auth/deps.py re-export |
| Error codes | 結構化 `"module.error_name"` + 集中 registry + `GET /api/meta/error-codes` endpoint |
| 前端 shared | 同步設計 |
| spaceId 傳遞 | 明確傳參（不隱式注入） |
| Bridge shared | `core/src/shared/bridges/` |
| 文件 vs 程式碼 | 文件先行 |

---

## 1. Inheritance — 繼承

> 「是一種（is-a）」關係。子類自動獲得父類的 fields 和 behavior。

### 1.1 SQLAlchemy Model 繼承鏈

```
                        TimestampMixin
                     ┌───── id (UUID v7)
                     │ created_at (server_default)
                     │ updated_at (server_default + onupdate)
                     │
           ┌─────────┴─────────┐
     SpaceScopedModel       GlobalModel
   ┌── space_id (FK)      （無額外 fields）
   │── created_by (FK)          │
   │                            │
   ▼                            ▼
Transaction              AuditLog
Budget                   SystemSetting
Quest, Task
Spark, Link
Source, Memory
Skill, Resource
...（39 entities）
```

**誰繼承 SpaceScopedModel（8 modules, ~35 entities）**：
finance, quest, muse, scout, lore, dojo, roster, nexus

**誰繼承 GlobalModel（2 modules, ~4 entities）**：
admin (audit_log, setting), auth (user, api_key)

**auth 特殊**：space/space_member 是 meta-entity，不繼承任何 base — 自己定義 schema。

### 1.2 Pydantic Schema 繼承鏈

```
         TimestampMixin
      ┌── created_at
      │── updated_at
      │
      ├── SpaceScopedResponse
      │    ┌── id
      │    │── space_id
      │    └── created_by
      │         │
      │         ▼
      │    TransactionResponse
      │    QuestResponse
      │    SparkResponse ...
      │
      └── ErrorResponse
           ┌── detail
           │── code ("module.error_name")
           └── module
```

### 1.3 Exception 繼承鏈

```
  WorkshopError (base)
  ├── status_code: int
  ├── code: str ("module.error_name")
  ├── module: str | None
  │
  ├── NotFoundError (404)
  ├── ForbiddenError (403)
  ├── ConflictError (409)
  ├── BadRequestError (400)
  └── RateLimitError (429)
```

Exception handler 在 `main.py` 註冊，自動把 `WorkshopError` → HTTP response。

### 1.4 Frontend TypeScript 繼承

```typescript
// BaseEntity — mirrors SpaceScopedResponse
interface BaseEntity {
  id: string;
  space_id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

// 各 module extends
interface Transaction extends BaseEntity { amount: number; category: string; }
interface Quest extends BaseEntity { title: string; status: QuestStatus; }
interface Spark extends BaseEntity { content: string; tags: string[]; }
```

---

## 2. Generics — 泛型

> 行為相同，型別不同。一份邏輯 + 多種型別 = 消除重複。

### 2.1 Backend: BaseCRUDService\<M, C, U, R\>

```
BaseCRUDService<ModelT, CreateT, UpdateT, ResponseT>

  list(db, space_id, pagination) → PaginatedResponse<ResponseT>
  get(db, space_id, entity_id)   → ResponseT
  create(db, space_id, data: CreateT, user_id) → ResponseT
  update(db, space_id, entity_id, data: UpdateT) → ResponseT
  delete(db, space_id, entity_id) → bool
```

**使用**：
```
FinanceService = BaseCRUDService<Transaction, TransactionCreate, TransactionUpdate, TransactionResponse>
QuestService   = BaseCRUDService<Quest, QuestCreate, QuestUpdate, QuestResponse>
MuseService    = BaseCRUDService<Spark, SparkCreate, SparkUpdate, SparkResponse>
```

覆蓋 39 個 standard CRUD entities。

### 2.2 Backend: PaginatedResponse\<T\>

```
PaginatedResponse<T>
  items: list[T]
  total: int
  page: int
  page_size: int
  pages: int (computed)
```

所有 list endpoint 統一回傳此格式，T 替換為各 module 的 Response type。

### 2.3 Frontend: createCrudApi\<T, C, U\>

```typescript
createCrudApi<EntityT, CreateT, UpdateT>(basePath: string) → {
  list(spaceId, page?, pageSize?) → PaginatedResponse<EntityT>
  get(spaceId, id)                → EntityT
  create(spaceId, data: CreateT)  → EntityT
  update(spaceId, id, data: UpdateT) → EntityT
  delete(spaceId, id)             → void
}
```

每個 module 一行建立 API client：
```typescript
const transactionApi = createCrudApi<Transaction, CreateTransaction, UpdateTransaction>("/api/finance/transactions");
const questApi = createCrudApi<Quest, CreateQuest, UpdateQuest>("/api/quest/quests");
```

### 2.4 Frontend: PaginatedResponse\<T\> (mirror)

```typescript
interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}
```

---

## 3. Polymorphism — 多型

> 同一介面，不同實作。呼叫者不需要知道具體子類。

### 3.1 Template Method — Service Hook Points

BaseCRUDService 定義固定流程，子類 override 特定步驟：

```
create() 流程：
  1. before_create(data) → data     ← 可 override：驗證、轉換、預設值
  2. DB insert
  3. after_create(model)             ← 可 override：發事件、觸發副作用
  4. to_response(model) → response   ← 可 override：自訂序列化
```

**各 module 的 override 場景**：

| Module | before_create | after_create | to_response | custom methods |
|--------|:---:|:---:|:---:|---|
| finance | 金額驗證 | 發 `transaction.created` event | -- | monthly_insights() |
| quest | 預設 status=open | 發 `quest.created` event | join task count | dispatch(), accept(), complete() |
| muse | -- | 發 `spark.created` event | -- | graph_traverse(), semantic_search() |
| scout | -- | 排程摘要生成 | -- | generate_briefing() |
| lore | embedding 計算 | 發 event | -- | semantic_search(), auto_extract() |
| dojo | prerequisite 檢查 | 發 event | join learning progress | recommend() |
| roster | capacity 檢查 | 發 event | -- | check_availability() |
| nexus | -- | 發 event + 觸發評分 | -- | score(), match() |

### 3.2 Bridge Adapter — 同一介面，不同平台

```
BridgeAdapter (ABC)
  ├── receive(raw_payload) → WorkshopMessage    # 解析外部格式
  ├── send(event) → ExternalPayload             # 轉換成外部格式
  ├── validate_signature(headers, body) → bool   # 驗證 webhook 來源
  └── refresh_token() → str                      # Token 管理

LINEAdapter(BridgeAdapter)       — LINE Messaging API 實作
TelegramAdapter(BridgeAdapter)   — Telegram Bot API 實作
DiscordAdapter(BridgeAdapter)    — Discord Webhook 實作
```

**多型調用**：Event Bus subscriber 不關心是哪個平台：
```python
adapter: BridgeAdapter = get_adapter(platform)
adapter.send(event)  # LINE/Telegram/Discord 各自處理
```

### 3.3 Error Handler — 統一入口，按 subclass 分派

```python
# main.py 註冊一個 handler，自動處理所有 WorkshopError 子類
app.add_exception_handler(WorkshopError, workshop_error_handler)

# NotFoundError → 404, ForbiddenError → 403, etc.
# 不需要在每個 route 裡寫 try/except
```

---

## 4. Encapsulation — 封裝

> 隱藏內部細節，只暴露必要介面。

### 4.1 FastAPI Dependencies — 封裝認證/權限/分頁

| Dependency | 封裝了什麼 | 暴露什麼 |
|-----------|-----------|---------|
| `get_current_user()` | Session cookie 解析、itsdangerous 驗簽 | `dict` (user info) |
| `get_space_id()` | Path param / query 提取、存在性驗證 | `str` (space_id) |
| `require_permission(action)` | RBAC lookup + ABAC policy evaluation | pass 或 raise 403 |
| `get_pagination()` | Query param parsing + validation | `PaginationParams` |
| `get_db()` | Connection pool、session lifecycle | `AsyncSession` |

Route handler 只看到乾淨的 interface：
```python
@router.get("/")
async def list_transactions(
    space_id: str = Depends(get_space_id),
    pagination: PaginationParams = Depends(get_pagination),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.list(db, space_id, pagination)
```

### 4.2 Error Registry — 封裝 code ↔ status 映射

```python
# 使用者只需 raise NotFoundError("finance.transaction_not_found")
# Registry 自動查出 status=404, default_message="Transaction not found"
# Exception handler 自動組裝 HTTP response
```

模組不需要知道 HTTP 狀態碼。

### 4.3 Event Publishing — 封裝 Event 建構

```python
# 不用每次手動建 Event 物件
# publish_crud_event("finance", "transaction", "created", data, user_id)
# 內部自動：建 Event → 設 type/source/user_id/trace_id → bus.publish
```

### 4.4 Frontend API Client — 封裝 HTTP 細節

```typescript
// 使用者只呼叫 transactionApi.list(spaceId, page)
// client 內部處理：credentials, headers, error parsing, retry
```

---

## 5. Composition — 組合

> 「有一個（has-a）」關係。把能力拼裝在一起。

### 5.1 Service = CRUD + Event + Permission

BaseCRUDService 不直接耦合 EventBus 或 PolicyEngine。
子類在 hook 裡自由組合：

```
FinanceService
  has-a: BaseCRUDService (繼承)
  uses: publish_crud_event() (在 after_create 呼叫)
  uses: require_permission() (在 route 層，非 service 層)
```

### 5.2 Standalone Helpers（給非標準 entities）

不繼承 BaseCRUDService 的 entity 可以直接使用 helper functions：

| Helper | 功能 |
|--------|------|
| `build_paginated_query(model, space_id, filters, order_by)` | 組裝 SELECT |
| `paginate(stmt, db, pagination)` | 執行 + 包裝成 PaginatedResponse |
| `get_or_404(db, model, id, space_id)` | 查不到就 raise NotFoundError |
| `check_exists(db, model, **filters)` | 檢查唯一約束 |

Quest 的 state machine (accept/complete) 不走 BaseCRUD，但仍用 `get_or_404` + `publish_crud_event`。

---

## 6. Backend ↔ Frontend Contract

| 概念 | Backend (Python) | Frontend (TypeScript) |
|------|-----------------|----------------------|
| Base Entity | `SpaceScopedResponse` | `BaseEntity` interface |
| Paginated List | `PaginatedResponse[T]` | `PaginatedResponse<T>` |
| Error | `ErrorResponse` | `ErrorResponse` |
| Error Codes | `ERROR_REGISTRY` dict → `GET /api/meta/error-codes` | fetch at init → local map |
| CRUD Operations | `BaseCRUDService<M,C,U,R>` | `createCrudApi<T,C,U>(path)` |
| Space Context | `get_space_id()` dependency | explicit `spaceId` param |
| Auth | `get_current_user()` dependency | `useAuth()` hook (session cookie) |
| Pagination | `get_pagination()` → `PaginationParams` | `usePaginatedList(fetcher, spaceId)` |

---

## 7. File Map

### Backend: `core/src/shared/`

| File | Contains | Technique |
|------|----------|-----------|
| `types.py` | UserId, SpaceId, EntityId, TypeVars | Type alias |
| `schemas.py` | TimestampMixin, SpaceScopedResponse, PaginationParams, PaginatedResponse\<T\>, ErrorResponse | Inheritance + Generic |
| `models.py` | Base, TimestampMixin, SpaceScopedModel, GlobalModel | Mixin |
| `service.py` | BaseCRUDService\<M,C,U,R\> + helper functions | Generic + Template Method + Composition |
| `deps.py` | get_db, get_current_user, get_space_id, require_permission, get_pagination | Encapsulation (DI) |
| `exceptions.py` | WorkshopError hierarchy + ERROR_REGISTRY | Inheritance + Registry |
| `events.py` | event_type(), publish_crud_event() | Encapsulation (function) |

### Frontend: `workbench/src/shared/`

| File | Contains | Technique |
|------|----------|-----------|
| `api/client.ts` | fetch wrapper + error interceptor | Encapsulation |
| `api/crud.ts` | createCrudApi\<T,C,U\> | Generic + Factory |
| `types/base.ts` | BaseEntity, PaginatedResponse\<T\>, ErrorResponse | Interface (mirrors backend) |
| `types/errors.ts` | error code map (from `/api/meta/error-codes`) | Registry |
| `hooks/usePaginatedList.ts` | paginated data fetching | Custom Hook |
| `hooks/useSpaceId.ts` | current space context | Custom Hook |
| `errors/handler.ts` | global error → toast/redirect | Encapsulation |
| `components/ModuleLayout.tsx` | module page skeleton | Composition |
| `components/PaginatedList.tsx` | list + pagination controls | Composition |

### Future: `core/src/shared/bridges/`

| File | Contains | Technique |
|------|----------|-----------|
| `adapter.py` | BridgeAdapter ABC | Polymorphism (ABC) |
| `auth.py` | webhook signature validation | Encapsulation |

---

## 8. 覆蓋率

| 數字 | 說明 |
|------|------|
| **39** | Standard CRUD entities → BaseCRUDService 覆蓋 |
| **~28** | Special methods → standalone helpers + custom service |
| **8/10** | Core modules 使用 SpaceScopedModel |
| **~60** | Event types 統一 `module.entity.action` 格式 |
| **3+** | Bridge platforms 使用 BridgeAdapter 多型 |
| **9** | Frontend modules mirror backend shared types |
