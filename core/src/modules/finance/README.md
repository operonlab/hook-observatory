# finance — 會計與財務模組

> 個人/家庭記帳、訂閱管理、預算規劃、消費分析、多錢包管理、分期追蹤、隱密保護。

## 定位

| 屬性 | 值 |
|------|-----|
| **Schema** | `finance` |
| **依賴** | auth |
| **MCP** | `workshop-finance`（CRUD 10 tools）+ `workshop-finance-wallet`（錢包+分期 8 tools）+ `workshop-finance-analytics`（分析 9 tools） |
| **V1 參考** | `workshop-finance` MCP（10 tools，port 8793） |

## 核心功能

### 一次性交易（Transaction）

- 收入/支出/轉帳記錄
- 付款方式：現金、信用卡、簽帳卡、電子支付、銀行轉帳
- 具體卡片/帳戶名稱（如「中信 LINE Pay」、「玉山 Debit」）
- 複數自訂標籤（多對多）
- 複數照片附件（RustFS 存檔，DB 記 storage_key）
- 狀態：completed / scheduled / cancelled / pending（預扣款）
- **wallet_id 必填**（D1）：對帳/淨資產全依賴 wallet_id
- 支援關聯分期計畫（installment_plan_id）+ 轉帳配對（paired_transaction_id）
- 多幣別預留：settlement_amount / original_currency / exchange_rate（Phase 1 鎖定 TWD）
- 手續費欄位 fee（轉帳/年費通用）、統一發票 invoice_number

### 樹狀分類系統（Category Tree）

- parent_id 自引用，支援無限層級
- 使用者可自訂新增/編輯/移動/停用
- 預設範本：飲食（早/午/晚/飲料/零食）、交通、居住、娛樂…
- 同一 space + parent 下名稱唯一（partial unique index，僅 active）

### 週期性訂閱（Subscription）

- 週期：monthly / yearly / weekly
- 狀態：active / paused / cancelled
- 自動記帳：到期日自動產生 transaction（event trigger）
- 自動記帳冪等：以 subscription_id + billing_period 做 unique 檢查
- 關聯錢包（wallet_id）

### 錢包系統（Wallet）

- 多帳戶餘額管理：bank_account / credit_card / cash / e_wallet / investment
- 信用卡統一為 wallet（type=credit_card），含 credit_limit 額度
- 信用卡繳款語意（S6）：明確定義為 transfer（bank→credit_card），非 income
- 錢包間轉帳：type='transfer' 交易（from_wallet_id → to_wallet_id），同一 DB transaction 內完成
- **餘額更新策略（D3）**：原子差量 `SET balance = balance - amount` + sync 時全量校正
- 餘額快照（wallet_snapshots）：每次同步記錄實際餘額 vs 計算餘額
- snapshot_type（S8）：reconciliation（對帳）/ valuation（投資市值，difference = 損益非漏記）
- 雙面夾擊對帳：同步點之間的差額 = 漏記金額 → 引導使用者補記
- 停用錢包 Gate Check（M9）：有 active 分期/訂閱時阻止停用
- Soft delete（deleted_at）+ sync_provider 預留
- 淨資產公式（S10）：bank+cash+e_wallet+investment+credit_card(負數)，credit_limit 不計入

### 分期付款（Installment Plan）

- 追蹤分期購買（3/6/12/24 期）
- 建立時立即產生 N 筆 scheduled transactions
- Cron job：到期日 scheduled → completed
- 取消分期：剩餘 scheduled → cancelled
- 支援零利率與有息分期（interest_rate）
- billing_day（S7）：每月扣款日，> 當月天數取最後一天
- fee_type（M11）：none / interest / fee_per_period / total_fee
- 尾差處理：最後一期 = total - 前 N-1 期合計
- 提前還款（M7）：POST /api/finance/installments/{id}/payoff
- 可編輯：description/merchant/category/wallet；不可改：num_installments/total_amount

### 預算功能（Budget）

- 總預算：月預計花費 + 儲蓄目標
- 分類預算：各分類上限金額
- 即時比對：當月支出 vs 預算，超支警示
- 分期承諾支出（M6）：獨立顯示「承諾支出 + 自由支出 / 預算」
- NULL unique 修復：分拆成兩個 partial unique index

### 隱密功能（Privacy — 直接排除策略）

- 所有財務實體支援 `is_private` 欄位
- **D2 決策**：列表非 owner 直接排除（非馬賽克），馬賽克仍洩漏 metadata
- SQL-level 過濾（`apply_privacy_filter`），非 Python post-filter
- 非 owner：列表不顯示、詳情 404（非 403 防 oracle）、搜尋排除、聚合排除、匯出排除
- Privacy 單一責任：邏輯集中在 services.py，MCP 不做額外處理
- 子實體繼承：tags/attachments JOIN parent 檢查、snapshots 繼承 wallet is_private
- Presigned URL 必須驗證 transaction privacy

### 消費分析

- 圓餅圖：當月分類佔比
- 柱狀圖：月度收支對比
- 散佈圖：消費金額 × 時間分佈
- 趨勢線：各分類月度變化
- 預算進度：消耗百分比
- 錢包餘額走勢：基於 snapshots
- 對帳差額圖：同步差額趨勢
- 分期支出日曆：未來 N 月分期扣款
- 淨資產：全錢包餘額加總（投資市值為最後同步日，非 TWD 以當日匯率換算）

### 月度消費報告

- 自動產生：每月 1 號 cron
- 含錢包概覽、分期追蹤
- LLM 產生 AI 建議（消費習慣觀察、超支提醒、訂閱檢視、對帳差額提醒）
- 按 viewer 身份動態過濾，AI prompt 排除 is_private=true 交易細節

## DB Schema

```sql
CREATE SCHEMA finance;

finance.transactions            -- 交易（amount DECIMAL(15,4), type, status, wallet_id NOT NULL,
                                --   installment_plan_id, paired_transaction_id, is_private,
                                --   settlement_amount, original_currency, exchange_rate, fee, invoice_number）
finance.transaction_tags        -- 標籤（transaction_id, tag）多對多
finance.transaction_attachments -- 照片附件（storage_key → RustFS）
finance.categories              -- 樹狀分類（parent_id 自引用，is_private，partial unique name）
finance.subscriptions           -- 訂閱（billing_cycle, next_billing, status, wallet_id, is_private, updated_at）
finance.wallets                 -- 錢包（type, current_balance DECIMAL(15,4), credit_limit, is_private,
                                --   sync_provider, deleted_at, partial unique name）
finance.wallet_snapshots        -- 餘額快照（synced_balance, calculated_balance,
                                --   difference GENERATED, snapshot_type, space_id, created_by）
finance.installment_plans       -- 分期計畫（num_installments, installment_amount, interest_rate,
                                --   billing_day, fee_type, fee_per_installment, is_private）
finance.budgets                 -- 預算（year_month, category_id, budget_amount, savings_target,
                                --   is_private, 兩個 partial unique index）
```

> **ID 型別備註**：藍圖 SQL 使用 UUID 表達語意；實作 ORM 統一用 `String(32)` + `uuid7().hex`。
> **DECIMAL 精度**：所有金額 `DECIMAL(15,4)`（相容 JPY 無小數、未來小數幣別）；`interest_rate` 維持 `DECIMAL(5,4)`。
> 所有 FK 補 ON DELETE 策略（RESTRICT / SET NULL / CASCADE 視語意而定）。

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
| GET/POST | `/api/finance/wallets` | 錢包列表/新增 |
| GET/PUT/DELETE | `/api/finance/wallets/{id}` | 錢包詳情/更新/刪除 |
| POST | `/api/finance/wallets/{id}/sync` | 同步餘額（建立 snapshot） |
| GET | `/api/finance/wallets/{id}/snapshots` | 快照歷史 |
| GET | `/api/finance/wallets/reconcile` | 全錢包對帳摘要 |
| GET/POST | `/api/finance/installments` | 分期列表/新增 |
| GET/PUT | `/api/finance/installments/{id}` | 分期詳情/更新 |
| POST | `/api/finance/installments/{id}/cancel` | 取消剩餘期數 |
| POST | `/api/finance/installments/{id}/payoff` | 提前還款（M7） |
| POST | `/api/finance/transfers` | 錢包間轉帳（含 fee 選填） |
| GET/POST | `/api/finance/budgets` | 預算查詢/設定 |
| GET | `/api/finance/summary` | 月度收支摘要 |
| GET | `/api/finance/insights` | 多月消費趨勢 |
| GET | `/api/finance/reports/{year_month}` | 月度消費報告 |

## 事件

| 事件 | 觸發時機 |
|------|---------|
| `finance.transaction.created` | 交易新增 |
| `finance.transaction.updated` | 交易更新 |
| `finance.transaction.deleted` | 交易刪除 |
| `finance.budget.exceeded` | 預算超支 |
| `finance.wallet.synced` | 錢包餘額同步 |
| `finance.wallet.reconciled` | 對帳完成 |
| `finance.installment.created` | 分期計畫建立 |
| `finance.installment.completed` | 分期全部完成 |
| `finance.installment.due` | 單期到期（cron RETURNING id，只發一次 batch event） |
| `finance.installment.cancelled` | 分期取消 |
| `finance.transfer.completed` | 轉帳完成（兩錢包餘額+txn 寫入後才發） |
| `finance.privacy.toggled` | 隱密狀態變更 |

**事件韌性**（[AD-10](../../docs/architecture/event-resilience-patterns.md)）：適用 P1+P2+P5。

| 分類 | 事件 | TTL | dedup key |
|------|------|-----|-----------|
| durable | transaction.* / wallet.* / installment.created/completed/cancelled / transfer.completed / privacy.toggled | 0 | 業務 ID |
| idempotent | budget.exceeded / installment.due | 5min | 複合鍵（space+period / plan+number） |

所有 handler 搭配 `ON CONFLICT DO NOTHING`（P2），EventBus publish 走 fire-and-forget（P5）。

## 餘額一致性

| 場景 | 更新公式 |
|------|---------|
| 新增交易 | `current_balance -= amount` |
| 更新交易 | `current_balance -= (new - old)` |
| 刪除交易 | `current_balance += amount` |
| 轉帳 | SELECT FOR UPDATE（sorted IDs）+ 同一 DB transaction |
| 取消分期 | 回滾 scheduled 期的餘額影響 |
| Sync | snapshot difference → 使用者確認後覆寫 |

TransactionService override `create()`/`update()`/`delete()` 執行差量更新，不改 base class hook 簽名。

## 冷熱資料策略

對齊 Workshop 4-Phase 慣例（同 memvault/intelflow）。

| 溫度 | 條件 | 存放 | 查詢 |
|------|------|------|------|
| Hot | 近 12 個月 | 主表 + partial index | 完整 SQL |
| Warm | 12-24 個月 | 主表 | 完整 SQL（略慢） |
| Cold | > 24 個月 | `transactions_archive` + S3 | ILIKE fallback |

- Phase 1: Partial indexes（Phase A 同步）
- Phase 2: `transactions_archive` 表（Phase G 後）
- Phase 3: S3 歸檔（附件已在 RustFS，cold notes 壓縮至 S3）
- Phase 4: 擴充 `scripts/archive_cold_data.py`（`--dry-run` 預設）
- 歸檔排除：`scheduled` / `pending` / 關聯 active installment_plan
- API 預設查主表，`include_archived=true` 觸發 UNION 查詢

## 目錄結構

```
core/src/modules/finance/
├── __init__.py
├── routes.py         # 所有 API 端點
├── models.py         # transactions, categories, subscriptions, budgets,
│                     # attachments, tags, wallets, wallet_snapshots, installment_plans
├── schemas.py        # Pydantic request/response
├── services.py       # 公開 API（交易 CRUD、分類管理、預算邏輯、分析計算、
│                     # 錢包管理、分期管理、轉帳、隱密過濾、對帳引擎）
├── events.py         # finance.transaction.created, finance.wallet.synced 等
├── deps.py           # 交易權限驗證
├── storage.py        # RustFS 上傳/下載（S3 compatible）
└── reports.py        # 月度報告產生（LLM 整合）
```

## 參考文件

- [P5 藍圖](../../docs/blueprint/p5-finance.md) — 完整 DB schema + MCP tools 設計
- [服務目錄](../../docs/vision/domain-catalog.md) — finance 定位
