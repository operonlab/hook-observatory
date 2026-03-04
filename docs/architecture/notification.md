---
doc_version: 2
content_hash: pending
target_lang: zh-TW
translated_at: 2026-03-04
---

# 通知與橋接架構

> 統一事件路由、多通道推播、雙向平台橋接。

---

## 架構總覽

```
┌─────────────────────────────────────────────────────────────┐
│  Core Monolith — EventBus                                    │
│                                                              │
│  finance.transaction.created                                 │
│  taskflow.task.completed                                     │
│  ideagraph.link.suggested                                    │
│  auth.user.registered                                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Notification Router（core/src/modules/notification/）         │
│                                                              │
│  1. 事件過濾：哪些事件需要通知？（notification_rules 表）       │
│  2. 使用者偏好：這個使用者要收這類通知嗎？（preferences 表）    │
│  3. 聚合防轟炸：短時間同類事件合併（aggregation buffer）       │
│  4. 格式化：依目標 channel 產生內容（template engine）         │
│  5. 路由派送：選擇最佳 channel → 呼叫 adapter                │
└──────┬───────────┬───────────┬───────────┬──────────────────┘
       │           │           │           │
       ▼           ▼           ▼           ▼
  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
  │ PWA Push│ │  ntfy   │ │  Email  │ │ Bridge  │
  │ (VAPID) │ │ (備用)  │ │ (SMTP)  │ │ Adapter │
  └─────────┘ └─────────┘ └─────────┘ └────┬────┘
                                            │
                                    ┌───────┼───────┐
                                    ▼       ▼       ▼
                                  LINE  Telegram  Discord
```

---

## 核心設計：兩層分離

### 第一層：Notification Module（單向推播）

| 屬性 | 值 |
|------|-----|
| **位置** | `core/src/modules/notification/` |
| **性質** | Core Module（DB-backed，擁有 `notification` schema） |
| **職責** | 事件→通知路由、格式化、派送、聚合、偏好管理 |

**只負責「發出去」**——不接收使用者回覆。

> **注意**：notification 是核心模組，非 hot-path service。它在 Core Monolith 內運行，擁有獨立的 DB schema。

### 第二層：Bridges（雙向通訊）

| 屬性 | 值 |
|------|-----|
| **位置** | `bridges/` |
| **性質** | 獨立連接器（每個平台一個子目錄） |
| **職責** | 接收外部訊息 → 正規化 → 路由到模組、模組事件 → 推送到外部平台 |

**既收又發**——使用者可以透過 LINE/Telegram/Discord 與系統互動。

### 為什麼分兩層？

| 面向 | Notification Service | Bridges |
|------|---------------------|---------|
| 方向 | 單向（Core → 使用者） | 雙向（使用者 ↔ Core） |
| 複雜度 | 低（格式化+發送） | 高（webhook 接收、指令解析、session 管理） |
| 依賴 | 內嵌在 Core Monolith | 可獨立部署 |
| 例子 | PWA push、Email、ntfy | LINE Bot、Telegram Bot、Discord Bot |
| 失敗影響 | 通知延遲 | 外部使用者無法互動 |

---

## NotificationEnvelope（正規化模型）

參考 OpenClaw 的 MessageEnvelope 模式，所有通知統一為：

```python
@dataclass
class NotificationEnvelope:
    # 來源
    event_type: str                     # "finance.transaction.created"
    event_payload: dict                 # 事件原始資料

    # 目標
    target_user_id: UUID                # 接收者
    target_space_id: UUID | None        # 空間（可選，用於群組通知）

    # 內容
    title: str                          # 通知標題
    body: str                           # 通知內文（純文字）
    body_html: str | None               # HTML 版本（email 用）
    icon: str | None                    # 圖示（PWA 用）
    url: str | None                     # 點擊跳轉 URL

    # 路由
    priority: str = "normal"            # "urgent" / "high" / "normal" / "low"
    channels: list[str] | None = None   # 指定 channel，None = 使用者偏好

    # 聚合
    group_key: str | None = None        # 同 group_key 的通知會被合併

    # 中繼資料
    created_at: datetime
    idempotency_key: str                # 防重複派送
```

---

## Channel Adapter 介面

參考 OpenClaw 的 Capability-Driven + Adapter 組合式設計：

```python
class ChannelCapabilities:
    """每個 channel 宣告自己的能力"""
    push: bool = False          # 能主動推送嗎？
    rich_text: bool = False     # 支援 HTML/Markdown？
    media: bool = False         # 支援圖片/檔案？
    batch: bool = False         # 支援批量發送？
    interactive: bool = False   # 支援按鈕/選單？（bridges only）
    bidirectional: bool = False # 能接收回覆？（bridges only）


class ChannelAdapter(ABC):
    """所有 channel 的基底介面"""

    @property
    @abstractmethod
    def channel_id(self) -> str:
        """唯一識別：'pwa_push', 'ntfy', 'email', 'line', 'telegram', 'discord'"""

    @property
    @abstractmethod
    def capabilities(self) -> ChannelCapabilities:
        """能力宣告"""

    @abstractmethod
    async def send(self, envelope: NotificationEnvelope) -> DeliveryResult:
        """發送通知，回傳結果"""

    # 可選 adapters（Interface Segregation）
    async def send_batch(self, envelopes: list[NotificationEnvelope]) -> list[DeliveryResult]:
        """批量發送（預設逐一呼叫 send）"""
        return [await self.send(e) for e in envelopes]

    async def validate_target(self, user_id: UUID) -> bool:
        """驗證目標使用者是否已設定此 channel"""
        return True
```

### Push Channel 實作

| Channel | capabilities | 技術 |
|---------|-------------|------|
| `pwa_push` | push=✅ rich=❌ media=❌ batch=✅ | Web Push API + VAPID |
| `ntfy` | push=✅ rich=✅ media=✅ batch=❌ | ntfy HTTP API |
| `email` | push=✅ rich=✅ media=✅ batch=✅ | SMTP / Resend API |
| `firebase` | push=✅ rich=❌ media=❌ batch=✅ | Firebase Cloud Messaging |

### Bridge Channel 實作

| Channel | capabilities | 技術 |
|---------|-------------|------|
| `line` | push=✅ rich=✅ media=✅ interactive=✅ bidirectional=✅ | LINE Messaging API |
| `telegram` | push=✅ rich=✅ media=✅ interactive=✅ bidirectional=✅ | Telegram Bot API |
| `discord` | push=✅ rich=✅ media=✅ interactive=✅ bidirectional=✅ | Discord.js |

---

## 使用者偏好（Notification Preferences）

存在 auth schema 中（因為是使用者級設定）：

```sql
CREATE TABLE auth.notification_preferences (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- 全域開關
    enabled     BOOLEAN NOT NULL DEFAULT true,
    quiet_hours JSONB,              -- {"start": "23:00", "end": "07:00", "timezone": "Asia/Taipei"}

    -- 按模組開關
    module_settings JSONB NOT NULL DEFAULT '{}',
    -- {
    --   "finance": {"enabled": true, "channels": ["pwa_push", "line"]},
    --   "taskflow": {"enabled": true, "channels": ["pwa_push"]},
    --   "ideagraph": {"enabled": false}
    -- }

    -- Channel 綁定
    channels    JSONB NOT NULL DEFAULT '{}',
    -- {
    --   "pwa_push": {"subscription": {...}},
    --   "line": {"user_id": "U1234567890"},
    --   "telegram": {"chat_id": 123456789},
    --   "email": {"address": "user@example.com"}
    -- }

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(user_id)
);
```

### 偏好 API

| 方法 | 路徑 | 用途 |
|------|------|------|
| GET | `/api/notifications/preferences` | 取得偏好設定 |
| PUT | `/api/notifications/preferences` | 更新偏好設定 |
| POST | `/api/notifications/preferences/channels/{channel}/bind` | 綁定 channel |
| DELETE | `/api/notifications/preferences/channels/{channel}/unbind` | 解綁 channel |
| POST | `/api/notifications/test` | 發送測試通知 |

---

## 通知聚合（Anti-Spam）

防止短時間大量同類事件轟炸使用者：

```python
class NotificationAggregator:
    """
    相同 group_key 的通知在 buffer_window 內會被合併。

    例：5 秒內收到 10 筆 finance.transaction.created
    → 合併為「你有 10 筆新交易紀錄」
    """
    buffer_window: int = 5          # 秒
    max_batch_size: int = 50        # 超過直接切斷

    # 合併策略
    strategies = {
        "finance.transaction.created": "count",      # 「N 筆新交易」
        "ideagraph.link.suggested": "count",          # 「N 條新建議連結」
        "taskflow.task.completed": "list",            # 列出完成的任務名
    }
```

---

## 通知歷史與追蹤

```sql
CREATE TABLE auth.notification_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id),
    envelope_json   JSONB NOT NULL,         -- 完整 NotificationEnvelope
    channel         VARCHAR(30) NOT NULL,   -- 實際使用的 channel
    status          VARCHAR(20) NOT NULL,   -- 'delivered' / 'failed' / 'aggregated'
    error_message   TEXT,
    read_at         TIMESTAMPTZ,            -- 使用者已讀時間
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_notification_log_user ON auth.notification_log(user_id, created_at DESC);
```

### 歷史 API

| 方法 | 路徑 | 用途 |
|------|------|------|
| GET | `/api/notifications` | 通知列表（分頁、過濾） |
| POST | `/api/notifications/{id}/read` | 標記已讀 |
| POST | `/api/notifications/read-all` | 全部已讀 |
| GET | `/api/notifications/unread-count` | 未讀數量（Badge 用） |

---

## Bridge 架構（雙向）

### 目錄結構

```
bridges/
├── _shared/                    # 共用介面與工具
│   ├── envelope.py             # MessageEnvelope 正規化
│   ├── adapter.py              # BridgeAdapter ABC
│   ├── router.py               # 訊息→模組路由邏輯
│   └── commands.py             # 統一指令解析
├── line/
│   ├── webhook.py              # LINE webhook 接收
│   ├── adapter.py              # LINE ChannelAdapter 實作
│   ├── commands.py             # LINE 專屬指令
│   └── config.py
├── telegram/
│   ├── webhook.py              # Telegram webhook 接收
│   ├── adapter.py              # Telegram ChannelAdapter 實作
│   ├── commands.py
│   └── config.py
└── discord/
    ├── bot.py                  # Discord bot 連線
    ├── adapter.py              # Discord ChannelAdapter 實作
    ├── commands.py
    └── config.py
```

### Inbound 訊息流（Bridge → Core）

```
外部平台
    │
    ▼
┌────────────────┐
│ webhook.py     │  1. 接收平台 webhook
│ (platform)     │
└───────┬────────┘
        │
        ▼
┌────────────────┐
│ envelope.py    │  2. 正規化為 MessageEnvelope
│ (_shared)      │     { sender, content, platform, metadata }
└───────┬────────┘
        │
        ▼
┌────────────────┐
│ router.py      │  3. 指令路由
│ (_shared)      │     "記帳 午餐 120" → finance.transaction.create
│                │     "任務 買牛奶" → taskflow.task.create
│                │     "想法 也許可以..." → ideagraph.spark.capture
└───────┬────────┘
        │
        ▼
┌────────────────┐
│ Core Module    │  4. 模組處理 → 回傳結果
│ services.py    │
└───────┬────────┘
        │
        ▼
┌────────────────┐
│ adapter.py     │  5. 格式化回覆 → 送回平台
│ (platform)     │
└────────────────┘
```

### 指令路由規則

```python
COMMAND_ROUTES = {
    # 關鍵字 → 模組.動作
    "記帳": "finance.transaction.create",
    "花費": "finance.transaction.create",
    "餘額": "finance.balance.query",
    "任務": "taskflow.task.create",
    "完成": "taskflow.task.complete",
    "想法": "ideagraph.spark.capture",
    "搜尋": "intelflow.search.execute",
    "提醒": "taskflow.task.create",  # + recurrence
}
```

---

## PWA Push 實作要點

### 前提條件

- `manifest.json`（PWA manifest）
- `sw.js`（Service Worker 註冊 push 事件）
- VAPID 金鑰對（伺服器端）

### 流程

```
1. 前端：ServiceWorker 註冊 → PushManager.subscribe() → 取得 subscription
2. 前端：POST /api/notifications/preferences/channels/pwa_push/bind {subscription}
3. 後端：儲存 subscription 到 notification_preferences.channels.pwa_push
4. 推播時：pywebpush.webpush(subscription, payload, vapid_key)
5. 前端：sw.js 收到 push event → 顯示 Notification
```

### 技術選型

| 項目 | 方案 |
|------|------|
| 後端 | `pywebpush`（Python VAPID push） |
| 前端 | Web Push API（原生，無需額外 lib） |
| 後備 | `ntfy`（self-hosted，不依賴瀏覽器支援） |
| 未來 | Firebase Cloud Messaging（行動 app 用） |

---

## 增長路徑

```
階段 1: PWA Push（VAPID）+ 通知偏好管理 + 通知歷史
         → 最小可用通知系統，零外部依賴

階段 2: + ntfy 備用通道 + 通知聚合 + 勿擾時段
         → 更穩健的推播體驗

階段 3: + LINE Bridge（webhook 接收 + 推播）
         → 第一個雙向平台，最高優先（台灣使用率）

階段 4: + Telegram Bridge + Discord Bridge
         → 多平台覆蓋

階段 5: + Email 通知 + Firebase（行動端）
         → 完整通知矩陣

階段 6: + AI 路由（根據緊急度自動選最佳 channel）
         → 智慧通知
```

---

## 相關文件

| 文件 | 用途 |
|------|------|
| [communication.md](./communication.md) | 整體通訊模式 |
| [event-driven.md](./event-driven.md) | EventBus 規範 |
| [domain-catalog.md](../vision/domain-catalog.md) | notification + social-hooks 定義 |
| [auth.md](./auth.md) | notification_preferences 所在的 auth schema |
