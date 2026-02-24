---
doc_version: 1
content_hash: 3ff968ae
source_version: 1
target_lang: zh-TW
translated_at: 2026-02-23
---

# 事件驅動架構 (Event-Driven Architecture)

## 設計理念

**萬物皆事件。事件驅動狀態變更。**

當一個模組變更狀態時，它會發布一個事件。其他模組（和插件）訂閱它們關心的事件。這在模組之間建立了鬆散耦合，同時維護了系統中發生之所有事情的清晰稽核軌跡。

```
模組 A 變更狀態
    → 發布事件至事件匯流排 (Event Bus)
    → 模組 B 接收事件並做出反應
    → 模組 C 接收事件並做出反應
    → 插件 Hook 觸發
    → 記錄 OTel span
```

## 事件結構

每個事件都遵循以下 Schema：

```python
 @.cache/uv/archive-v0/uj_7CuQMD1gog0o_f4ybB/huggingface_hub/dataclasses.py
class Event:
    type: str           # 例如 "finance.transaction.created"
    data: dict          # 事件負載 (payload)
    id: str             # 唯一事件 ID (UUID v7)
    timestamp: str      # ISO 8601 時間戳記
    source: str         # 發布事件的模組
    user_id: str | None # 觸發動作的使用者（如果適用）
    trace_id: str       # 用於關聯的 OpenTelemetry trace ID
```

範例：

```json
{
  "type": "finance.transaction.created",
  "data": {
    "transaction_id": "txn_abc123",
    "amount": 150.00,
    "currency": "TWD",
    "category": "food"
  },
  "id": "evt_01HQXYZ...",
  "timestamp": "2026-02-22T10:30:00Z",
  "source": "finance",
  "user_id": "usr_456",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
}
```

## 事件命名規範

```
{domain}.{entity}.{past_tense_verb}
```

| 組成部分 | 規則 | 範例 |
|-----------|------|---------|
| `domain` | 模組名稱 | `auth`, `finance`, `taskflow`, `ideagraph` |
| `entity` | 業務實體（單數） | `user`, `transaction`, `taskflow`, `spark` |
| `verb` | 過去式（事件已經發生） | `created`, `updated`, `deleted`, `completed` |

### 各模組標準事件

| 模組 | 事件 |
|--------|--------|
| auth | `auth.user.registered`, `auth.user.approved`, `auth.user.suspended`, `auth.user.logged_in`, `auth.user.logged_out` |
| finance | `finance.transaction.created`, `finance.transaction.updated`, `finance.budget.exceeded`, `finance.subscription.renewed` |
| taskflow | `taskflow.task.created`, `taskflow.task.completed`, `taskflow.skill.leveled_up`, `taskflow.reward.claimed` |
| ideagraph | `ideagraph.spark.created`, `ideagraph.spark.linked`, `ideagraph.graph.updated` |
| admin | `admin.setting.changed`, `admin.plugin.installed`, `admin.plugin.removed` |

### 系統事件

| 事件 | 觸發時機 |
|-------|------|
| `system.startup` | 應用程式啟動 |
| `system.shutdown` | 應用程式正在關閉 |
| `system.health.degraded` | 健康檢查偵測到問題 |

## EventBus API

### 核心介面

```python
class EventBus:
    async def publish(self, event_type: str, data: dict, **kwargs) -> str:
        """發布事件。回傳事件 ID。"""

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """將處理程序訂閱至特定事件類型。支援 glob 模式。"""

    def on(self, event_type: str) -> Callable:
        """用於訂閱處理程序的裝飾器。"""

    def use(self, middleware: EventMiddleware) -> None:
        """註冊在每個事件上運行的中間件。"""
```

### 發布事件

```python
# 直接發布
event_id = await event_bus.publish(
    "finance.transaction.created",
    data={"transaction_id": "txn_abc", "amount": 150.00},
    user_id=current_user.id,
)

# 或從模組的服務層 (service layer) 內發布
class TransactionService:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def create_transaction(self, data: CreateTransactionRequest, user_id: str):
        txn = await self.repo.insert(data)
        await self.event_bus.publish(
            "finance.transaction.created",
            data={"transaction_id": str(txn.id), "amount": txn.amount},
            user_id=user_id,
        )
        return txn
```

### 訂閱事件

```python
# 裝飾器風格
 @event_bus.on("finance.transaction.created")
async def on_transaction_created(event: Event):
    # 檢查這是否觸發了任務成就
    await check_spending_quest(event.data["transaction_id"], event.user_id)

# Glob 模式訂閱
 @event_bus.on("finance.*.*")
async def on_any_finance_event(event: Event):
    # 稽核記錄所有財務事件
    await audit_log.record(event)

# 手動訂閱
event_bus.subscribe("taskflow.task.completed", handle_quest_completion)
```

### 中間件 (Middleware)

中間件會攔截每個事件以處理橫切關注點 (cross-cutting concerns)：

```python
class OTelEventMiddleware(EventMiddleware):
    """為每個事件建立 OpenTelemetry spans。"""

    async def __call__(self, event: Event, next: Callable):
        with tracer.start_as_current_span(f"event:{event.type}") as span:
            span.set_attribute("event.id", event.id)
            span.set_attribute("event.source", event.source)
            await next(event)

class LoggingMiddleware(EventMiddleware):
    """使用 structlog 記錄每個事件。"""

    async def __call__(self, event: Event, next: Callable):
        log.info("event.published", event_type=event.type, event_id=event.id)
        await next(event)
        log.info("event.handled", event_type=event.type, event_id=event.id)

# 註冊中間件
event_bus.use(OTelEventMiddleware())
event_bus.use(LoggingMiddleware())
```

## 事件流範例

### 1. 使用者註冊 → 管理員通知

```
使用者提交註冊表單
    │
    ▼
Auth 模組：建立使用者 (status=pending)
    │
    ▼
Auth 模組：publish("auth.user.registered", {user_id, email, name})
    │
    ├──► Admin 模組訂閱者：建立稽核日誌條目
    │
    ├──► 通知 Hook：發送管理員電子郵件/推播通知
    │
    └──► 插件 Hook (before_user_approve)：自定義驗證
```

### 2. 交易建立 → 任務成就

```
使用者建立一筆財務交易
    │
    ▼
Finance 模組：插入交易，publish("finance.transaction.created", {txn_id, amount, category})
    │
    ├──► Quest 模組訂閱者：
    │       檢查使用者是否有進行中的支出任務
    │       如果達到門檻 → 完成任務
    │       publish("taskflow.task.completed", {quest_id, user_id})
    │       │
    │       ├──► Finance 模組訂閱者：發放獎勵積分
    │       │
    │       └──► Muse 模組訂閱者：建立成就靈感 (spark)
    │
    └──► Admin 模組訂閱者：稽核日誌
```

### 3. 插件安裝 → Hook 註冊

```
管理員透過 Manifest 安裝插件
    │
    ▼
Admin 模組：驗證 Manifest，安裝插件
    │
    ▼
Admin 模組：publish("admin.plugin.installed", {plugin_id, hooks})
    │
    ├──► Hook 引擎：註冊插件的 Hook 處理程序
    │
    ├──► Auth 模組：註冊插件的權限集
    │
    └──► 前端：重新載入插件 UI 插槽 (slots)
```

## 後端策略

### 階段 1：進程內非同步 (當前)

事件使用 Python 的 `asyncio` 在進程內分發：

```python
class InProcessEventBus(EventBus):
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._middleware: list[EventMiddleware] = []

    async def publish(self, event_type: str, data: dict, **kwargs) -> str:
        event = Event(type=event_type, data=data, id=str(uuid7()), ...)
        # 跑完中間件鏈，然後分發給處理程序
        for handler in self._match_handlers(event_type):
            asyncio.create_task(handler(event))
        return event.id
```

**優點**：零延遲、無外部依賴、簡單調試。
**缺點**：進程崩潰時事件遺失、無跨進程傳遞。

### 階段 2：Redis Streams (未來)

當系統需要持久性或跨服務事件時：

```python
class RedisStreamEventBus(EventBus):
    async def publish(self, event_type: str, data: dict, **kwargs) -> str:
        event = Event(type=event_type, data=data, ...)
        await self.redis.xadd(f"events:{event_type}", event.to_dict())
        return event.id
```

**優點**：持久化、跨服務、支援用於負載平衡的消費者群組 (consumer groups)。
**缺點**：額外的基礎架構、微小的延遲。

### 階段 3：NATS (遙遠的未來)

如果系統需要多節點、高吞吐量的事件流：
- 使用 NATS JetStream 實現持久流
- 基於主題 (Subject-based) 的路由與我們的命名規範一致
- 內建消費者群組與重播功能

## 可觀測性整合

每個事件都是一等可觀測性公民：

| 信號 | 內容 | 方式 |
|--------|------|-----|
| Trace | 每個事件 = 父級 Trace 中的一個 Span | `trace_id` 欄位傳遞 |
| Metric | 事件吞吐量、延遲、錯誤率 | OTel 事件中間件計數器 |
| Log | 結構化事件日誌 | 帶有事件元數據的 structlog |

```python
# 每個事件類型的自動指標
event_counter = meter.create_counter("events.published", description="發布的事件數")
event_latency = meter.create_histogram("events.handling_duration_ms")
```

儀表板細節請參閱 [可觀測性 (Observability)](./observability.md)。

## 規則

1. **僅限過去式**：事件描述已經發生的事情。永遠不要使用 `user.create` —— 始終使用 `user.created`。
2. **事件是不可變的**：一旦發布，事件的數據永遠不會改變。如需更正，請發布新事件。
3. **等冪處理程序**：訂閱者必須能夠在沒有副作用的情況下處理兩次相同的事件。
4. **無請求/回應**：事件是「發布後不管」(fire-and-forget)。如果你需要回應，請使用服務導入 (service import)。
5. **保持負載精簡**：僅包含 ID 和必要的數據。訂閱者可以透過服務導入獲取完整記錄。
6. **Schema 演進**：可以自由添加欄位。在沒有版本化事件類型的情況下，切勿移除或重新命名欄位。
