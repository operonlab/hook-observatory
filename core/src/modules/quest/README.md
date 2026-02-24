# quest — 任務與排程模組

> 統一任務管理、日曆排程、進度追蹤、自動報告產出。

## 定位

| 屬性 | 值 |
|------|-----|
| **Schema** | `quest` |
| **依賴** | auth, dojo（量化模式） |
| **雙向連接** | finance（任務 ↔ 訂單） |
| **MCP** | `workshop-quest`（CRUD ~10 tools）+ `workshop-quest-reports`（報告 ~5 tools） |
| **V1 參考** | `pulso-quest` MCP（10 tools） |

## 核心功能

### 統一任務模型

- 多來源：personal / family / company
- 子任務：parent_id 自引用
- 專案歸屬：可選 project 欄位
- 優先權：urgent / high / medium / low
- 工時追蹤：預估 vs 實際

### 狀態機（6 狀態）

```
[todo] → [in_progress] → [review] → [done]
              ├→ [blocked] (可解除回到 in_progress/review)
              └→ [cancelled]
```

每次狀態變更自動寫入 `task_updates` 紀錄。

### 進度追蹤與回報

- task_updates 表記錄每次更新（type: progress / blocker / note / status_change）
- 每筆更新含 content（回報內容）和 hours_spent（工時）
- 供日誌/週報/月報自動彙整

### 週期性任務

- recurrence JSONB：`{"type": "weekly", "days": [1,3,5]}` 或 `{"type": "monthly", "day": 15}`
- 自動展開到日曆

### 自動報告產出

| 報告 | 頻率 | 觸發 |
|------|------|------|
| 日誌 | 每天 23:00 | cron + 手動 |
| 週報 | 每週日 22:00 | cron + 手動 |
| 月報 | 每月最後一天 | cron + 手動 + LLM 建議 |

## DB Schema

```sql
CREATE SCHEMA quest;

quest.tasks             -- 任務（title, source, status, due_date, priority, recurrence, tags[]）
quest.task_updates      -- 進度紀錄（task_id, type, content, old/new_status, hours_spent）
```

所有資料表含 `space_id` 和 `created_by`。

## API 端點

| 方法 | 路徑 | 用途 |
|------|------|------|
| GET/POST | `/api/quest/tasks` | 任務列表/新增 |
| GET/PUT/DELETE | `/api/quest/tasks/{id}` | 任務詳情/更新/刪除 |
| POST | `/api/quest/tasks/{id}/complete` | 快捷完成 |
| POST | `/api/quest/tasks/{id}/updates` | 新增進度回報 |
| GET | `/api/quest/tasks/{id}/updates` | 該任務的更新歷史 |
| GET | `/api/quest/today` | 今日任務摘要 |
| GET | `/api/quest/upcoming` | 未來 N 天任務 |
| GET | `/api/quest/blocked` | 阻塞項目 |
| GET | `/api/quest/calendar` | 日曆資料（指定月份） |
| GET | `/api/quest/reports/daily/{date}` | 日誌 |
| GET | `/api/quest/reports/weekly/{week}` | 週報 |
| GET | `/api/quest/reports/monthly/{month}` | 月報 |
| GET | `/api/quest/stats` | 完成率、工時統計 |

## 目錄結構

```
core/src/modules/quest/
├── __init__.py
├── routes.py         # 所有 API 端點
├── models.py         # tasks, task_updates
├── schemas.py        # Pydantic request/response
├── services.py       # 公開 API（任務 CRUD、狀態機、進度追蹤）
├── events.py         # quest.task.created, quest.task.completed 等
├── deps.py           # 任務權限驗證
├── state_machine.py  # 狀態轉換規則與驗證
├── reports.py        # 日誌/週報/月報產生邏輯（LLM 整合）
└── scheduler.py      # 週期性任務展開
```

## 跨模組整合

- **finance**：訂閱扣款日顯示在 quest 日曆上（透過 EventBus `finance.subscription.billing_due`）
- **dojo**：量化模式下任務可標註技能需求

## 參考文件

- [P6 藍圖](../../docs/blueprint/p6-quest.md) -- 完整 DB schema + MCP tools + 報告範本
- [服務目錄](../../docs/vision/domain-catalog.md) -- quest 定位
