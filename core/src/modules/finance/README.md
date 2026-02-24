# finance — 會計與財務模組

> 個人/家庭記帳、訂閱管理、預算規劃、消費分析。

## 定位

| 屬性 | 值 |
|------|-----|
| **Schema** | `finance` |
| **依賴** | auth |
| **MCP** | `workshop-finance`（CRUD ~10 tools）+ `workshop-finance-analytics`（分析 ~8 tools） |
| **V1 參考** | `pulso-finance` MCP（10 tools，port 8793） |

## 核心功能

### 一次性交易（Transaction）

- 收入/支出記錄
- 付款方式：現金、信用卡、簽帳卡、電子支付、銀行轉帳
- 具體卡片/帳戶名稱（如「中信 LINE Pay」、「玉山 Debit」）
- 複數自訂標籤（多對多）
- 複數照片附件（RustFS 存檔，DB 記 storage_key）

### 樹狀分類系統（Category Tree）

- parent_id 自引用，支援無限層級
- 使用者可自訂新增/編輯/移動/停用
- 預設範本：飲食（早/午/晚/飲料/零食）、交通、居住、娛樂…

### 週期性訂閱（Subscription）

- 週期：monthly / yearly / weekly
- 狀態：active / paused / cancelled
- 自動記帳：到期日自動產生 transaction（event trigger）

### 預算功能（Budget）

- 總預算：月預計花費 + 儲蓄目標
- 分類預算：各分類上限金額
- 即時比對：當月支出 vs 預算，超支警示

### 消費分析

- 圓餅圖：當月分類佔比
- 柱狀圖：月度收支對比
- 散佈圖：消費金額 × 時間分佈
- 趨勢線：各分類月度變化
- 預算進度：消耗百分比

### 月度消費報告

- 自動產生：每月 1 號 cron
- LLM 產生 AI 建議（消費習慣觀察、超支提醒、訂閱檢視）

## DB Schema

```sql
CREATE SCHEMA finance;

finance.transactions            -- 交易（amount, payment_method, payment_detail, category_id, transacted_at）
finance.transaction_tags        -- 標籤（transaction_id, tag）多對多
finance.transaction_attachments -- 照片附件（storage_key → RustFS）
finance.categories              -- 樹狀分類（parent_id 自引用）
finance.subscriptions           -- 訂閱（billing_cycle, next_billing, status）
finance.budgets                 -- 預算（year_month, category_id, budget_amount, savings_target）
```

所有資料表含 `space_id`（Space-Based Sharing）和 `created_by`。

## API 端點

| 方法 | 路徑 | 用途 |
|------|------|------|
| GET/POST | `/api/finance/transactions` | 交易列表/新增 |
| GET/PUT/DELETE | `/api/finance/transactions/{id}` | 交易詳情/更新/刪除 |
| POST | `/api/finance/transactions/{id}/attachments` | 上傳照片 |
| GET/POST | `/api/finance/categories` | 分類列表/新增 |
| PUT | `/api/finance/categories/{id}` | 更新分類（含移動） |
| GET/POST | `/api/finance/subscriptions` | 訂閱列表/新增 |
| PUT | `/api/finance/subscriptions/{id}` | 更新訂閱（含暫停/取消） |
| GET/POST | `/api/finance/budgets` | 預算查詢/設定 |
| GET | `/api/finance/summary` | 月度收支摘要 |
| GET | `/api/finance/insights` | 多月消費趨勢 |
| GET | `/api/finance/reports/{year_month}` | 月度消費報告 |

## 目錄結構

```
core/src/modules/finance/
├── __init__.py
├── routes.py         # 所有 API 端點
├── models.py         # transactions, categories, subscriptions, budgets, attachments, tags
├── schemas.py        # Pydantic request/response
├── services.py       # 公開 API（交易 CRUD、分類管理、預算邏輯、分析計算）
├── events.py         # finance.transaction.created, finance.budget.exceeded 等
├── deps.py           # 交易權限驗證
├── storage.py        # RustFS 上傳/下載（S3 compatible）
└── reports.py        # 月度報告產生（LLM 整合）
```

## 參考文件

- [P5 藍圖](../../docs/blueprint/p5-finance.md) — 完整 DB schema + MCP tools 設計
- [服務目錄](../../docs/vision/domain-catalog.md) — finance 定位
