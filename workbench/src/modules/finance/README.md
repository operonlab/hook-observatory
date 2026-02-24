# finance — 記帳 UI

> 交易管理、分類設定、訂閱管理、預算規劃、消費分析圖表、月度報告。

## 路由

| 路徑 | 頁面 | 說明 |
|------|------|------|
| `/finance` | Dashboard | 當月摘要 + 預算進度 + 最近交易 |
| `/finance/transactions` | TransactionList | 交易列表（過濾、搜尋、分頁） |
| `/finance/transactions/new` | TransactionForm | 新增交易（含拍照上傳） |
| `/finance/categories` | CategoryManager | 樹狀分類管理（拖拽排序） |
| `/finance/subscriptions` | SubscriptionList | 訂閱列表 + 日曆 |
| `/finance/budget` | BudgetPlanner | 月度預算設定 + 進度追蹤 |
| `/finance/analytics` | Analytics | 圓餅圖 / 柱狀圖 / 散佈圖 / 趨勢線 |
| `/finance/reports/:month` | MonthlyReport | 月度消費報告（AI 建議） |

## 元件

```
workbench/src/modules/finance/
├── pages/
│   ├── Dashboard.tsx
│   ├── TransactionList.tsx
│   ├── TransactionForm.tsx
│   ├── CategoryManager.tsx
│   ├── SubscriptionList.tsx
│   ├── BudgetPlanner.tsx
│   ├── Analytics.tsx
│   └── MonthlyReport.tsx
├── components/
│   ├── TransactionRow.tsx       # 單筆交易（含標籤、分類 badge）
│   ├── CategoryTree.tsx         # 樹狀分類選擇器
│   ├── PhotoUploader.tsx        # 多張照片上傳（拍照 / 選檔）
│   ├── BudgetProgressBar.tsx    # 預算消耗進度條
│   ├── SubscriptionCalendar.tsx # 訂閱扣款日曆
│   └── charts/
│       ├── PieChart.tsx         # 分類圓餅圖
│       ├── BarChart.tsx         # 月度柱狀圖
│       ├── ScatterPlot.tsx      # 消費散佈圖
│       └── TrendLine.tsx        # 趨勢線
├── hooks/
│   ├── useTransactions.ts
│   ├── useCategories.ts
│   └── useBudget.ts
├── stores/
│   └── financeStore.ts          # Zustand
├── api/
│   └── financeApi.ts
└── index.tsx
```

## 圖表技術

使用 **Recharts**（React 原生）或 **ECharts**（功能更豐富），視實作複雜度決定。

## 參考

- [Finance 後端模組](../../../core/src/modules/finance/README.md)
- [P5 藍圖](../../../docs/blueprint/p5-finance.md)
