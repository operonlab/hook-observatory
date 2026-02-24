---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

> [← 返回優先藍圖總覽](./v2-priorities.md)

# P8：Notification + Bridges — 通知推播與社群平台橋接

### 一句話定義

**統一通知路由引擎 + 雙向社群平台橋接**——讓所有模組的事件能觸達使用者，使用者也能透過 LINE/Telegram 直接操作系統。

---

### 為什麼需要

1. **所有模組都需要通知**：finance 超支警示、taskflow 任務到期、ideagraph 新建議連結——沒有通知系統，使用者只能主動登入查看
2. **行動端體驗**：PWA Push 讓手機收到即時通知，不需要開網頁
3. **LINE 是台灣剛需**：直接在 LINE 裡「記帳 午餐 120」比開 App 快 10 倍
4. **雙向互動**：不只推播，還能透過 IM 操作——真正的隨時隨地

---

### 現況分析

| 功能 | V1 狀態 | V2 處置 |
|------|---------|---------|
| PWA Push | 不存在 | 全新建置（VAPID） |
| ntfy | 不存在 | 後備通道 |
| Email 通知 | 不存在 | 未來階段 |
| LINE Bot | 不存在 | 全新建置 |
| Telegram Bot | 不存在 | 全新建置 |
| Discord Bot | 不存在 | 全新建置 |
| 通知偏好 | 不存在 | 全新建置 |
| 通知歷史 | 不存在 | 全新建置 |

---

### 架構設計

#### 兩層分離

```
┌──────────────────────────────────────────────┐
│  EventBus（所有模組事件）                       │
│  finance.transaction.created                  │
│  taskflow.task.completed                      │
│  ideagraph.link.suggested                     │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  第一層：Notification Service                  │
│  core/services/notification/                  │
│  Hot-path service（單向推播）                   │
│                                              │
│  事件過濾 → 偏好檢查 → 聚合 → 格式化 → 派送    │
└──────┬───────┬───────┬───────┬───────────────┘
       │       │       │       │
       ▼       ▼       ▼       ▼
    PWA Push  ntfy   Email  Bridge Adapter
    (VAPID)  (備用)  (SMTP) (LINE/TG/DC)
```

```
┌──────────────────────────────────────────────┐
│  第二層：Bridges                               │
│  bridges/{line,telegram,discord}/              │
│  獨立連接器（雙向通訊）                          │
│                                              │
│  外部訊息 → 正規化 → 指令路由 → Core 模組       │
│  Core 事件 → 格式化 → 推送回平台               │
└──────────────────────────────────────────────┘
```

| 層面 | Notification Service | Bridges |
|------|---------------------|---------|
| **方向** | 單向（Core → 使用者） | 雙向（使用者 ↔ Core） |
| **位置** | `core/services/notification/` | `bridges/` |
| **DB** | 共用 auth schema（偏好+日誌） | 無獨立 schema |
| **複雜度** | 低（格式化+發送） | 高（webhook、session、指令路由） |
| **失敗影響** | 通知延遲 | 外部使用者無法互動 |

---

### 核心設計（參考 OpenClaw）

#### 1. NotificationEnvelope 正規化

所有通知統一為結構化信封：

```python
@dataclass
class NotificationEnvelope:
    event_type: str               # "finance.transaction.created"
    target_user_id: UUID          # 接收者
    title: str                    # 通知標題
    body: str                     # 純文字內文
    body_html: str | None         # HTML 版（email 用）
    url: str | None               # 點擊跳轉 URL
    priority: str = "normal"      # urgent / high / normal / low
    group_key: str | None         # 聚合用（同 key 合併）
    idempotency_key: str          # 防重複
```

#### 2. ChannelAdapter + Capability 宣告

```python
class ChannelCapabilities:
    push: bool          # 能主動推送？
    rich_text: bool     # 支援 HTML/Markdown？
    media: bool         # 支援圖片？
    interactive: bool   # 支援按鈕/選單？（bridges only）
    bidirectional: bool # 能接收回覆？（bridges only）

class ChannelAdapter(ABC):
    channel_id: str
    capabilities: ChannelCapabilities

    async def send(self, envelope: NotificationEnvelope) -> DeliveryResult: ...
```

每個 channel 只需實作 `send()`，其餘能力依 capabilities 宣告自動決定行為。

#### 3. 使用者偏好

存在 `auth.notification_preferences`（JSONB）：

- **全域開關**：enabled + quiet_hours
- **模組級開關**：`{"finance": {"enabled": true, "channels": ["pwa_push", "line"]}}`
- **Channel 綁定**：`{"line": {"user_id": "U1234"}, "pwa_push": {"subscription": {...}}}`

#### 4. 聚合防轟炸

相同 group_key 在 5 秒內合併：
- 10 筆 `finance.transaction.created` → 「你有 10 筆新交易紀錄」
- 5 條 `ideagraph.link.suggested` → 「你有 5 條新建議連結待驗證」

#### 5. 通知歷史

`auth.notification_log` 表記錄每筆派送結果（delivered / failed / aggregated），支援已讀追蹤和 Badge 未讀數。

---

### Bridge 指令路由

使用者在 LINE/Telegram 發送的訊息，依關鍵字路由到對應模組：

| 指令 | 目標 | 範例 |
|------|------|------|
| 記帳 / 花費 | finance.transaction.create | 「記帳 午餐 120」 |
| 餘額 | finance.balance.query | 「餘額」 |
| 任務 / 提醒 | taskflow.task.create | 「任務 買牛奶」 |
| 完成 | taskflow.task.complete | 「完成 買牛奶」 |
| 想法 | ideagraph.spark.capture | 「想法 也許可以用 AI 自動分類」 |
| 搜尋 | intelflow.search.execute | 「搜尋 React 19 新功能」 |

**Inbound 流程**：
```
LINE webhook → MessageEnvelope 正規化 → 指令路由 → Core 模組 → 格式化回覆 → LINE 回傳
```

---

### 技術選型

| 項目 | 方案 |
|------|------|
| **PWA Push** | Web Push API + VAPID（`pywebpush`） |
| **ntfy** | ntfy self-hosted（後備通道） |
| **Email** | SMTP / Resend API（未來） |
| **Firebase** | Firebase Cloud Messaging（行動端，未來） |
| **LINE** | LINE Messaging API（`line-bot-sdk-python`） |
| **Telegram** | Telegram Bot API（`python-telegram-bot`） |
| **Discord** | Discord.py |
| **前端通知 UI** | Notification Center 側邊欄 + Badge |

---

### 前端 UI

#### Notification Center（所有模組共用）

位於 `workbench/src/shared/components/`，非獨立模組：

| 元件 | 功能 |
|------|------|
| `NotificationBell.tsx` | 導覽列鈴鐺 + Badge 未讀數 |
| `NotificationPanel.tsx` | 側邊滑出面板（通知列表） |
| `NotificationItem.tsx` | 單筆通知（圖示+標題+時間+已讀狀態） |
| `NotificationPreferences.tsx` | 設定頁面（模組級+channel 級開關） |

#### 偏好設定頁面

位於 `/settings/notifications`：

- 全域 on/off
- 勿擾時段設定
- 按模組開關（finance ✅ / taskflow ✅ / ideagraph ❌）
- 按 channel 開關（PWA ✅ / LINE ✅ / Email ❌）
- Channel 綁定管理（LINE QR code 掃描、Telegram /start 指令）

---

### API 端點

#### Notification Service

| 方法 | 路徑 | 用途 |
|------|------|------|
| GET | `/api/notifications` | 通知列表（分頁+過濾） |
| GET | `/api/notifications/unread-count` | 未讀數（Badge 用） |
| POST | `/api/notifications/{id}/read` | 標記已讀 |
| POST | `/api/notifications/read-all` | 全部已讀 |
| GET | `/api/notifications/preferences` | 取得偏好 |
| PUT | `/api/notifications/preferences` | 更新偏好 |
| POST | `/api/notifications/preferences/channels/{ch}/bind` | 綁定 channel |
| DELETE | `/api/notifications/preferences/channels/{ch}/unbind` | 解綁 channel |
| POST | `/api/notifications/test` | 發送測試通知 |

#### Bridge Webhooks

| 方法 | 路徑 | 用途 |
|------|------|------|
| POST | `/webhooks/line` | LINE webhook 接收 |
| POST | `/webhooks/telegram` | Telegram webhook 接收 |
| POST | `/webhooks/discord` | Discord interaction endpoint |

---

### 目錄結構

```
core/services/notification/           ← 通知路由服務
├── __init__.py
├── router.py                         # 事件→通知路由
├── envelope.py                       # NotificationEnvelope 定義
├── aggregator.py                     # 聚合防轟炸
├── preferences.py                    # 偏好管理
├── history.py                        # 通知歷史
├── templates/                        # 通知模板
│   ├── finance.py
│   ├── taskflow.py
│   └── ideagraph.py
└── channels/                         # Channel Adapter 實作
    ├── base.py                       # ChannelAdapter ABC
    ├── pwa_push.py                   # Web Push VAPID
    ├── ntfy.py                       # ntfy HTTP API
    └── email.py                      # SMTP/Resend

bridges/                              ← 雙向平台連接器
├── _shared/
│   ├── envelope.py                   # MessageEnvelope 正規化
│   ├── adapter.py                    # BridgeAdapter ABC
│   ├── router.py                     # 指令→模組路由
│   └── commands.py                   # 統一指令定義
├── line/
│   ├── webhook.py
│   ├── adapter.py
│   ├── commands.py
│   └── config.py
├── telegram/
│   ├── webhook.py
│   ├── adapter.py
│   ├── commands.py
│   └── config.py
└── discord/
    ├── bot.py
    ├── adapter.py
    ├── commands.py
    └── config.py

workbench/src/shared/components/notification/  ← 前端 UI
├── NotificationBell.tsx
├── NotificationPanel.tsx
├── NotificationItem.tsx
└── NotificationPreferences.tsx
```

---

### 遷移策略

```
Phase A: Notification Service 骨架 + PWA Push (VAPID)
         + 偏好管理 + 通知歷史 + Notification Center UI
         → 最小可用通知系統

Phase B: + 聚合防轟炸 + 勿擾時段 + ntfy 備用通道
         → 穩健推播體驗

Phase C: + LINE Bridge（webhook + 推播 + 指令路由）
         → 第一個雙向平台

Phase D: + Telegram Bridge + Discord Bridge
         → 多平台覆蓋

Phase E: + Email (SMTP/Resend) + Firebase (行動端)
         → 完整通知矩陣

Phase F: + AI 智慧路由（緊急度→自動選 channel）
         → 智慧通知
```

---

### 事件消費

Notification Service 消費以下模組事件（可在偏好中個別開關）：

| 模組 | 事件 | 預設通知 |
|------|------|---------|
| finance | `transaction.created` | 「新交易：午餐 $120」 |
| finance | `budget.exceeded` | 「⚠️ 餐飲預算已超支 15%」 |
| finance | `subscription.billing_due` | 「Netflix 明天扣款 $390」 |
| taskflow | `task.due_soon` | 「任務「API 文件」明天到期」 |
| taskflow | `task.blocked` | 「任務被阻塞：等待客戶回覆」 |
| taskflow | `report.generated` | 「週報已產生，點擊查看」 |
| ideagraph | `link.suggested` | 「3 條新建議連結待驗證」 |
| ideagraph | `spark.refined` | 「Spark 已精煉完成」 |
| auth | `user.registered` | 「新使用者待審核」（admin only） |

---

### 相關文件

| 文件 | 用途 |
|------|------|
| [v2-priorities.md](./v2-priorities.md) | 藍圖索引 |
| [notification.md](../architecture/notification.md) | 完整架構設計（含 DB schema、介面定義） |
| [domain-catalog.md](../vision/domain-catalog.md) | notification + social-hooks 定義 |
| [communication.md](../architecture/communication.md) | 整體通訊模式 |
| [event-driven.md](../architecture/event-driven.md) | EventBus 規範 |

---

**返回** → [優先藍圖總覽](./v2-priorities.md)
