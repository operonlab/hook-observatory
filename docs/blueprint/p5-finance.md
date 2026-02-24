---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

> [← 返回優先藍圖總覽](./v2-priorities.md)

# P5：Finance 記帳系統 — 完整個人財務管理

### 現況分析

V1 Finance MCP Server（`pulso-finance`）已有 10 個 tools：

| Tool | 功能 |
|------|------|
| `finance_summary` | 月度收支摘要（含分類明細） |
| `finance_list_transactions` | 列出交易（過濾：月份/類型/分類/付款方式/標籤/全文搜尋） |
| `finance_add_transaction` | 新增交易 |
| `finance_update_transaction` | 更新交易 |
| `finance_delete_transaction` | 刪除交易 |
| `finance_list_subscriptions` | 列出訂閱 |
| `finance_add_subscription` | 新增訂閱 |
| `finance_update_subscription` | 更新訂閱 |
| `finance_insights` | 多月消費趨勢 |
| `finance_suggest` | 欄位自動補全 |

**V1 的好東西**：MCP 介面設計成熟、基本 CRUD 完整。
**V1 缺什麼**：無照片附件、無樹狀分類、無預算功能、無視覺化圖表、無月度報告。

### V2 目標

將 Finance 從 MCP-only 工具升級為完整的個人財務管理系統，含 Web UI + 分析圖表 + 預算規劃。

#### 1. 一次性交易（Transaction）

```sql
CREATE TABLE finance.transactions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id        UUID NOT NULL,
    type            TEXT NOT NULL,              -- 'income' / 'expense'
    amount          DECIMAL(12,2) NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'TWD',
    description     TEXT,
    merchant        TEXT,                       -- 商家名稱

    -- 付款方式
    payment_method  TEXT NOT NULL,              -- 'cash', 'credit_card', 'debit_card',
                                               -- 'e_payment', 'bank_transfer'
    payment_detail  TEXT,                       -- 具體卡片/帳戶名稱
                                               -- e.g. '中信 LINE Pay', '玉山 Debit', 'Apple Pay'

    -- 分類系統（樹狀）
    category_id     UUID REFERENCES finance.categories(id),

    -- 時間
    transacted_at   TIMESTAMPTZ NOT NULL,       -- 實際消費時間
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    created_by      UUID REFERENCES auth.users(id)
);

-- 複數自訂標籤
CREATE TABLE finance.transaction_tags (
    transaction_id  UUID REFERENCES finance.transactions(id) ON DELETE CASCADE,
    tag             TEXT NOT NULL,
    PRIMARY KEY (transaction_id, tag)
);

-- 複數照片附件（存 RustFS，DB 記關聯）
CREATE TABLE finance.transaction_attachments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    transaction_id  UUID REFERENCES finance.transactions(id) ON DELETE CASCADE,
    storage_key     TEXT NOT NULL,              -- RustFS object key (S3 path)
    filename        TEXT NOT NULL,              -- 原始檔名
    content_type    TEXT NOT NULL,              -- MIME type
    size_bytes      BIGINT,
    uploaded_at     TIMESTAMPTZ DEFAULT now()
);
```

**照片流程**：
```
手機拍照 → 上傳 /api/finance/transactions/{id}/attachments
  → Core API → RustFS (S3 PUT)
  → 回傳 storage_key → 寫入 finance.transaction_attachments
  → UI 顯示縮圖（RustFS presigned URL）
```

#### 2. 樹狀分類系統（Category Tree）

```sql
CREATE TABLE finance.categories (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id    UUID NOT NULL,
    parent_id   UUID REFERENCES finance.categories(id),  -- NULL = 頂層
    name        TEXT NOT NULL,
    icon        TEXT,                                     -- emoji or icon name
    color       TEXT,                                     -- hex color
    sort_order  INT DEFAULT 0,
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now()
);
```

**預設樹狀結構範例**：
```
飲食
├── 早餐
├── 午餐
├── 晚餐
├── 飲料
└── 零食
交通
├── 大眾運輸
├── 計程車
├── 油費
└── 停車費
居住
├── 房租
├── 水電
├── 網路
└── 管理費
娛樂
├── 遊戲
├── 串流訂閱
├── 書籍
└── 旅遊
```

使用者可自由新增/編輯/移動分類節點。

#### 3. 週期性訂閱（Subscription）

```sql
CREATE TABLE finance.subscriptions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id        UUID NOT NULL,
    name            TEXT NOT NULL,              -- e.g. 'Netflix', 'Claude Pro'
    amount          DECIMAL(12,2) NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'TWD',
    billing_cycle   TEXT NOT NULL,              -- 'monthly', 'yearly', 'weekly'
    billing_day     INT,                        -- 每月幾號扣款（1-31）
    category_id     UUID REFERENCES finance.categories(id),
    payment_method  TEXT,
    payment_detail  TEXT,
    start_date      DATE NOT NULL,
    end_date        DATE,                       -- NULL = 持續中
    status          TEXT DEFAULT 'active',      -- 'active', 'paused', 'cancelled'
    next_billing    DATE,                       -- 下次扣款日（自動計算）
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    created_by      UUID REFERENCES auth.users(id)
);
```

**自動記帳**：訂閱到期日 → 自動產生 transaction 記錄（cron job 或 event trigger）。

#### 4. 預算功能（Budget）

```sql
CREATE TABLE finance.budgets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id        UUID NOT NULL,
    year_month      TEXT NOT NULL,              -- '2026-02'
    category_id     UUID REFERENCES finance.categories(id),  -- NULL = 總預算
    budget_amount   DECIMAL(12,2) NOT NULL,     -- 預算金額
    savings_target  DECIMAL(12,2),              -- 儲蓄目標（僅總預算有）
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(space_id, year_month, category_id)
);
```

**預算邏輯**：
- **總預算**：這個月預計花多少、存多少
- **分類預算**：飲食上限 8000、娛樂上限 3000…
- **即時比對**：當月實際支出 vs 預算，超支即警示
- **剩餘分配**：月初設定 → 隨消費遞減 → 剩餘可用金額

#### 5. 消費分析圖表（Web UI）

| 圖表類型 | 用途 | 資料來源 |
|---------|------|---------|
| **圓餅圖** | 當月支出分類佔比 | `transactions` GROUP BY `category` |
| **柱狀圖** | 月度收支對比（近 6/12 個月） | `transactions` GROUP BY `month` |
| **散佈圖** | 消費金額 × 時間分佈（找出消費模式） | `transactions` 的 `amount` × `transacted_at` |
| **趨勢線** | 各分類月度變化趨勢 | `transactions` GROUP BY `category, month` |
| **預算進度** | 各分類預算消耗百分比 | `budgets` vs `transactions` |
| **訂閱日曆** | 每月訂閱扣款時間軸 | `subscriptions` 的 `next_billing` |

**技術選擇**：前端使用 **Recharts**（React 生態，支援響應式）或 **ECharts**（功能更豐富）。

#### 6. 月度消費報告

每月自動產生（月底 or 下月 1 號觸發）：

```
📊 2026 年 2 月消費報告
─────────────────────

💰 收支摘要
  收入：$85,000
  支出：$52,300（預算 $60,000，節省 $7,700 ✅）
  儲蓄：$32,700（目標 $25,000，超額達標 ✅）

📈 分類分析
  飲食  $12,500 / $15,000（83%）
  交通  $3,200 / $5,000（64%）
  娛樂  $8,900 / $8,000（111% ⚠️ 超支）
  居住  $18,000 / $18,000（100%）

💡 AI 建議
  1. 娛樂類超支 $900，主要來自 2/14 的旅遊消費，建議下月調高預算或分攤
  2. 飲料消費佔飲食的 28%（$3,500），較上月增加 15%
  3. 訂閱類月支出 $4,200，建議檢視 3 個超過半年未使用的訂閱
```

**產生方式**：
- 自動觸發：每月 1 號 cron job → 彙整上月資料 → LLM 產生建議 → 寫入 DB
- 手動觸發：UI 上按鈕或 MCP tool

#### 7. MCP Server 設計

根據 AD-2 切分規則（超過 10 個 tools 拆分），Finance 預估 15-20 個 tools，拆成 2 個 MCP Server：

**`workshop-finance`**（核心 CRUD，~10 tools）：
| Tool | 功能 |
|------|------|
| `finance_add_transaction` | 新增交易（含標籤、付款方式） |
| `finance_update_transaction` | 更新交易 |
| `finance_delete_transaction` | 刪除交易 |
| `finance_list_transactions` | 列出交易（過濾：月份/類型/分類/付款/標籤/搜尋） |
| `finance_add_subscription` | 新增訂閱 |
| `finance_update_subscription` | 更新訂閱（含暫停/取消） |
| `finance_list_subscriptions` | 列出訂閱 |
| `finance_manage_categories` | 分類 CRUD（新增/編輯/移動/停用） |
| `finance_upload_attachment` | 上傳交易附件照片 |
| `finance_suggest` | 欄位自動補全（商家、標籤、分類） |

**`workshop-finance-analytics`**（分析 + 預算，~8 tools）：
| Tool | 功能 |
|------|------|
| `finance_summary` | 月度收支摘要 |
| `finance_insights` | 多月消費趨勢分析 |
| `finance_budget_set` | 設定月度預算（總額 + 分類） |
| `finance_budget_status` | 查詢預算消耗狀態 |
| `finance_monthly_report` | 產生/查閱月度消費報告 |
| `finance_category_breakdown` | 分類明細（含子分類展開） |
| `finance_subscription_forecast` | 訂閱未來 N 月預估支出 |
| `finance_export` | 匯出資料（CSV / JSON） |

### 技術架構

```
workbench/src/modules/finance/    ← Finance UI（交易列表、圖表、預算、報告）
core/src/modules/finance/         ← Finance 後端（API + DB + 分析引擎 + 報告產生）
mcp/finance/                      ← workshop-finance MCP（核心 CRUD）
mcp/finance-analytics/            ← workshop-finance-analytics MCP（分析 + 預算）
```

### 遷移策略

1. **Phase A**：建立 finance schema（transactions + categories + tags + attachments + subscriptions + budgets）
2. **Phase B**：Core API CRUD（交易 + 分類 + 訂閱 + 預算） + RustFS 照片上傳
3. **Phase C**：MCP Server（2 個）切換到 Core API
4. **Phase D**：Web UI（交易列表 + 分類管理 + 訂閱管理）
5. **Phase E**：分析圖表 + 月度報告 + AI 建議

### 相關文件

| 文件 | 用途 |
|------|------|
| [v2-priorities.md](./v2-priorities.md) | 藍圖索引 |
| [shared-layer-patterns.md](../architecture/shared-layer-patterns.md) | 共享層模式（TreeStructure §5.3、Tags §5.4、StateMachine §3.4、LLMService §8.2、ExportService §8.5、ScheduledReport §8.4、ChartKit §9.4、CalendarView §9.2） |

---

**下一步** → [P6：Taskflow 排程與任務管理](./p6-taskflow.md)
