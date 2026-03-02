---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

> [← 返回優先藍圖總覽](./v2-priorities.md)

# P6：Taskflow 排程與任務管理 — 日曆 + 追蹤 + 報告

### 現況分析

V1 Quest MCP Server（`workshop-quest`）已有 10 個 tools：

| Tool | 功能 |
|------|------|
| `quest_board` | 任務看板總覽 |
| `quest_create` | 建立新任務 |
| `quest_update` | 更新任務內容 |
| `quest_accept` | 接受任務 |
| `quest_complete` | 完成任務 |
| `quest_fail` | 標記任務失敗 |
| `quest_list` | 列出任務（可過濾） |
| `quest_status` | 查詢任務狀態 |
| `quest_allocate` | 分配任務 |
| `quest_skill_tree` | 技能樹查詢 |

**V1 的好東西**：MCP 介面成熟、RPG 隱喻設計（裝備=知識、技能=職能、屬性=核心特徵）、技能樹系統。
**V1 缺什麼**：無日曆檢視、無進度追蹤回報機制、無自動報告產出、無多來源（家庭/公司/個人）分類、無週期性任務。

### 概述

整合日曆功能與個人任務管理，支援多來源任務（家庭、公司、個人），追蹤進度與回報情況，並自動產出日誌、週報、月報。

### V2 目標

#### 1. 統一任務模型

```sql
CREATE TABLE taskflow.tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id        UUID NOT NULL,
    parent_id       UUID REFERENCES taskflow.tasks(id),    -- 子任務
    title           TEXT NOT NULL,
    description     TEXT,

    -- 來源與分類
    source          TEXT NOT NULL,              -- 'personal', 'family', 'company'
    project         TEXT,                       -- 歸屬專案名稱（可選）

    -- 狀態機
    status          TEXT NOT NULL DEFAULT 'todo',
    -- 'todo' → 'in_progress' → 'review' → 'done'
    --                        → 'blocked'
    --                        → 'cancelled'

    -- 排程
    due_date        TIMESTAMPTZ,               -- 截止日
    start_date      TIMESTAMPTZ,               -- 預計開始日
    completed_at    TIMESTAMPTZ,               -- 實際完成時間

    -- 優先權與工作量
    priority        TEXT DEFAULT 'medium',      -- 'urgent', 'high', 'medium', 'low'
    estimated_hours FLOAT,                     -- 預估工時
    actual_hours    FLOAT,                     -- 實際工時

    -- 週期性
    recurrence      JSONB,                     -- NULL = 一次性
    -- { "type": "weekly", "days": [1,3,5], "end_date": "2026-12-31" }
    -- { "type": "monthly", "day": 15 }

    -- Meta
    tags            TEXT[],
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    created_by      UUID REFERENCES auth.users(id)
);
```

**狀態機**：
```
          ┌──────────────────────────┐
          │                          │
[todo] ──► [in_progress] ──► [review] ──► [done]
              │                  │
              ├──► [blocked]     │
              │       │          │
              │       └──────────┘ (解除 → 回到 review 或 in_progress)
              │
              └──► [cancelled]
```

#### 2. 進度追蹤與回報

```sql
CREATE TABLE taskflow.task_updates (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    task_id     UUID NOT NULL REFERENCES taskflow.tasks(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,              -- 'progress', 'blocker', 'note', 'status_change'
    content     TEXT NOT NULL,              -- 回報內容
    old_status  TEXT,                       -- 狀態變更前
    new_status  TEXT,                       -- 狀態變更後
    hours_spent FLOAT,                     -- 本次花費工時
    created_at  TIMESTAMPTZ DEFAULT now(),
    created_by  UUID REFERENCES auth.users(id)
);
```

**用途**：每次更新任務都留下紀錄，供日誌/週報/月報彙整。

#### 3. 日曆檢視（Calendar View）

| 檢視模式 | 顯示內容 |
|---------|---------|
| **月檢視** | 每天的任務數量 + 圓點標示，點擊展開 |
| **週檢視** | 時間軸橫向，任務以色塊呈現（Gantt-like） |
| **日檢視** | 當天所有任務詳情 + 時間排程 |
| **議程檢視** | 近 7 天任務列表（按時間排序） |

**整合**：
- Finance 訂閱扣款日 → 日曆上顯示（跨模組 event）
- 週期性任務 → 自動展開到日曆

**技術選擇**：前端使用 **FullCalendar**（React wrapper）或 **react-big-calendar**。

#### 4. 自動報告產出

**日誌（Daily Log）**：
```
📋 2026-02-24 日誌
─────────────────

✅ 已完成 (3)
  - [公司] 完成 API 文件更新
  - [個人] 整理 workshop docs
  - [家庭] 繳電費

🔄 進行中 (2)
  - [公司] 前端 UI 重構（進度 60%）
  - [個人] Finance 模組設計

⏳ 明日預計
  - [公司] Code review + 部署
  - [個人] Auth 模組實作
```

**週報（Weekly Report）**：
```
📊 2026-02-17 ~ 02-23 週報
──────────────────────────

📈 數據摘要
  完成：12 項 | 新增：8 項 | 阻塞：1 項
  總工時：32h | 平均每日：4.6h
  完成率：85%

📂 按來源
  公司：5 完成 / 2 進行中
  個人：4 完成 / 3 進行中
  家庭：3 完成

🚧 阻塞項目
  - [公司] 等待客戶確認設計稿（已阻塞 3 天）

💡 觀察
  - 本週公司任務集中在週一到三，建議均勻分配
  - 個人專案進度超前，可考慮提前進入下階段
```

**月報（Monthly Report）**：
```
📊 2026 年 2 月月報
──────────────────

📈 總覽
  完成：48 項 | 完成率：87%
  總工時：128h
  按來源：公司 45% | 個人 35% | 家庭 20%

📊 趨勢
  vs 上月：完成數 +12%、工時 -5%（效率提升）

🏆 里程碑
  - Workshop V2 文件架構完成
  - Finance 模組上線
  - tmux-webui 手機體驗升級

📋 下月重點
  - Auth 模組完成
  - Intelflow 遷移啟動
```

**產生方式**：
- **日誌**：每天 23:00 自動產生（彙整當天 task_updates）
- **週報**：每週日 22:00 自動產生
- **月報**：每月最後一天自動產生 + LLM 產生觀察與建議
- **手動觸發**：UI 按鈕或 MCP tool

#### 5. MCP Server 設計

Taskflow 預估 12-15 個 tools，拆成 2 個 MCP Server：

**`workshop-taskflow`**（核心 CRUD + 排程，~10 tools）：
| Tool | 功能 |
|------|------|
| `taskflow_create` | 建立任務（含子任務、標籤、排程） |
| `taskflow_update` | 更新任務（含狀態變更） |
| `taskflow_list` | 列出任務（過濾：狀態/來源/專案/日期/標籤） |
| `taskflow_complete` | 標記完成（快捷操作） |
| `taskflow_add_update` | 新增進度回報 |
| `taskflow_list_blocked` | 列出阻塞項目 |
| `taskflow_today` | 今日任務摘要 |
| `taskflow_upcoming` | 未來 N 天任務 |
| `taskflow_set_recurrence` | 設定週期性排程 |
| `taskflow_bulk_update` | 批次更新狀態 |

**`workshop-taskflow-reports`**（報告 + 分析，~5 tools）：
| Tool | 功能 |
|------|------|
| `taskflow_daily_log` | 產生/查閱日誌 |
| `taskflow_weekly_report` | 產生/查閱週報 |
| `taskflow_monthly_report` | 產生/查閱月報 |
| `taskflow_stats` | 任務統計（完成率、工時分佈、趨勢） |
| `taskflow_export` | 匯出報告（Markdown / PDF） |

### 技術架構

```
workbench/src/modules/taskflow/      ← Taskflow UI（任務列表、日曆、看板、報告）
core/src/modules/taskflow/           ← Taskflow 後端（API + DB + 排程引擎 + 報告產生）
mcp/taskflow/                        ← workshop-taskflow MCP（核心 CRUD + 排程）
mcp/taskflow-reports/                ← workshop-taskflow-reports MCP（報告 + 分析）
```

### 遷移策略

1. **Phase A**：建立 taskflow schema（tasks + task_updates）+ 基本 CRUD API
2. **Phase B**：狀態機 + 進度追蹤 + 回報功能
3. **Phase C**：日曆 UI + 週期性任務
4. **Phase D**：自動報告產出（日誌 → 週報 → 月報）
5. **Phase E**：MCP Server（2 個） + 與 Finance 的跨模組 event 整合（`taskflow.task.completed`）

### 相關文件

| 文件 | 用途 |
|------|------|
| [v2-priorities.md](./v2-priorities.md) | 藍圖索引 |
| [shared-layer-patterns.md](../architecture/shared-layer-patterns.md) | 共享層模式（TreeStructure §5.3、Tags §5.4、JSONB §5.5、StateMachine §3.4、LLMService §8.2、BulkOps §8.6、ScheduledReport §8.4、ExportService §8.5、CalendarView §9.2、ChartKit §9.4、ReportViewer §9.3） |

---

**返回** → [優先藍圖總覽](./v2-priorities.md)
