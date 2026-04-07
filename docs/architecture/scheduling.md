---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

# 系統排程管理 (System Scheduling)

> 統一管理 Workshop 所有服務的排程策略 — 開機自起、離線自救、定時任務。

---

## 設計理念

Workshop 是個人工作站，運行在 macOS 單機上。排程策略的設計原則：

1. **開機即就緒** — 機器重啟後，核心基礎設施自動啟動，無需人工介入
2. **離線自救** — 服務崩潰時自動重啟，不需要 24/7 監控
3. **定時排程** — 週期性報告、健康檢查、資料維護按時執行
4. **統一管理** — 所有排程集中可查、可控，不散落在各服務內部

---

## 三層排程架構

```
┌────────────────────────────────────────────────────────────┐
│  Layer 1: macOS launchd（系統級）                           │
│  開機自起 + 崩潰重啟 + 定時觸發                              │
│                                                            │
│  ~/Library/LaunchAgents/com.workshop.*.plist                │
└──────────────┬─────────────────────────────────────────────┘
               │
┌──────────────▼─────────────────────────────────────────────┐
│  Layer 2: Docker restart policy（容器級）                    │
│  基礎設施服務（PostgreSQL、Redis、LGTM、RustFS）              │
│                                                            │
│  restart: unless-stopped                                   │
└──────────────┬─────────────────────────────────────────────┘
               │
┌──────────────▼─────────────────────────────────────────────┐
│  Layer 3: Application-level scheduling（應用級）             │
│  asyncio 定時迴圈、EventBus 觸發                             │
│                                                            │
│  sentinel: light/deep check intervals                      │
│  notification: aggregation buffer window                   │
└────────────────────────────────────────────────────────────┘
```

---

## Layer 1: macOS launchd

### 為什麼選 launchd

| 方案 | 優劣 |
|------|------|
| **launchd** ✅ | macOS 原生、開機自起、崩潰重啟、日曆觸發 |
| cron | 無崩潰重啟、無 macOS 整合、已被 Apple 棄用 |
| systemd | Linux only |
| PM2/Supervisor | 額外依賴、與 macOS 生態不一致 |

### plist 命名規範

```
com.workshop.{service-name}[-{variant}].plist
```

| plist | 服務 | 類型 |
|-------|------|------|
| `com.workshop.core.plist` | Core Monolith (port 10000) | 常駐服務 |
| `com.workshop.sentinel.plist` | Sentinel (port 4101) | 常駐服務 |
| `com.workshop.system-monitor-weekly.plist` | 週報生成 | 定時任務 |
| `com.workshop.system-monitor-monthly.plist` | 月報生成 | 定時任務 |

### 常駐服務 plist 模板

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.workshop.core</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/joneshong/.local/bin/python3</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>src.app:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>10000</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/joneshong/workshop/core</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>/Users/joneshong/.claude/data/logs/core-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/joneshong/.claude/data/logs/core-stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

**關鍵設定**：
- `RunAtLoad: true` — 開機/登入時自動啟動
- `KeepAlive.SuccessfulExit: false` — 非正常退出時自動重啟
- `ThrottleInterval: 10` — 崩潰重啟間隔至少 10 秒（防止 crash loop）

### 定時任務 plist 模板

```xml
<!-- com.workshop.system-monitor-weekly.plist -->
<dict>
    <key>Label</key>
    <string>com.workshop.system-monitor-weekly</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/joneshong/.local/bin/python3</string>
        <string>/Users/joneshong/workshop/stations/system-monitor/__main__.py</string>
        <string>report</string>
        <string>--type=weekly</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>5</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</dict>
```

### launchd 管理指令

```bash
# 安裝（載入 plist）
launchctl load ~/Library/LaunchAgents/com.workshop.core.plist

# 卸載
launchctl unload ~/Library/LaunchAgents/com.workshop.core.plist

# 查看狀態
launchctl list | grep com.workshop

# 立即啟動
launchctl start com.workshop.core

# 立即停止
launchctl stop com.workshop.core
```

### 程式化管理

`stations/system-monitor/scheduler.py` 提供了 launchd plist 的程式化管理：

```python
from scheduler import Scheduler

scheduler = Scheduler()
scheduler.install()       # 產生 plist + launchctl load
scheduler.uninstall()     # launchctl unload + 刪除 plist
scheduler.status()        # 查詢所有排程狀態
scheduler.run_now("weekly")  # 立即執行
```

---

## Layer 2: Docker restart policy

基礎設施服務透過 Docker Compose 管理（`infra/docker/docker-compose.yml`）：

| 服務 | 映像 | restart 策略 | 健康檢查 |
|------|------|-------------|---------|
| PostgreSQL | postgres:16 | `unless-stopped` | `pg_isready` 每 10 秒 |
| Redis | redis:7-alpine | `unless-stopped` | `redis-cli ping` 每 10 秒 |
| LGTM | grafana/otel-lgtm | `unless-stopped` | — |
| RustFS | zotio/rustfs | `unless-stopped` | — |

**`unless-stopped` 策略**：
- 容器崩潰 → 自動重啟
- 手動停止 → 不重啟
- Docker daemon 重啟（開機） → 自動啟動

### Docker daemon 開機自起

macOS 上 Docker Desktop 預設開機啟動。確認設定：
- Docker Desktop → Settings → General → "Start Docker Desktop when you sign in to your computer"

---

## Layer 3: Application-level scheduling

### Sentinel — asyncio 定時迴圈

Sentinel 使用 asyncio 定時迴圈執行兩種健康檢查：

```python
# stations/sentinel/config.py
class CheckConfig:
    light_interval: float = 30.0    # 輕量檢查：每 30 秒
    deep_interval: float = 300.0    # 深度檢查：每 5 分鐘
```

```python
# stations/sentinel/main.py
async def _light_check_loop(config):
    await asyncio.sleep(5)  # 啟動延遲
    while True:
        await run_light_checks()
        await asyncio.sleep(config.check.light_interval)

async def _deep_check_loop(config):
    await asyncio.sleep(10)
    while True:
        await run_deep_checks()
        await asyncio.sleep(config.check.deep_interval)
```

### Notification — 聚合緩衝

通知模組使用短時間窗口防止事件轟炸（詳見 [notification.md](./notification.md)）：

```python
class NotificationAggregator:
    buffer_window: int = 5     # 5 秒內同類事件合併
    max_batch_size: int = 50   # 超過 50 筆直接切斷
```

### EventBus — 事件觸發排程

部分排程由事件驅動而非固定時間：

```python
@event_bus.on("finance.transaction.created")
async def check_budget_threshold(event):
    # 交易建立時觸發預算檢查
    ...

@event_bus.on("system.startup")
async def initialize_schedules(event):
    # 系統啟動時初始化所有排程
    ...
```

---

## 完整排程矩陣

### 常駐服務（必須持續運行）

| 服務 | 管理方式 | 埠位 | 自動重啟 | 開機自起 |
|------|---------|------|---------|---------|
| PostgreSQL | Docker (`unless-stopped`) | 5432 | ✅ | ✅ |
| Redis | Docker (`unless-stopped`) | 6379 | ✅ | ✅ |
| LGTM | Docker (`unless-stopped`) | 3000/4317/4318 | ✅ | ✅ |
| Core Monolith | launchd (`KeepAlive`) | 10000 | ✅ | ✅ |
| Sentinel | launchd (`KeepAlive`) | 4101 | ✅ | ✅ |
| Agent Metrics | launchd (`KeepAlive`) | 8795 | ✅ | ✅ |
| Nginx | launchd (系統自帶) | 80/443 | ✅ | ✅ |

### 定時任務（週期性執行）

| 任務 | 觸發方式 | 頻率 | 說明 |
|------|---------|------|------|
| 系統週報 | launchd `StartCalendarInterval` | 每週一 05:00 | system-monitor 週報 |
| 系統月報 | launchd `StartCalendarInterval` | 每月 1 日 05:00 | system-monitor 月報 |
| 輕量健康檢查 | asyncio loop | 每 30 秒 | sentinel 基本存活檢查 |
| 深度健康檢查 | asyncio loop | 每 5 分鐘 | sentinel 服務品質檢查 |
| 通知聚合 | 事件觸發 + buffer | 5 秒窗口 | notification 防轟炸 |

### 事件驅動任務（按需執行）

| 任務 | 觸發事件 | 說明 |
|------|---------|------|
| 預算警告 | `finance.transaction.created` | 交易超過預算閾值時通知 |
| 任務成就 | `taskflow.task.completed` | 完成任務時檢查獎勵 |
| 排程初始化 | `system.startup` | 系統啟動時載入所有排程 |

---

## 離線自救策略

### 故障恢復流程

```
服務崩潰
    │
    ▼
launchd / Docker 偵測到退出
    │
    ├── 正常退出 (exit 0) → 不重啟
    │
    └── 異常退出 (exit ≠ 0)
        │
        ▼
    等待 ThrottleInterval (10 秒)
        │
        ▼
    自動重啟
        │
        ├── 重啟成功 → 恢復正常
        │
        └── 持續崩潰 (crash loop)
            │
            ▼
        launchd 限流（越來越慢）
            │
            ▼
        Sentinel 偵測到 degraded
            │
            ▼
        通知使用者（ntfy / PWA push）
```

### 依賴啟動順序

```
1. Docker daemon 啟動 (macOS login)
    │
    ├─► PostgreSQL (healthcheck: pg_isready)
    ├─► Redis (healthcheck: redis-cli ping)
    └─► LGTM (no dependency)

2. launchd 啟動 Workshop 服務
    │
    ├─► Core Monolith (depends: PostgreSQL, Redis)
    │       └─► 啟動失敗 → KeepAlive 重試（等待 DB 就緒）
    │
    ├─► Sentinel (depends: Core — optional)
    │       └─► 獨立運行，Core 不可用時降級檢查
    │
    └─► Agent Metrics (depends: PostgreSQL)
            └─► 啟動失敗 → KeepAlive 重試
```

**注意**：launchd 本身不支援 service dependency。透過 `KeepAlive` + `ThrottleInterval` 實現「等待依賴就緒」的效果 — 服務啟動失敗後等待 10 秒重試，直到依賴服務可用。

---

## 管理工具

### system-monitor CLI

```bash
# 安裝所有定時排程
python3 stations/system-monitor/scheduler.py install

# 卸載所有定時排程
python3 stations/system-monitor/scheduler.py uninstall

# 查看排程狀態
python3 stations/system-monitor/scheduler.py status

# 立即執行週報
python3 stations/system-monitor/scheduler.py run --type weekly
```

### 統一排程查詢

```bash
# 查看所有 Workshop 相關的 launchd 排程
launchctl list | grep com.workshop

# 查看所有 Docker 服務狀態
docker compose -p ws-infra ps

# Sentinel 健康儀表板
curl http://localhost:4101/api/health
```

---

## 增長路徑

```
現階段: launchd (常駐 + 定時) + Docker (基礎設施) + asyncio (應用級)
         → 足以支撐個人工作站需求

未來 Phase 2: + 統一排程管理 CLI
         → 一個指令查看/管理所有排程

未來 Phase 3: + 排程視覺化 Dashboard
         → system-monitor 前端顯示排程矩陣與執行歷史

未來 Phase 4: + 事件觸發排程引擎 (nodeflow)
         → 複雜的 DAG 排程（依賴、條件、重試）
```

---

## 相關文件

| 文件 | 用途 |
|------|------|
| [modular-monolith.md](./modular-monolith.md) | 服務架構與埠位分配 |
| [notification.md](./notification.md) | 通知聚合的排程策略 |
| [event-driven.md](./event-driven.md) | 事件觸發排程 |
| [observability.md](./observability.md) | 監控與告警 |
| [../reference/sandbox-executor.md](../reference/sandbox-executor.md) | Sandbox 執行模型 |
