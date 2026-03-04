---
doc_version: 6
content_hash: pending
source_version: 6
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
    TimestampMixin              SoftDeleteMixin
 ┌── id (UUID v7)             ┌── deleted_at (nullable, indexed)
 │── created_at                │
 │── updated_at                │
 │                             │
 └──────────┬──────────────────┘
            │ (both mixins)
  ┌─────────┴──────────┐
SpaceScopedModel    GlobalModel
 ┌── space_id       (TimestampMixin only,
 │── created_by      無 soft delete)
 │                        │
 ▼                        ▼
Transaction          AuditLog
Budget               SystemSetting
Quest, Task
Spark, Link
Source, Memory
Skill, Resource
...(39 entities)
```

**誰繼承了 SpaceScopedModel (8 個模組, ~35 個實體)**：
finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore
→ **全部具備軟刪除能力**（透過 `SoftDeleteMixin`）

**誰繼承了 GlobalModel (2 個模組, ~4 個實體)**：
admin (audit_log, setting), auth (user, api_key)
→ **無軟刪除**（僅有 `TimestampMixin`）

**auth 是特殊的**：space/space_member 是元實體 (meta-entities) — 它們不繼承任何基底並定義自己的 schema。

### 1.2 軟刪除模式 (Soft Delete Pattern)

> `SoftDeleteMixin` + `BaseCRUDService` 的協作，實現「刪除不消失」的資料保護。

**設計理由**：個人工作站中，誤刪資料的代價很高。軟刪除讓所有 `SpaceScopedModel` 實體（8 模組, ~35 實體）自動獲得「回收桶 + 恢復」能力。

#### Mixin 定義

```python
# core/src/shared/models.py
class SoftDeleteMixin:
    """Soft delete support — set deleted_at instead of hard deleting."""
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
```

- `deleted_at = None` → 正常存在
- `deleted_at = timestamp` → 已軟刪除（進入回收桶）
- 有 `index=True` → 查詢效能保證

#### BaseCRUDService 的自動行為

`BaseCRUDService` 會自動偵測 model 是否含有 `deleted_at` 欄位（`_has_soft_delete()`），並據此調整所有操作：

| 方法 | 行為（有 SoftDeleteMixin） | 行為（無 SoftDeleteMixin） |
|------|--------------------------|--------------------------|
| `list()` | 自動過濾 `deleted_at == None` | 回傳全部 |
| `get()` | 已刪除的回傳 `None` | 正常取得 |
| `get_including_deleted()` | 忽略軟刪除狀態，強制取得 | 同 `get()` |
| `delete()` | **設定 `deleted_at = now()`**（軟刪除） | **真正刪除**（hard delete） |
| `list_deleted()` | 回收桶：列出所有已軟刪除的項目 | 不適用 |
| `restore()` | 還原：`deleted_at = None` | 不適用 |
| `purge()` | 永久刪除（hard delete，不可逆） | 不適用 |

#### 完整生命週期

```
建立 → 正常存在 (deleted_at = NULL)
  │
  ├── list() / get() → ✅ 可見
  │
  ▼ delete()
軟刪除 (deleted_at = timestamp)
  │
  ├── list() / get() → ❌ 不可見（被自動過濾）
  ├── list_deleted() → ✅ 出現在回收桶
  │
  ├── restore() → 回到「正常存在」
  │
  └── purge() → 永久消失（不可逆）
```

#### 稽核追蹤

所有軟刪除操作都透過 `_record_audit()` 記錄：
- `delete` → action: `"delete"`, 記錄刪除者 (user_id) 與時間
- `restore` → action: `"restore"`
- `purge` → action: `"purge"`

#### 適用範圍

| 類別 | 模組 | 軟刪除 |
|------|------|--------|
| SpaceScopedModel | finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore | ✅ |
| GlobalModel | auth, admin | ❌ |

### 1.3 Pydantic Schema 繼承鏈

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

### 1.4 異常繼承鏈

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

### 1.5 前端 TypeScript 繼承

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

### 3.4 狀態機 (StateMachine) — 統一狀態轉換

多個模組的實體具有明確的狀態生命週期，共享統一的狀態機抽象：

```python
# shared/state_machine.py
class StateMachine:
    def __init__(self, transitions: dict[str, list[str]]):
        self.transitions = transitions

    def can_transition(self, from_state: str, to_state: str) -> bool: ...
    def transition(self, entity, to_state: str) -> None: ...  # 非法跳轉 → ConflictError
```

**各模組使用場景**：

| 模組 | 實體 | 狀態流 |
|------|------|--------|
| auth | User | pending → active → suspended / banned |
| taskflow | Task | todo → in_progress → review → done / cancelled / blocked |
| ideagraph | Spark | draft → refined → archived |
| ideagraph | Link | suggested → verified / rejected |
| finance | Subscription | active → paused → cancelled |

呼叫者只需 `machine.transition(entity, "done")`，非法轉換自動拋出 `ConflictError("taskflow.invalid_transition")`。

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

### 5.3 Tree Structure — 自引用父子關係 (Adjacency List)

多個實體使用 `parent_id` 自引用 FK 建立樹狀結構：

```sql
-- 通用 adjacency list pattern
parent_id   UUID REFERENCES same_table(id),  -- NULL = 頂層
sort_order  INT DEFAULT 0                    -- 同層排序
```

| 模組 | 實體 | 用途 |
|------|------|------|
| finance | categories | 樹狀分類（飲食 > 午餐 > 外送） |
| taskflow | tasks | 子任務（parent_id → 父任務） |

**共享查詢**：`build_tree_query(model, space_id)` — 遞迴 CTE 查詢整棵樹，回傳巢狀結構。

### 5.4 Tags[] 標準化

5 個模組使用 `TEXT[]` + GIN 索引存儲標籤：

```sql
tags  TEXT[] DEFAULT '{}',
CREATE INDEX idx_{table}_tags ON {schema}.{table} USING GIN(tags);
```

| 模組 | 實體 | 標籤用途 |
|------|------|---------|
| finance | transactions | 消費標籤（午餐、報帳） |
| taskflow | tasks | 任務分類（urgent、frontend） |
| ideagraph | sparks | 想法標籤（AI、架構） |
| intelflow | reports | 報告分類（company-intel） |
| memvault | blocks | 記憶標籤（pattern、preference） |

**前端對應**：`shared/components/TagsInput.tsx` 統一標籤輸入元件 + 統一的 `?tags=a,b` 查詢參數。

### 5.5 JSONB 結構化彈性欄位

需要半結構化資料的場景使用 JSONB：

| 模組 | 欄位 | JSONB 內容 |
|------|------|-----------|
| taskflow | tasks.recurrence | `{"type": "weekly", "days": [1,3,5]}` |
| auth | notification_preferences | `{"finance": {"enabled": true, "channels": ["pwa"]}}` |
| auth | oauth_accounts.raw_data | 完整 OAuth profile 備份 |
| memvault | profile_scores | Profile Score（知識/態度/技能） |

**最佳實踐**：
- Pydantic schema 中用 typed model 定義 JSONB 結構（非 `dict[str, Any]`）
- PostgreSQL 端用 `jsonb_path_exists()` 查詢
- 可枚舉的值不放進 JSONB（應為獨立欄位）
- 前端用 zod schema 驗證 JSONB 結構

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
| `models.py` | Base, TimestampMixin, SoftDeleteMixin, SpaceScopedModel, GlobalModel | Mixin |
| `service.py` | BaseCRUDService\<M,C,U,R\> + 軟刪除生命週期 + 輔助函式 | 泛型 + 範本方法 + 組合 |
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

### 未來：`core/src/shared/` (新增共享服務)

| 檔案 | 內容 | 技術 |
|------|----------|-----------|
| `state_machine.py` | StateMachine 狀態轉換引擎 | 多型 + 宣告式規則 |
| `embedding.py` | EmbeddingService (pgvector) | 封裝 + 策略模式 |
| `llm.py` | LLMService 抽象層 | 多型 (Provider ABC) |
| `semantic_search.py` | SemanticSearchService | 泛型 + 組合 |
| `report_generator.py` | ScheduledReportGenerator | 範本方法 |
| `export.py` | ExportService (CSV/JSON/Markdown) | 策略模式 |
| `tree.py` | build_tree_query() 遞迴 CTE | 組合 (函式) |

### 未來：`workbench/src/shared/components/` (新增共享元件)

| 檔案 | 內容 | 技術 |
|------|----------|-----------|
| `ForceGraph.tsx` | D3 force-directed 圖譜 | 組合 (React + D3) |
| `CalendarView.tsx` | FullCalendar 包裝器 | 組合 |
| `ReportViewer.tsx` | Markdown 報告檢視器 | 組合 |
| `ChartKit.tsx` | Recharts/ECharts 統一封裝 | 策略模式 |
| `DashboardWidget.tsx` | Widget 協議元件 | 組合 (Slot pattern) |
| `TagsInput.tsx` | 標籤輸入 + 過濾 | 封裝 |

---

## 8. 共享服務層 (Shared Services)

> 跨模組的後端服務抽象。每個服務被 2+ 模組使用，統一放在 `core/src/shared/`。

### 8.1 EmbeddingService — pgvector 向量服務

統一管理向量生成與儲存，解決維度不一致問題：

```python
class EmbeddingService:
    def __init__(self, provider: EmbeddingProvider, dimensions: int):
        self.provider = provider       # ollama / openai / local
        self.dimensions = dimensions   # 統一為 768d（Ollama nomic-embed-text）

    async def embed(self, text: str) -> list[float]: ...
    async def batch_embed(self, texts: list[str]) -> list[list[float]]: ...
    async def similarity_search(self, query_vec, table, top_k=10, threshold=0.7): ...
```

**使用模組與維度規範**：

| 模組 | 向量欄位 | 維度 | Provider |
|------|---------|------|----------|
| memvault | blocks.embedding | 768d | Ollama nomic-embed-text |
| ideagraph | sparks.embedding | 768d | 同上（統一） |
| intelflow | report_embeddings.embedding | 768d | 同上（統一） |

> **決策**：統一使用 768d (Ollama nomic-embed-text)。若未來需要 1536d (OpenAI) 則透過 `EmbeddingProvider` 策略切換，不改介面。

### 8.2 LLMService — LLM 抽象層

5 個模組需要呼叫 LLM，統一抽象避免各自實作：

```python
class LLMService:
    async def complete(self, prompt: str, model: str = "default", **kwargs) -> str: ...
    async def structured_output(self, prompt: str, schema: type[BaseModel]) -> BaseModel: ...
```

| 模組 | 用途 | 呼叫方式 |
|------|------|---------|
| finance | 月度報告 AI 建議 | `structured_output(prompt, MonthlyInsight)` |
| taskflow | 日誌/週報/月報 AI 觀察 | `complete(prompt)` |
| ideagraph | Spark 精煉 + 連結推演 | `structured_output(prompt, RefinedSpark)` |
| intelflow | 每日情報彙整 + 三分析師辯論 | `complete(prompt)` |
| memvault | SessionEnd 記憶提煉 | `structured_output(prompt, MemoryBlock)` |

### 8.3 SemanticSearchService — 跨模組語意搜尋

統一的向量相似度搜尋介面，支援單模組搜尋和跨模組聯邦搜尋：

```python
class SemanticSearchService:
    async def search(self, query: str, module: str, top_k: int = 10) -> list[SearchResult]: ...
    async def federated_search(self, query: str, modules: list[str], top_k: int = 10) -> list[SearchResult]: ...
```

**聯邦搜尋**：同一個查詢在 memvault + ideagraph + intelflow 三個 schema 中搜尋，結果合併排序。

### 8.4 ScheduledReportGenerator — 排程報告產生器

finance（月報）和 taskflow（日誌/週報/月報）共享報告產生管線：

```python
class ScheduledReportGenerator(ABC):
    schedule: str                            # cron 表達式
    async def collect_data(self, period) -> dict: ...   # 資料收集
    async def render(self, data: dict) -> str: ...      # 格式化輸出
    async def enrich_with_ai(self, rendered: str) -> str: ...  # AI 增強（可選）
    async def store(self, report: str) -> None: ...     # 寫入 DB
```

| 模組 | 報告 | 頻率 |
|------|------|------|
| taskflow | 日誌 | 每天 23:00 |
| taskflow | 週報 | 每週日 22:00 |
| taskflow | 月報 | 每月最後一天 |
| finance | 月度消費報告 | 每月 1 號 |

### 8.5 ExportService — 匯出服務

多個模組需要匯出功能：

```python
class ExportService:
    async def export(self, data: list[dict], format: str) -> bytes:
        # format: "csv" / "json" / "markdown" / "pdf"
```

| 模組 | 匯出內容 | 格式 |
|------|---------|------|
| finance | 交易紀錄 | CSV, JSON |
| taskflow | 報告 | Markdown, PDF |
| intelflow | 搜尋報告 | Markdown |

### 8.6 BulkOperationsMixin — 批量操作

多個模組需要批量更新/刪除：

```python
class BulkOperationsMixin:
    async def bulk_update(self, db, ids: list[UUID], updates: dict) -> int: ...
    async def bulk_delete(self, db, ids: list[UUID]) -> int: ...
```

| 模組 | 操作 |
|------|------|
| taskflow | `bulk_update` — 批次更新任務狀態 |
| ideagraph | `batch_verify` — 批量驗證 suggested links |
| notification | `read-all` — 全部已讀 |

---

## 9. 共享前端元件 (Shared Frontend Components)

> 跨模組的前端 UI 元件。每個元件被 2+ 模組使用，統一放在 `workbench/src/shared/components/`。

### 9.1 ForceGraph — Galaxy/圖譜視覺化

3 個模組使用 D3.js force-directed graph：

```typescript
interface ForceGraphProps<N extends BaseNode, L extends BaseLink> {
  nodes: N[];
  links: L[];
  onNodeClick?: (node: N) => void;
  onLinkClick?: (link: L) => void;
  colorBy?: keyof N;
  sizeBy?: keyof N;
  layout?: "force" | "radial" | "tree";
}
```

| 模組 | 用途 | 節點 | 邊 |
|------|------|------|-----|
| memvault | Memvault Galaxy 星系圖 | Knowledge/Attitude/Skill 區塊 | 關聯線 |
| ideagraph | Idea Galaxy 圖譜 | Spark 節點 | Link（suggested=虛線, verified=實線） |
| intelflow | Topic 關聯圖 | 主題 | 主題關聯 |

### 9.2 CalendarView — 日曆元件

基於 FullCalendar 或 react-big-calendar 的統一封裝：

| 模組 | 事件來源 |
|------|---------|
| taskflow | 任務（due_date, start_date） |
| finance | 訂閱扣款日（next_billing） |

### 9.3 ReportViewer — 報告檢視器

統一的 Markdown 報告渲染元件（含統計卡片 + AI 建議區塊）：

| 模組 | 報告類型 |
|------|---------|
| taskflow | 日誌 / 週報 / 月報 |
| finance | 月度消費報告 |
| intelflow | 每日情報 / 搜尋報告 |

### 9.4 ChartKit — 圖表統一方案

統一的圖表函式庫封裝（Recharts 或 ECharts）：

```typescript
<ChartKit type="pie" data={categoryData} />
<ChartKit type="bar" data={monthlyData} />
<ChartKit type="line" data={trendData} />
<ChartKit type="progress" data={budgetData} />
```

| 模組 | 圖表類型 |
|------|---------|
| finance | 圓餅圖、柱狀圖、散佈圖、趨勢線、預算進度 |
| taskflow | 完成率統計、工時分佈、來源分佈 |
| intelflow | 主題時序圖、報告統計 |

### 9.5 DashboardWidget 協議 — Widget 系統

Workbench 首頁的 Widget 系統，每個模組可註冊 1+ Widget：

```typescript
interface DashboardWidget {
  id: string;                    // "finance-summary" / "taskflow-today"
  module: string;                // 所屬模組
  title: string;
  size: "small" | "medium" | "large";
  component: React.ComponentType;
  refreshInterval?: number;      // 自動重新整理間隔（秒）
}

// 模組註冊：
export const financeWidgets: DashboardWidget[] = [
  { id: "finance-summary", module: "finance", title: "本月摘要", size: "medium", component: FinanceSummaryWidget },
];
```

---

## 10. 涵蓋範圍

| 數量 | 描述 |
|--------|-------------|
| **39** | 標準 CRUD 實體 → 由 BaseCRUDService 涵蓋 |
| **~35** | 具備軟刪除的實體（SpaceScopedModel, 8 模組） |
| **~28** | 特殊方法 → 獨立小幫手 + 自定義服務 |
| **8/10** | 核心模組使用 SpaceScopedModel |
| **~60** | 遵循 `module.entity.action` 格式的事件型別 |
| **5** | 使用 StateMachine 的實體（User, Task, Spark, Link, Subscription） |
| **5** | 使用 Tags[] 標準化的模組 |
| **3** | 使用 Tree Structure 的實體 |
| **5** | 使用 LLMService 的模組 |
| **3** | 使用 EmbeddingService (pgvector 768d) 的模組 |
| **3+** | 使用 BridgeAdapter 多型的 Bridge 平台 |
| **3** | 使用 ForceGraph 視覺化的模組 |
| **3+** | 使用 ChartKit 的模組 |
| **10** | 前端模組可註冊 DashboardWidget |
