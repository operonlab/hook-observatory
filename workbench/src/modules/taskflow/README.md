# taskflow — 任務與日曆 UI

> 任務管理、日曆檢視、進度追蹤、報告瀏覽。

## 路由

| 路徑 | 頁面 | 說明 |
|------|------|------|
| `/taskflow` | Dashboard | 今日任務 + 即將到期 + 阻塞項 |
| `/taskflow/tasks` | TaskList | 任務列表（過濾：狀態/來源/專案/標籤） |
| `/taskflow/tasks/new` | TaskForm | 新增任務（含子任務、排程、標籤） |
| `/taskflow/tasks/:id` | TaskDetail | 任務詳情 + 進度回報歷史 |
| `/taskflow/calendar` | CalendarView | 月/週/日/議程 四種檢視 |
| `/taskflow/reports` | ReportList | 日誌/週報/月報列表 |
| `/taskflow/reports/:type/:date` | ReportDetail | 報告詳情 |
| `/taskflow/stats` | Statistics | 完成率趨勢、工時分佈 |

## 元件

```
workbench/src/modules/taskflow/
├── pages/
│   ├── Dashboard.tsx
│   ├── TaskList.tsx
│   ├── TaskForm.tsx
│   ├── TaskDetail.tsx
│   ├── CalendarView.tsx
│   ├── ReportList.tsx
│   ├── ReportDetail.tsx
│   └── Statistics.tsx
├── components/
│   ├── TaskRow.tsx              # 單筆任務（狀態 badge + 來源標籤）
│   ├── TaskStatusBadge.tsx      # 6 狀態彩色 badge
│   ├── TaskUpdateForm.tsx       # 進度回報表單
│   ├── TaskUpdateTimeline.tsx   # 更新歷史時間軸
│   ├── SubtaskList.tsx          # 子任務折疊列表
│   ├── RecurrenceEditor.tsx     # 週期性設定 UI
│   └── calendar/
│       ├── MonthView.tsx
│       ├── WeekView.tsx
│       ├── DayView.tsx
│       └── AgendaView.tsx
├── hooks/
│   ├── useTasks.ts
│   ├── useCalendar.ts
│   └── useReports.ts
├── stores/
│   └── taskflowStore.ts         # Zustand
├── api/
│   └── taskflowApi.ts
└── index.tsx
```

## 日曆技術

使用 **FullCalendar**（React wrapper）或 **react-big-calendar**，視實作體驗決定。

## 參考

- [Taskflow 後端模組](../../../core/src/modules/taskflow/README.md)
- [P6 藍圖](../../../docs/blueprint/p6-taskflow.md)
