---
doc_version: 5
content_hash: 2989924d
source_version: 5
target_lang: zh-TW
translated_at: 2026-02-23
---

# 共享層設計 — OOP 模式目錄

> Workshop 共享模式的全方位分析。每個模式描述了：使用者是誰、採用了哪種 OOP 技術，以及如何使用。

---

## 決策

| 項目 | 決策 |
|------|----------|
| ID 格式 | UUID v7 (`uuid-utils` 函式庫) |
| CRUD Service | BaseCRUD (標準) + helpers (特殊) 並存 |
| get_current_user | 規範定義於 shared/deps.py，auth/deps.py 重新匯出 |
| 錯誤代碼 | 結構化 `"module.error_name"` + 集中註冊表 + `GET /api/meta/error-codes` 端點 |
| 前端共享 | 同步設計 |
| spaceId 傳遞 | 顯式參數 (無隱式注入) |
| Bridge 共享 | `core/src/shared/bridges/` |
| 文件 vs 代碼 | 文件優先 |

---

## 1. 繼承 (Inheritance)

> 「Is-a」關係。子類別自動繼承父類別的欄位與行為。

### 1.1 SQLAlchemy 模型繼承鏈

```
                        TimestampMixin
                     ┌───── id (UUID v7)
                     │ created_at (server_default)
                     │ updated_at (server_default + onupdate)
                     │
           ┌─────────┴─────────┐
     SpaceScopedModel       GlobalModel
   ┌── space_id (FK)      (no extra fields)
   │── created_by (FK)          │
   │                            │
   ▼                            ▼
Transaction              AuditLog
Budget                   SystemSetting
Quest, Task
Spark, Link
Source, Memory
Skill, Resource
...(39 entities)
```

**誰繼承了 SpaceScopedModel (8 個模組, ~35 個實體)**：
finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore

**誰繼承了 GlobalModel (2 個模組, ~4 個實體)**：
admin (audit_log, setting), auth (user, api_key)

**auth 是特殊的**：space/space_member 是元實體 (meta-entities) — 它們不繼承任何基底並定義自己的 schema。

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

### 1.3 異常繼承鏈

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

異常處理程序註冊在 `main.py` 中，自動將 `WorkshopError` 轉換為 HTTP 回應。

### 1.4 前端 TypeScript 繼承

```typescript
// BaseEntity — 對應 SpaceScopedResponse
interface BaseEntity {
  id: string;
  space_id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

// 每個模組進行擴展
interface Transaction extends BaseEntity { amount: number; category: string; }
interface Quest extends BaseEntity { title: string; status: QuestStatus; }
interface Spark extends BaseEntity { content: string; tags: string[]; }
```

---

## 2. 泛型 (Generics)

> 相同的行為，不同的型別。一份邏輯 + 多種型別 = 消除重複代碼。

### 2.1 後端：BaseCRUDService\<M, C, U, R\>

```
BaseCRUDService<ModelT, CreateT, UpdateT, ResponseT>

  list(db, space_id, pagination) → PaginatedResponse<ResponseT>
  get(db, space_id, entity_id)   → ResponseT
  create(db, space_id, data: CreateT, user_id) → ResponseT
  update(db, space_id, entity_id, data: UpdateT) → ResponseT
  delete(db, space_id, entity_id) → bool
```

**用法**：
```
FinanceService = BaseCRUDService<Transaction, TransactionCreate, TransactionUpdate, TransactionResponse>
QuestService   = BaseCRUDService<Quest, QuestCreate, QuestUpdate, QuestResponse>
MuseService    = BaseCRUDService<Spark, SparkCreate, SparkUpdate, SparkResponse>
```

涵蓋了 39 個標準 CRUD 實體。

### 2.2 後端：PaginatedResponse\<T\>

```
PaginatedResponse<T>
  items: list[T]
  total: int
  page: int
  page_size: int
  pages: int (computed)
```

所有列表端點均統一返回此格式，其中 T 被替換為每個模組的 Response 型別。

### 2.3 前端：createCrudApi\<T, C, U\>

```typescript
createCrudApi<EntityT, CreateT, UpdateT>(basePath: string) → {
  list(spaceId, page?, pageSize?) → PaginatedResponse<EntityT>
  get(spaceId, id)                → EntityT
  create(spaceId, data: CreateT)  → EntityT
  update(spaceId, id, data: UpdateT) → EntityT
  delete(spaceId, id)             → void
}
```

每個模組僅需一行代碼即可建立 API 用戶端：
```typescript
const transactionApi = createCrudApi<Transaction, CreateTransaction, UpdateTransaction>("/api/finance/transactions");
const questApi = createCrudApi<Quest, CreateQuest, UpdateQuest>("/api/taskflow/quests");
```

### 2.4 前端：PaginatedResponse\<T\> (對應)

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

## 3. 多型 (Polymorphism)

> 相同的介面，不同的實作。呼叫者無需知曉具體的子類別。

### 3.1 範本方法 (Template Method) — Service 鉤子點

BaseCRUDService 定義了一個固定流程；子類別覆寫特定步驟：

```
create() 流程：
  1. before_create(data) → data     ← 覆寫：驗證、轉換、預設值
  2. DB 插入
  3. after_create(model)             ← 覆寫：發送事件、觸發副作用
  4. to_response(model) → response   ← 覆寫：自定義序列化
```

**各模組覆寫場景**：

| 模組 | before_create | after_create | to_response | 自定義方法 |
|--------|:---:|:---:|:---:|---|
| finance | 金額驗證 | 發送 `transaction.created` 事件 | -- | monthly_insights() |
| taskflow | 預設狀態=open | 發送 `taskflow.created` 事件 | 關聯任務計數 | dispatch(), accept(), complete() |
| ideagraph | -- | 發送 `spark.created` 事件 | -- | graph_traverse(), semantic_search() |
| intelflow | -- | 排程摘要生成 | -- | generate_briefing() |
| memvault | Embedding 計算 | 發送事件 | -- | semantic_search(), auto_extract() |
| skillpath | 前置條件檢查 | 發送事件 | 關聯學習進度 | recommend() |
| workpool | 容量檢查 | 發送事件 | -- | check_availability() |
| matchcore | -- | 發送事件 + 觸發評分 | -- | score(), match() |

### 3.2 Bridge 配接器 — 相同介面，不同平台

```
BridgeAdapter (ABC)
  ├── receive(raw_payload) → WorkshopMessage    # 解析外部格式
  ├── send(event) → ExternalPayload             # 轉換為外部格式
  ├── validate_signature(headers, body) → bool   # 驗證 webhook 來源
  └── refresh_token() → str                      # 權杖管理

LINEAdapter(BridgeAdapter)       — LINE Messaging API 實作
TelegramAdapter(BridgeAdapter)   — Telegram Bot API 實作
DiscordAdapter(BridgeAdapter)    — Discord Webhook 實作
```

**多型調用**：Event Bus 訂閱者不在乎是哪個平台：
```python
adapter: BridgeAdapter = get_adapter(platform)
adapter.send(event)  # LINE/Telegram/Discord 各自以自己的方式處理
```

### 3.3 錯誤處理程序 — 單一進入點，由子類別分發

```python
# main.py 註冊一個處理程序，自動處理所有 WorkshopError 子類別
app.add_exception_handler(WorkshopError, workshop_error_handler)

# NotFoundError → 404, ForbiddenError → 403, 等等。
# 無需在每個路由中撰寫 try/except
```

---

## 4. 封裝 (Encapsulation)

> 隱藏內部細節，僅暴露必要的介面。

### 4.1 FastAPI 依賴項 — 封裝身份驗證/權限/分頁

| 依賴項 | 封裝了什麼 | 暴露了什麼 |
|-----------|---------------------|-----------------|
| `get_current_user()` | Session cookie 解析, itsdangerous 簽章驗證 | `dict` (使用者資訊) |
| `get_space_id()` | 路徑參數 / 查詢參數擷取, 存在性驗證 | `str` (space_id) |
| `require_permission(action)` | RBAC 查找 + ABAC 策略評估 | 通過或拋出 403 |
| `get_pagination()` | 查詢參數解析 + 驗證 | `PaginationParams` |
| `get_db()` | 連線池, session 生命週期 | `AsyncSession` |

路由處理程序看到的只有簡潔的介面：
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

### 4.2 錯誤註冊表 — 封裝代碼 ↔ 狀態映射

```python
# 使用者只需：raise NotFoundError("finance.transaction_not_found")
# 註冊表自動查找 status=404, default_message="Transaction not found"
# 異常處理程序自動組裝 HTTP 回應
```

模組無需了解 HTTP 狀態碼。

### 4.3 事件發布 — 封裝事件建構

```python
# 無需每次手動建立 Event 物件
# publish_crud_event("finance", "transaction", "created", data, user_id)
# 內部實作：建立 Event → 設定 type/source/user_id/trace_id → bus.publish
```

### 4.4 前端 API 用戶端 — 封裝 HTTP 細節

```typescript
// 使用者只需調用 transactionApi.list(spaceId, page)
// 用戶端內部處理：憑證、標頭、錯誤解析、重試
```

---

## 5. 組合 (Composition)

> 「Has-a」關係。將各項能力組裝在一起。

### 5.1 Service = CRUD + 事件 + 權限

BaseCRUDService 並不直接與 EventBus 或 PolicyEngine 耦合。
子類別在鉤子中自由組合：

```
FinanceService
  has-a: BaseCRUDService (繼承)
  uses: publish_crud_event() (在 after_create 中調用)
  uses: require_permission() (在路由層而非服務層)
```

### 5.2 獨立小幫手 (用於非標準實體)

不繼承 BaseCRUDService 的實體可以直接使用輔助函式：

| 小幫手 | 功能 |
|--------|----------|
| `build_paginated_query(model, space_id, filters, order_by)` | 組裝 SELECT |
| `paginate(stmt, db, pagination)` | 執行 + 包裝在 PaginatedResponse 中 |
| `get_or_404(db, model, id, space_id)` | 若未找到則拋出 NotFoundError |
| `check_exists(db, model, **filters)` | 檢查唯一性約束 |

Quest 的狀態機 (accept/complete) 不使用 BaseCRUD，但仍使用 `get_or_404` + `publish_crud_event`。

---

## 6. 後端 ↔ 前端契約

| 概念 | 後端 (Python) | 前端 (TypeScript) |
|---------|-----------------|----------------------|
| 基礎實體 | `SpaceScopedResponse` | `BaseEntity` 介面 |
| 分頁列表 | `PaginatedResponse[T]` | `PaginatedResponse<T>` |
| 錯誤 | `ErrorResponse` | `ErrorResponse` |
| 錯誤代碼 | `ERROR_REGISTRY` 字典 → `GET /api/meta/error-codes` | 初始化時獲取 → 本地映射 |
| CRUD 操作 | `BaseCRUDService<M,C,U,R>` | `createCrudApi<T,C,U>(path)` |
| 空間上下文 | `get_space_id()` 依賴項 | 顯式 `spaceId` 參數 |
| 身份驗證 | `get_current_user()` 依賴項 | `useAuth()` hook (session cookie) |
| 分頁 | `get_pagination()` → `PaginationParams` | `usePaginatedList(fetcher, spaceId)` |

---

## 7. 檔案對照表

### 後端：`core/src/shared/`

| 檔案 | 內容 | 技術 |
|------|----------|-----------|
| `types.py` | UserId, SpaceId, EntityId, TypeVars | 型別別名 |
| `schemas.py` | TimestampMixin, SpaceScopedResponse, PaginationParams, PaginatedResponse\<T\>, ErrorResponse | 繼承 + 泛型 |
| `models.py` | Base, TimestampMixin, SpaceScopedModel, GlobalModel | Mixin |
| `service.py` | BaseCRUDService\<M,C,U,R\> + 輔助函式 | 泛型 + 範本方法 + 組合 |
| `deps.py` | get_db, get_current_user, get_space_id, require_permission, get_pagination | 封裝 (DI) |
| `exceptions.py` | WorkshopError 層級 + ERROR_REGISTRY | 繼承 + 註冊表 |
| `events.py` | event_type(), publish_crud_event() | 封裝 (函式) |

### 前端：`workbench/src/shared/`

| 檔案 | 內容 | 技術 |
|------|----------|-----------|
| `api/client.ts` | fetch 包裝器 + 錯誤攔截器 | 封裝 |
| `api/crud.ts` | createCrudApi\<T,C,U\> | 泛型 + 工廠 |
| `types/base.ts` | BaseEntity, PaginatedResponse\<T\>, ErrorResponse | 介面 (對應後端) |
| `types/errors.ts` | 錯誤代碼映射 (來自 `/api/meta/error-codes`) | 註冊表 |
| `hooks/usePaginatedList.ts` | 分頁數據獲取 | 自定義 Hook |
| `hooks/useSpaceId.ts` | 當前空間上下文 | 自定義 Hook |
| `errors/handler.ts` | 全域錯誤 → 彈窗/重定向 | 封裝 |
| `components/ModuleLayout.tsx` | 模組頁面骨架 | 組合 |
| `components/PaginatedList.tsx` | 列表 + 分頁控制項 | 組合 |

### 未來：`core/src/shared/bridges/`

| 檔案 | 內容 | 技術 |
|------|----------|-----------|
| `adapter.py` | BridgeAdapter ABC | 多型 (ABC) |
| `auth.py` | webhook 簽章驗證 | 封裝 |

---

## 8. 涵蓋範圍

| 數量 | 描述 |
|--------|-------------|
| **39** | 標準 CRUD 實體 → 由 BaseCRUDService 涵蓋 |
| **~28** | 特殊方法 → 獨立小幫手 + 自定義服務 |
| **8/10** | 核心模組使用 SpaceScopedModel |
| **~60** | 遵循 `module.entity.action` 格式的事件型別 |
| **3+** | 使用 BridgeAdapter 多型的 Bridge 平台 |
| **10** | 前端模組對應後端共享型別 |
