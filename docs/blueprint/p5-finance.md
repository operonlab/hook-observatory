---
doc_version: 3
content_hash: pending
target_lang: zh-TW
---

> [← 返回優先藍圖總覽](./v2-priorities.md)

# P5：Finance 記帳系統 — 完整個人財務管理

### 現況分析

V1 Finance MCP Server（`workshop-finance`）已有 10 個 tools：

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
**V1 缺什麼**：無照片附件、無樹狀分類、無預算功能、無視覺化圖表、無月度報告、無錢包管理、無分期追蹤、無隱密功能。

### V2 目標

將 Finance 從 MCP-only 工具升級為完整的個人財務管理系統，含 Web UI + 分析圖表 + 預算規劃 + 多錢包管理 + 分期付款追蹤 + 隱密保護。

> **ID 型別備註**：藍圖 SQL 使用 UUID 表達語意；實作 ORM 統一用 `String(32)` + `uuid7().hex`，對齊 `TimestampMixin` 慣例。

#### 1. 一次性交易（Transaction）

```sql
CREATE TABLE finance.transactions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id        UUID NOT NULL,
    type            TEXT NOT NULL,              -- 'income' / 'expense' / 'transfer'
    amount          DECIMAL(15,4) NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'TWD',
    description     TEXT,
    merchant        TEXT,                       -- 商家名稱

    -- 付款方式
    payment_method  TEXT NOT NULL,              -- 'cash', 'credit_card', 'debit_card',
                                               -- 'e_payment', 'bank_transfer'
    payment_detail  TEXT,                       -- 具體卡片/帳戶名稱
                                               -- e.g. '中信 LINE Pay', '玉山 Debit', 'Apple Pay'

    -- 分類系統（樹狀）
    category_id     UUID REFERENCES finance.categories(id) ON DELETE SET NULL,

    -- 錢包關聯（D1: wallet_id 必填 — 對帳/淨資產全依賴 wallet_id，NULL 造成每個查詢特殊處理）
    wallet_id           UUID NOT NULL REFERENCES finance.wallets(id) ON DELETE RESTRICT,
    transfer_to_wallet_id UUID REFERENCES finance.wallets(id) ON DELETE RESTRICT,

    -- 分期關聯
    installment_plan_id UUID REFERENCES finance.installment_plans(id) ON DELETE SET NULL,
    installment_number  INT,                    -- 第幾期（1~N）

    -- 轉帳配對（S1: 雙向 transaction 互指）
    paired_transaction_id UUID REFERENCES finance.transactions(id) ON DELETE SET NULL,

    -- 狀態
    status          TEXT DEFAULT 'completed',   -- 'completed', 'scheduled', 'cancelled', 'pending'

    -- 多幣別支援（F2: schema 預留，Phase 1 鎖定 TWD）
    settlement_amount  DECIMAL(15,4),           -- wallet currency 結算金額
    original_currency  TEXT,                    -- 原幣代碼
    exchange_rate      DECIMAL(12,6),           -- 匯率

    -- 手續費（M8: 轉帳/年費通用）
    fee             DECIMAL(15,4) DEFAULT 0,

    -- 發票（L1）
    invoice_number  TEXT,                       -- 統一發票號碼

    -- 隱密
    is_private      BOOLEAN DEFAULT false,

    -- 時間
    transacted_at   TIMESTAMPTZ NOT NULL,       -- 實際消費時間
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    created_by      UUID REFERENCES auth.users(id) ON DELETE SET NULL
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

-- Indexes（F3: 覆蓋高頻查詢）
CREATE INDEX idx_txn_space_time ON finance.transactions(space_id, transacted_at DESC);
CREATE INDEX idx_txn_wallet ON finance.transactions(wallet_id);
CREATE INDEX idx_txn_category ON finance.transactions(space_id, category_id, transacted_at);
CREATE INDEX idx_txn_installment ON finance.transactions(installment_plan_id);
CREATE UNIQUE INDEX idx_txn_installment_num ON finance.transactions(installment_plan_id, installment_number)
    WHERE installment_plan_id IS NOT NULL;
CREATE INDEX idx_txn_scheduled ON finance.transactions(status, transacted_at)
    WHERE status = 'scheduled';
CREATE INDEX idx_txn_paired ON finance.transactions(paired_transaction_id)
    WHERE paired_transaction_id IS NOT NULL;
```

**交易類型**（type 欄位）：
- `income` — 收入
- `expense` — 支出
- `transfer` — 錢包間轉帳（from `wallet_id` → to `transfer_to_wallet_id`）

**交易狀態**（status 欄位）：
- `completed` — 已完成（一般交易預設）
- `scheduled` — 排程中（分期付款未到期）
- `cancelled` — 已取消（分期取消的剩餘期數）
- `pending` — 預扣款（authorize→settle 流程）

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
    parent_id   UUID REFERENCES finance.categories(id) ON DELETE SET NULL,  -- NULL = 頂層
    name        TEXT NOT NULL,
    icon        TEXT,                                     -- emoji or icon name
    color       TEXT,                                     -- hex color
    sort_order  INT DEFAULT 0,
    is_active   BOOLEAN DEFAULT true,
    is_private  BOOLEAN DEFAULT false,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 同一 space + parent 下名稱唯一（僅 active 分類）
CREATE UNIQUE INDEX idx_category_unique_name
    ON finance.categories(space_id, COALESCE(parent_id, ''), name)
    WHERE is_active = true;
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
    amount          DECIMAL(15,4) NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'TWD',
    billing_cycle   TEXT NOT NULL,              -- 'monthly', 'yearly', 'weekly'
    billing_day     INT,                        -- 每月幾號扣款（1-31）
    category_id     UUID REFERENCES finance.categories(id) ON DELETE SET NULL,
    wallet_id       UUID REFERENCES finance.wallets(id) ON DELETE SET NULL,  -- 訂閱關聯錢包
    payment_method  TEXT,
    payment_detail  TEXT,
    start_date      DATE NOT NULL,
    end_date        DATE,                       -- NULL = 持續中
    status          TEXT DEFAULT 'active',      -- 'active', 'paused', 'cancelled'
    next_billing    DATE,                       -- 下次扣款日（自動計算）
    notes           TEXT,
    is_private      BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    created_by      UUID REFERENCES auth.users(id) ON DELETE SET NULL
);

CREATE INDEX idx_sub_space ON finance.subscriptions(space_id);
```

**自動記帳**：訂閱到期日 → 自動產生 transaction 記錄（cron job 或 event trigger）。

**自動記帳冪等**：以 `subscription_id + billing_period` 做 unique 檢查，避免重複記帳。

#### 4. 錢包系統（Wallet）

```sql
CREATE TABLE finance.wallets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id        UUID NOT NULL,
    name            TEXT NOT NULL,              -- '中信帳戶', '玉山儲蓄', '現金'
    type            TEXT NOT NULL,              -- 'bank_account', 'credit_card', 'cash',
                                               -- 'e_wallet', 'investment'
    currency        TEXT NOT NULL DEFAULT 'TWD',
    initial_balance DECIMAL(15,4) NOT NULL DEFAULT 0,
    current_balance DECIMAL(15,4) NOT NULL DEFAULT 0,  -- 最新餘額（原子差量更新）
    credit_limit    DECIMAL(15,4),              -- 信用卡額度（僅 type=credit_card）
    icon            TEXT,
    color           TEXT,
    sort_order      INT DEFAULT 0,
    is_active       BOOLEAN DEFAULT true,
    is_private      BOOLEAN DEFAULT false,
    sync_provider   TEXT DEFAULT 'manual',      -- 預留 CSV/API 同步（'manual' / 'csv' / 'api'）
    last_synced_at  TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ,                -- soft delete 配合 is_active
    created_at      TIMESTAMPTZ DEFAULT now(),
    created_by      UUID REFERENCES auth.users(id) ON DELETE SET NULL
);

-- 同一 space 下名稱唯一（僅 active 錢包）
CREATE UNIQUE INDEX idx_wallet_unique_name
    ON finance.wallets(space_id, name) WHERE is_active = true;
CREATE INDEX idx_wallet_space ON finance.wallets(space_id);

-- 餘額快照（對帳核心）
CREATE TABLE finance.wallet_snapshots (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    wallet_id           UUID REFERENCES finance.wallets(id) ON DELETE CASCADE,
    space_id            VARCHAR(32) NOT NULL,                     -- M17/S2: 多租戶+隱密繼承
    created_by          VARCHAR(32),                              -- S2: 權限校驗
    synced_balance      DECIMAL(15,4) NOT NULL,                   -- 使用者回報的實際餘額
    calculated_balance  DECIMAL(15,4) NOT NULL,                   -- 系統計算餘額（上次同步 + Σ交易）
    difference          DECIMAL(15,4) GENERATED ALWAYS AS (synced_balance - calculated_balance) STORED,  -- M16: 計算欄位
    snapshot_type       TEXT DEFAULT 'reconciliation',            -- S8: 'reconciliation' / 'valuation'
    notes               TEXT,                                     -- 差異備註
    synced_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_snapshot_wallet_time ON finance.wallet_snapshots(wallet_id, synced_at DESC);
CREATE INDEX idx_snapshot_space_time ON finance.wallet_snapshots(space_id, synced_at DESC);
```

**錢包類型與餘額邏輯**：

| type | balance 含義 | 特殊欄位 |
|------|-------------|----------|
| bank_account | 正數 = 存款 | — |
| credit_card | 負數 = 欠款，0 = 已繳清 | credit_limit |
| cash | 正數 = 手邊現金 | — |
| e_wallet | 正數 = 電子錢包餘額 | — |
| investment | 正數 = 投資市值 | — |

**信用卡統一為 wallet**：不另建信用卡實體，以 `type=credit_card` 的 wallet 涵蓋。信用卡消費 = 該 wallet 的 expense transaction，繳卡費 = income transaction（或 bank_account → credit_card 的 transfer）。

**信用卡繳款語意統一（S6）**：明確定義為 `transfer`（bank→credit_card），不記為 income。前端引導使用者選擇「繳卡費」時自動填入 type=transfer + from_wallet=銀行 + to_wallet=信用卡。

**雙面夾擊對帳流程**：
```
同步點A (3/1: 實際餘額 $50,000)
    ├── 記錄消費 $3,000 + $2,500 + $1,000 = $6,500
    └── 系統計算餘額 = $50,000 - $6,500 = $43,500
同步點B (3/15: 實際餘額 $42,000)
    └── 差額 = $42,000 - $43,500 = -$1,500 ← 有 $1,500 漏記支出
    └── 使用者補充遺漏交易 → 差額歸零 ✅
```

**投資型錢包對帳邏輯（S8）**：snapshot_type='valuation' 時，difference 代表損益變化而非漏記，不顯示差額警告。

**停用錢包 Gate Check（M9）**：有 active 分期計畫或 active 訂閱關聯時，阻止停用錢包。使用者必須先將分期/訂閱遷移至其他錢包，才能停用。

**錢包間轉帳**：支援 `type='transfer'` 交易，`wallet_id` = 來源錢包，`transfer_to_wallet_id` = 目標錢包。轉帳在同一 DB transaction 內完成，SELECT FOR UPDATE 按 wallet_id 排序防死鎖。

**淨資產公式（S10）**：
```
淨資產(TWD) = Σ(wallet.current_balance WHERE type IN ('bank_account','cash','e_wallet'))
            + Σ(wallet.current_balance WHERE type = 'investment')
            + Σ(wallet.current_balance WHERE type = 'credit_card')  -- 負數
            -- 非 TWD 錢包用當日匯率換算至 display_currency
            -- credit_limit 不計入
```

#### 5. 分期付款（Installment Plan）

```sql
CREATE TABLE finance.installment_plans (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id            UUID NOT NULL,
    description         TEXT NOT NULL,              -- 'MacBook Pro 14"'
    total_amount        DECIMAL(15,4) NOT NULL,     -- 總金額
    currency            TEXT NOT NULL DEFAULT 'TWD',
    num_installments    INT NOT NULL,               -- 分期數 (3/6/12/24)
    installment_amount  DECIMAL(15,4) NOT NULL,     -- 每期金額（系統計算，尾差處理：最後一期 = total - 前 N-1 期合計）
    interest_rate       DECIMAL(5,4) DEFAULT 0,     -- 年利率（0 = 零利率）
    billing_day         INT,                        -- S7: 每月扣款日（1-31，NULL 則從 start_date day 推算）
    fee_type            TEXT DEFAULT 'none',        -- M11: 'none'/'interest'/'fee_per_period'/'total_fee'
    fee_per_installment DECIMAL(15,4) DEFAULT 0,    -- 每期手續費
    merchant            TEXT,                        -- 商家
    category_id         UUID REFERENCES finance.categories(id) ON DELETE SET NULL,
    wallet_id           UUID REFERENCES finance.wallets(id) ON DELETE RESTRICT,  -- 扣款錢包
    payment_method      TEXT NOT NULL,
    payment_detail      TEXT,
    start_date          DATE NOT NULL,               -- 第一期日期
    end_date            DATE,                        -- 最後一期（自動計算）
    status              TEXT DEFAULT 'active',       -- 'active', 'completed', 'cancelled'
    is_private          BOOLEAN DEFAULT false,
    created_at          TIMESTAMPTZ DEFAULT now(),
    created_by          UUID REFERENCES auth.users(id) ON DELETE SET NULL
);
```

**分期 → Transaction 生成邏輯**：
1. 建立 installment_plan 時 → 立即產生 N 筆 transaction（status='scheduled'）
2. 每筆 transaction 帶 `installment_plan_id` + `installment_number`（1~N）
3. Cron job：到期日將 `scheduled` → `completed`，允許修改實際金額
4. 取消分期：剩餘 `scheduled` transactions → `cancelled`

**尾差處理**：`installment_amount` 由系統計算。最後一期 = total_amount - 前 (N-1) 期合計，確保總金額精準無誤。

**billing_day 日期計算**：若 billing_day > 當月天數，取當月最後一天（e.g. billing_day=31 在 2 月 → 2/28 或 2/29）。

**分期餘額計算**：
- 已繳 = Σ `completed` transactions
- 待繳 = Σ `scheduled` transactions
- 進度 = 已繳期數 / 總期數

**提前還款**：`POST /api/finance/installments/{id}/payoff`（M7）— 將所有剩餘 `scheduled` transactions 標記為 `completed`，更新錢包餘額。

**可編輯欄位範圍**：description / merchant / category / wallet 可改；num_installments / total_amount 不可改（需取消重建）。修改 installment_amount 時，自動更新所有 `scheduled` 期的金額。

#### 6. 預算功能（Budget）

```sql
CREATE TABLE finance.budgets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    space_id        UUID NOT NULL,
    year_month      TEXT NOT NULL,              -- '2026-02'
    category_id     UUID REFERENCES finance.categories(id) ON DELETE CASCADE,  -- NULL = 總預算
    budget_amount   DECIMAL(15,4) NOT NULL,     -- 預算金額
    savings_target  DECIMAL(15,4),              -- 儲蓄目標（僅總預算有）
    is_private      BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- 修復 NULL unique 陷阱：分拆成兩個 partial unique index
CREATE UNIQUE INDEX idx_budget_with_category
    ON finance.budgets(space_id, year_month, category_id)
    WHERE category_id IS NOT NULL;
CREATE UNIQUE INDEX idx_budget_total
    ON finance.budgets(space_id, year_month)
    WHERE category_id IS NULL;
```

**預算邏輯**：
- **總預算**：這個月預計花多少、存多少
- **分類預算**：飲食上限 8000、娛樂上限 3000…
- **即時比對**：當月實際支出 vs 預算，超支即警示
- **剩餘分配**：月初設定 → 隨消費遞減 → 剩餘可用金額
- **分期承諾支出**（M6）：預算中獨立顯示「承諾支出 $X + 自由支出 $Y / 預算 $Z」，讓使用者看清真正的可支配空間

#### 7. 消費分析圖表（Web UI）

| 圖表類型 | 用途 | 資料來源 |
|---------|------|---------|
| **圓餅圖** | 當月支出分類佔比 | `transactions` GROUP BY `category` |
| **柱狀圖** | 月度收支對比（近 6/12 個月） | `transactions` GROUP BY `month` |
| **散佈圖** | 消費金額 × 時間分佈（找出消費模式） | `transactions` 的 `amount` × `transacted_at` |
| **趨勢線** | 各分類月度變化趨勢 | `transactions` GROUP BY `category, month` |
| **預算進度** | 各分類預算消耗百分比 | `budgets` vs `transactions` |
| **訂閱日曆** | 每月訂閱扣款時間軸 | `subscriptions` 的 `next_billing` |
| **錢包餘額走勢** | 各錢包餘額隨時間變化 | `wallet_snapshots` |
| **對帳差額圖** | 每次同步的差額趨勢（越接近 0 越好） | `wallet_snapshots` 的 `difference` |
| **分期支出日曆** | 未來 N 月的分期扣款時間軸 | `installment_plans` + `transactions`（scheduled） |
| **淨資產** | Σ 所有錢包餘額（投資 + 存款 - 信用卡欠款） | `wallets` 的 `current_balance` |

> **淨資產圖表標注**：投資市值為最後同步日數據，非 TWD 錢包以當日匯率換算。

**技術選擇**：前端使用 **Recharts**（React 生態，支援響應式）或 **ECharts**（功能更豐富）。

#### 8. 月度消費報告

每月自動產生（月底 or 下月 1 號觸發）：

```
📊 2026 年 2 月消費報告
─────────────────────

💰 收支摘要
  收入：$85,000
  支出：$52,300（預算 $60,000，節省 $7,700 ✅）
  儲蓄：$32,700（目標 $25,000，超額達標 ✅）

🏦 錢包概覽
  中信帳戶：$120,000（+$32,700）
  玉山儲蓄：$350,000（無異動）
  中信信用卡：-$18,500（待繳）
  淨資產：$451,500

📈 分類分析
  飲食  $12,500 / $15,000（83%）
  交通  $3,200 / $5,000（64%）
  娛樂  $8,900 / $8,000（111% ⚠️ 超支）
  居住  $18,000 / $18,000（100%）

📅 分期追蹤
  MacBook Pro：第 4/12 期 $3,750（剩餘 $30,000）
  冷氣：第 8/12 期 $2,500（剩餘 $10,000）

💡 AI 建議
  1. 娛樂類超支 $900，主要來自 2/14 的旅遊消費，建議下月調高預算或分攤
  2. 飲料消費佔飲食的 28%（$3,500），較上月增加 15%
  3. 訂閱類月支出 $4,200，建議檢視 3 個超過半年未使用的訂閱
  4. 對帳差額：中信帳戶本月累積差額 $-320，建議補記遺漏交易
```

**產生方式**：
- 自動觸發：每月 1 號 cron job → 彙整上月資料 → LLM 產生建議 → 寫入 DB
- 手動觸發：UI 上按鈕或 MCP tool
- **月度報告按 viewer 身份動態過濾**。AI 建議 prompt 排除 `is_private=true` 交易細節。

#### 9. 隱密功能（Privacy — 直接排除策略）

所有財務實體（交易、訂閱、分類、預算、錢包、分期計畫）均支援 `is_private` 欄位。

**核心變更（D2）**：列表從「馬賽克」改為「直接排除」。馬賽克仍洩漏 metadata（category_id, wallet_id, type, UUID v7 時間戳），直接排除更安全。

**機制**：SQL-level 過濾（非 Python post-filter）

```python
# services.py — 隱密過濾邏輯（SQL WHERE 注入）
def apply_privacy_filter(query, model, current_user_id):
    """非 owner 的隱密項目直接從結果排除"""
    return query.where(
        or_(model.is_private == False, model.created_by == current_user_id)
    )
```

**權限規則**：

| 操作 | 非 owner | owner (created_by) |
|------|---------|-------------------|
| 列表（List） | **不顯示**（SQL WHERE 排除） | 完整資料 |
| 詳情（Get） | **404**（統一，非 403，防 oracle attack） | 完整資料 |
| 編輯（Update） | 404 | 允許 |
| 刪除（Delete） | 404 | 允許 |
| 搜尋命中隱密 | 不返回（排除） | 正常返回 |
| 聚合 | 排除隱密項目 | 包含全部 |
| 匯出 | 排除隱密項目（row 不存在） | 包含全部 |
| 欄位補全 | 排除隱密交易的 merchant/tag | 包含全部 |

**Privacy 單一責任宣告**：所有 privacy 過濾邏輯集中在 `core/src/modules/finance/services.py`。MCP Server 作為 thin wrapper，不做任何額外 privacy 處理。

**子實體繼承**：
- `transaction_tags` / `transaction_attachments` → JOIN parent transaction 檢查 `is_private`
- `wallet_snapshots` → 繼承 parent wallet 的 `is_private`
- Presigned URL 生成必須驗證 transaction privacy

#### 10. MCP Server 設計

根據 AD-2 切分規則（每個 MCP Server ≤ 10 tools），Finance 共 27 個 tools，拆成 3 個 MCP Server：

**`workshop-finance`**（核心 CRUD，10 tools）：

| Tool | 功能 | 備註 |
|------|------|------|
| `finance_add_transaction` | 新增交易（含 wallet_id、installment 關聯） | 修改 |
| `finance_update_transaction` | 更新交易 | — |
| `finance_delete_transaction` | 刪除交易 | — |
| `finance_list_transactions` | 列出交易（過濾：月份/類型/分類/付款/標籤/搜尋/錢包/分期） | 修改 |
| `finance_add_subscription` | 新增訂閱 | — |
| `finance_update_subscription` | 更新訂閱（含暫停/取消） | — |
| `finance_list_subscriptions` | 列出訂閱 | — |
| `finance_manage_categories` | 分類 CRUD（新增/編輯/移動/停用） | — |
| `finance_suggest` | 欄位自動補全（商家、標籤、分類） | — |
| `finance_toggle_privacy` | 切換項目隱密狀態 | 從 wallet server 移入 |

**`workshop-finance-wallet`**（錢包 + 分期，8 tools）：

| Tool | 功能 | 備註 |
|------|------|------|
| `finance_manage_wallets` | 錢包 CRUD（新增/編輯/停用） | 新增 |
| `finance_sync_wallet` | 同步錢包餘額 + 產生 snapshot | 新增 |
| `finance_reconcile` | 錢包對帳摘要（顯示各錢包差額） | 新增 |
| `finance_transfer` | 錢包間轉帳 | 新增 |
| `finance_add_installment` | 新增分期（自動產生 scheduled transactions） | 新增 |
| `finance_list_installments` | 列出分期計畫 | 新增 |
| `finance_installment_payoff` | 分期提前還款 | 新增 |
| `finance_upload_attachment` | 上傳交易附件照片 | 從核心移入 |

**`workshop-finance-analytics`**（分析 + 預算，9 tools）：

| Tool | 功能 | 備註 |
|------|------|------|
| `finance_summary` | 月度收支摘要（含錢包餘額總覽） | 修改 |
| `finance_insights` | 多月消費趨勢分析 | — |
| `finance_budget_set` | 設定月度預算（總額 + 分類） | — |
| `finance_budget_status` | 查詢預算消耗狀態 | — |
| `finance_monthly_report` | 產生/查閱月度消費報告 | — |
| `finance_category_breakdown` | 分類明細（含子分類展開） | — |
| `finance_subscription_forecast` | 訂閱未來 N 月預估支出 | — |
| `finance_installment_forecast` | 分期未來支出預估 | 新增 |
| `finance_export` | 匯出資料（CSV / JSON，含隱密過濾） | 修改 |

#### 11. 事件定義

```python
class FinanceEvents:
    # 交易
    TRANSACTION_CREATED = "finance.transaction.created"
    TRANSACTION_UPDATED = "finance.transaction.updated"
    TRANSACTION_DELETED = "finance.transaction.deleted"

    # 預算
    BUDGET_EXCEEDED = "finance.budget.exceeded"

    # 錢包
    WALLET_SYNCED = "finance.wallet.synced"               # 錢包餘額同步
    WALLET_RECONCILED = "finance.wallet.reconciled"       # 對帳完成

    # 分期
    INSTALLMENT_CREATED = "finance.installment.created"   # 分期計畫建立
    INSTALLMENT_COMPLETED = "finance.installment.completed" # 分期全部完成
    INSTALLMENT_DUE = "finance.installment.due"           # 單期到期
    INSTALLMENT_CANCELLED = "finance.installment.cancelled" # 分期取消

    # 轉帳
    TRANSFER_COMPLETED = "finance.transfer.completed"     # 轉帳完成

    # 隱密
    PRIVACY_TOGGLED = "finance.privacy.toggled"           # 隱密狀態變更
```

**事件發送時機說明**：
- `TRANSFER_COMPLETED`：兩個錢包餘額都更新 + transaction record 寫入後才發
- `INSTALLMENT_DUE`：cron 用 `RETURNING id` 取實際更新 ID，只發一次 batch event
- cron 將 `scheduled→completed` 時只發 `INSTALLMENT_DUE`，不發 `TRANSACTION_UPDATED`（系統行為 vs 使用者行為區分）

**事件韌性標注**（參照 [AD-10 事件韌性模式](../architecture/event-resilience-patterns.md)）：

Finance 模組適用 P1（時效分類）+ P2（冪等投影）+ P5（非阻塞隔離）。

| 事件 | TTL 分類 | dedup key 策略 | 理由 |
|------|---------|---------------|------|
| `transaction.created` | durable (0) | `transaction_id`（業務 ID） | 金流紀錄永久保存 |
| `transaction.updated` | durable (0) | `transaction_id + updated_at` | 變更歷史需追溯 |
| `transaction.deleted` | durable (0) | `transaction_id` | audit trail |
| `budget.exceeded` | idempotent (5min) | `space_id + year_month + category_id` | 同一預算週期內去重，避免重複通知 |
| `wallet.synced` | durable (0) | `snapshot_id`（業務 ID） | 對帳記錄永久保存 |
| `wallet.reconciled` | durable (0) | `wallet_id + synced_at` | 對帳歷史 |
| `installment.created` | durable (0) | `installment_plan_id` | 分期紀錄永久保存 |
| `installment.completed` | durable (0) | `installment_plan_id` | 完成事實 |
| `installment.due` | idempotent (5min) | `installment_plan_id + installment_number` | cron 可能重跑，需冪等 |
| `installment.cancelled` | durable (0) | `installment_plan_id` | 取消事實 |
| `transfer.completed` | durable (0) | `paired_transaction_id` | 轉帳紀錄永久保存 |
| `privacy.toggled` | durable (0) | `entity_type + entity_id + toggled_at` | audit trail |

**冪等實作要點**：
- 交易類事件用 **業務 ID** 作為 natural key（零碰撞風險）
- `budget.exceeded` / `installment.due` 用 **複合鍵** 確保 cron 重跑安全
- 所有 handler 搭配 `ON CONFLICT DO NOTHING`（P2 模式）
- EventBus publish 走 fire-and-forget（P5 模式），不阻塞 API 回應

### API 端點

```
# 交易
GET/POST    /api/finance/transactions                  -- 列表/新增
GET/PUT/DEL /api/finance/transactions/{id}             -- 詳情/更新/刪除
POST        /api/finance/transactions/{id}/attachments -- 上傳照片

# 分類
GET/POST    /api/finance/categories                    -- 列表/新增
PUT         /api/finance/categories/{id}               -- 更新（含移動）

# 訂閱
GET/POST    /api/finance/subscriptions                 -- 列表/新增
PUT         /api/finance/subscriptions/{id}            -- 更新（含暫停/取消）

# 錢包
GET/POST    /api/finance/wallets                       -- 列表/新增
GET/PUT/DEL /api/finance/wallets/{id}                  -- 詳情/更新/刪除
POST        /api/finance/wallets/{id}/sync             -- 同步餘額（建立 snapshot）
GET         /api/finance/wallets/{id}/snapshots        -- 快照歷史
GET         /api/finance/wallets/reconcile             -- 全錢包對帳摘要

# 分期
GET/POST    /api/finance/installments                  -- 列表/新增（含自動產生 transactions）
GET/PUT     /api/finance/installments/{id}             -- 詳情/更新
POST        /api/finance/installments/{id}/cancel      -- 取消剩餘期數
POST        /api/finance/installments/{id}/payoff      -- 提前還款（M7）

# 轉帳
POST        /api/finance/transfers                     -- 錢包間轉帳（request body 含 fee 選填欄位）

# 預算
GET/POST    /api/finance/budgets                       -- 查詢/設定

# 分析
GET         /api/finance/summary                       -- 月度收支摘要
GET         /api/finance/insights                      -- 多月消費趨勢
GET         /api/finance/reports/{year_month}           -- 月度消費報告
```

### 技術架構

```
workbench/src/modules/finance/    ← Finance UI（交易列表、圖表、預算、報告、錢包管理、分期追蹤）
core/src/modules/finance/         ← Finance 後端（API + DB + 分析引擎 + 報告產生 + 對帳引擎）
mcp/finance/                      ← workshop-finance MCP（核心 CRUD）
mcp/finance-wallet/               ← workshop-finance-wallet MCP（錢包 + 分期）
mcp/finance-analytics/            ← workshop-finance-analytics MCP（分析 + 預算）
```

### 餘額一致性 ADR

**策略**：原子差量 + 定期校正（D3）

O(1) 每筆交易效能，sync 時全量校正偏差。轉帳用 SELECT FOR UPDATE（按 wallet_id 排序防死鎖）。

| 場景 | 餘額更新公式 |
|------|-------------|
| 新增交易 | `UPDATE wallets SET current_balance = current_balance - :amount WHERE id = :wallet_id` |
| 更新交易 | `delta = new_amount - old_amount; UPDATE wallets SET current_balance = current_balance - :delta` |
| 刪除交易 | `UPDATE wallets SET current_balance = current_balance + :amount` |
| 轉帳 | `SELECT FOR UPDATE`（按 wallet_id 排序）+ 同一 DB transaction 內扣出入帳 |
| 取消分期 | 將所有 `scheduled` 期餘額影響回滾 |
| Sync 校正 | snapshot 記錄 difference，使用者確認後以 synced_balance 覆寫 current_balance |

**Cron 冪等**：`WHERE status='scheduled' AND transacted_at <= now()` + `RETURNING id`，只對實際更新的 row 發事件。

**BaseCRUDService 整合**：Finance 的 `TransactionService` override `create()` / `update()` / `delete()`，在 hook 內執行餘額差量更新。不改 base class hook 簽名。

### 多幣別邊界

- **Phase 1 鎖定 TWD only**：currency 欄位保留但 UI 不開放切換
- Schema 預留 `original_currency`、`exchange_rate`、`settlement_amount`
- 跨幣別轉帳 Phase 1 禁止（CHECK constraint: `wallet.currency = transaction.currency`）
- 淨資產 Phase 1 只加總 TWD 錢包
- 未來多幣別開放時，淨資產計算需用當日匯率換算至 display_currency

### 冷熱資料策略

對齊 Workshop 4-Phase 冷熱分層慣例（參照 memvault/intelflow 實作）。

**資料溫度定義**：

| 溫度 | 條件 | 存放位置 | 查詢方式 |
|------|------|---------|---------|
| Hot | `transacted_at` 近 12 個月 | 主表（含 B-tree + partial index） | 完整 SQL 查詢 |
| Warm | 12-24 個月 | 主表（但不在 partial index 覆蓋範圍） | 完整 SQL 查詢（略慢） |
| Cold | > 24 個月 | `finance.transactions_archive` + S3 blob | ILIKE text search（無 HNSW） |

**Phase 演進**：

1. **Phase 1 — Partial Indexes**（Phase A 一起做）
   - 已在 §1 定義：`idx_txn_scheduled`、`idx_txn_paired` 等 partial index
   - 高頻查詢走 partial index，低頻（cancelled/old）走 full scan

2. **Phase 2 — Archive Tables**（Phase G 後）
   ```sql
   CREATE TABLE finance.transactions_archive (
       LIKE finance.transactions INCLUDING ALL
   );
   -- 無 partial index、無 HNSW，僅 B-tree on (space_id, transacted_at)
   CREATE INDEX idx_txn_archive_space_time
       ON finance.transactions_archive(space_id, transacted_at DESC);
   ```

3. **Phase 3 — S3 歸檔**（資料量 > 100K 筆時）
   - 附件 blob（transaction_attachments 的 storage_key）本身已在 RustFS（S3）
   - Cold 交易的大型 notes/description 可壓縮至 S3，主表存 `s3://` 前綴 reference
   - 讀取時透明 resolve（參照 `core/src/shared/storage.py`）

4. **Phase 4 — Auto Archive Script**
   - 擴充 `scripts/archive_cold_data.py` 加入 finance 模組
   - 閾值：`transacted_at < now() - interval '24 months'` AND `status IN ('completed', 'cancelled')`
   - `scheduled` 狀態永不歸檔（仍為活躍分期）
   - `--dry-run` 預設，`--execute` 執行
   - 歸檔後主表 row 刪除，archive 表保留完整資料

**歸檔排除規則**：
- `status = 'scheduled'` — 活躍分期不歸檔
- `status = 'pending'` — 預扣款不歸檔
- 關聯的 `installment_plan` 仍為 `active` — 整組分期交易不拆開歸檔
- `wallet_snapshots` 最近 6 個月保留主表，更早的歸檔

**Cold 資料查詢**：
- 列表 API 預設只查主表（Hot + Warm）
- `include_archived=true` 參數觸發 UNION 查詢（主表 + archive 表）
- Cold 搜尋只走 ILIKE（`_text_search_fallback`），不走全文索引

### 遷移策略

0. **Phase 0：V1 資料遷移策略**
   - wallet 推斷：根據 V1 `payment_method + payment_detail` 自動建立 wallet 並回填 wallet_id
   - 系統自動建立「未分類」預設錢包（V1 無法推斷的歸入此處）
   - status：V1 所有交易預設 `completed`
   - category_id：V1 text 分類 → 建立 categories 記錄 → 回填 UUID FK
   - is_private：預設 false
   - 遷移腳本可重跑（idempotent）、支援 `--dry-run`
   - **驗證 checklist**：筆數一致、金額加總一致、分類覆蓋率
1. **Phase A**：建立 finance schema（transactions + categories + tags + attachments + subscriptions + budgets + wallets + wallet_snapshots + installment_plans）+ 所有表的 `is_private` 欄位
2. **Phase B**：Core API CRUD — 交易 + 分類 + 訂閱 + 預算 + 錢包 + 分期 + 轉帳 + 隱密過濾
3. **Phase C**：RustFS 照片上傳 + 錢包餘額同步 + 快照 + 對帳引擎
4. **Phase D**：MCP Server（3 個）切換到 Core API
5. **Phase E**：Web UI — 交易列表 + 分類管理 + 訂閱管理 + 錢包管理 + 分期管理 + 隱密切換
6. **Phase F**：分析圖表 + 錢包走勢 + 淨資產 + 對帳差額
7. **Phase G**：月度報告 + AI 建議 + 分期到期 cron + 對帳提醒

### 相關文件

| 文件 | 用途 |
|------|------|
| [v2-priorities.md](./v2-priorities.md) | 藍圖索引 |
| [shared-layer-patterns.md](../architecture/shared-layer-patterns.md) | 共享層模式（TreeStructure §5.3、Tags §5.4、StateMachine §3.4、LLMService §8.2、ExportService §8.5、ScheduledReport §8.4、ChartKit §9.4、CalendarView §9.2） |

---

**下一步** → [P6：Taskflow 排程與任務管理](./p6-taskflow.md)
