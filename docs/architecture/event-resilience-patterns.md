# 事件韌性模式 (Event Resilience Patterns)

> 從 Hook Observatory 實戰中提煉的 6 個通用架構模式，適用於 Workshop 全域。
>
> **前置閱讀**：[event-driven.md](./event-driven.md)（事件格式、命名規範、EventBus API）

---

## 概要

Workshop 的事件驅動架構（AD-6）定義了事件的格式與傳遞規則，但未涵蓋事件在「不理想情境」下的行為——系統崩潰、事件堆積、過期事件重播、caller 被阻塞。本文件補完這些模式，形成完整的事件韌性策略。

| 模式 | 解決的問題 | 適用場景 |
|------|-----------|---------|
| [P1 事件時效分類](#p1-事件時效分類-event-temporal-classification) | 不是所有事件都該永久保存 | 任何產生事件的模組 |
| [P2 冪等投影](#p2-冪等投影-idempotent-projection) | 重複處理不能產生副作用 | 所有事件消費端 |
| [P3 WAL-Projection 分離](#p3-wal-projection-分離) | DB 掛了 ≠ 事件遺失 | 需要零遺失保證的管線 |
| [P4 Checkpoint Recovery](#p4-checkpoint-recovery) | 崩潰後從正確位置繼續 | 批次處理、spool drainer |
| [P5 非阻塞隔離](#p5-非阻塞隔離-non-blocking-isolation) | 下游故障不阻塞上游 | Hook、Bridge、通知管線 |
| [P6 層級式過載保護](#p6-層級式過載保護-tiered-backpressure) | burst 流量不壓垮系統 | 高頻事件生產者 |

---

## P1 — 事件時效分類 (Event Temporal Classification)

### 問題

事件驅動系統往往預設所有事件同等重要。但實際上，一個 TTS 語音通知在 10 秒後已經毫無意義，而一筆交易記錄則必須永久保存。當系統崩潰後恢復時，如果不分青紅皂白地重播所有事件，就會出現「播放 5 分鐘前的語音通知」這種荒謬行為。

### 模式

將每個事件歸入三個語意類別之一：

| 類別 | TTL | 崩潰後行為 | 典型範例 |
|------|-----|-----------|---------|
| **ephemeral**（轉瞬即逝） | 2-30s | 過期丟棄 | UI 刷新、TTS 通知、即時信號 |
| **durable**（持久保存） | ∞ | 永遠重播 | 統計計數、audit log、交易記錄 |
| **idempotent**（冪等操作） | 30s-5min | TTL 內安全重播 | 外部 API webhook、帶 dedup key 的寫入 |

### 規則

1. **預設 TTL = 0**（durable）——向後相容，不會意外丟棄事件
2. 新事件類型**必須明確宣告** TTL，並記錄在配置中
3. **ephemeral 事件必須帶 `ts` 欄位**——TTL 計算依賴精確的事件時間戳
4. Recovery 時，TTL 過濾發生在 **讀取後、投影前**——確保 ephemeral 事件不會在崩潰後被重播

> **⚠️ 簡化提醒**：TTL 分類在概念上是正確的，但對個人工作站的統計監控場景而言是過度設計。
> Hook Observatory 的實戰結論是：全部事件預設 durable（TTL=0），空間管理用定期 SQL DELETE 即可。
> 只在事件量 > 100K/day 或有明確的 ephemeral 語意需求時，才引入 TTL 分類機制。

### Workshop 應用

| 模組 | 事件 | 建議 TTL | 理由 |
|------|------|---------|------|
| finance | `transaction.created/updated/deleted` | durable (0) | 金流紀錄永久保存 |
| finance | `wallet.synced/reconciled` | durable (0) | 對帳記錄永久保存 |
| finance | `installment.created/completed/cancelled` | durable (0) | 分期事實永久保存 |
| finance | `transfer.completed` | durable (0) | 轉帳紀錄永久保存 |
| finance | `privacy.toggled` | durable (0) | audit trail |
| finance | `budget.exceeded` | idempotent (5min) | 同預算週期去重，避免重複通知 |
| finance | `installment.due` | idempotent (5min) | cron 可能重跑，需冪等 |
| memvault | `memory.extracted` | durable (0) | 記憶擷取結果需持久化 |
| taskflow | `task.assigned` | durable (0) | 派工紀錄 |
| bridge | `notification.sent` | ephemeral (10s) | 通知已送，重播無意義 |
| hook-observatory | `PreToolUse` | durable (0) | 統計用途 |

---

## P2 — 冪等投影 (Idempotent Projection)

### 問題

在分散式系統中，「exactly-once delivery」是不可能實現的理論目標。實際上只能做到 at-least-once——同一事件可能被處理多次（網路重試、崩潰恢復、重新部署）。如果事件處理有副作用（例如重複插入記錄、重複扣款），系統就會進入不一致狀態。

### 模式

**At-least-once delivery + Idempotent handler = Exactly-once semantics**

每個事件攜帶一個**去重鍵 (dedup key)**，消費端用 `ON CONFLICT DO NOTHING` 確保重複處理不產生副作用。

### 去重鍵設計

```
dedup_hash = SHA256(event_type + timestamp + payload[:200])[:16]
```

| 策略 | 適用場景 | 碰撞風險 |
|------|---------|---------|
| **內容雜湊** (content hash) | 無外部 ID 的事件（hook、log） | 極低（16 hex chars = 64 bits） |
| **業務 ID** (natural key) | 有唯一業務 ID 的實體（transaction_id, task_id） | 零 |
| **複合鍵** (composite key) | 跨模組事件（source_module + entity_id + event_type） | 零 |

### 實裝要點

```sql
-- PostgreSQL: UNIQUE 約束 + ON CONFLICT
CREATE UNIQUE INDEX idx_events_dedup ON events (dedup_hash);

INSERT INTO events (..., dedup_hash) VALUES (..., 'abc123...')
ON CONFLICT (dedup_hash) DO NOTHING;  -- 冪等！
```

```python
# Python: handler 層面的冪等
async def handle_transaction_created(event: Event):
    existing = await repo.get_by_dedup_key(event.dedup_key)
    if existing:
        return  # 已處理，跳過
    await repo.create(...)
```

### 規則

1. 所有事件 handler **必須是冪等的**——處理同一事件兩次 = 無副作用
2. 去重鍵的選擇取決於業務語意，而非技術便利
3. 去重鍵的 TTL 應 ≥ 事件本身的 TTL（避免去重視窗過期後的重複處理）
4. 去重表可以定期清理（例如 30 天前的去重記錄可安全刪除）

---

## P3 — WAL-Projection 分離

### 問題

當事件直接寫入 DB 時，DB 故障 = 事件遺失。in-memory queue 更危險——進程崩潰時 queue 中的所有事件全部消失。對於統計、audit log 等不能丟失的事件來說，這是不可接受的。

### 模式

借鑑資料庫的 WAL (Write-Ahead Log) 概念，將事件分為兩層：

```
Source of Truth:  磁碟上的不可變日誌（JSONL 檔案）
Projection:       DB 中的結構化投影（用於查詢和統計）
```

**事件先寫日誌，再投影到 DB**。日誌是不可變的 source of truth；DB 是可重建的衍生物。

```
事件 → append JSONL (WAL)  →  SpoolDrainer  →  batch INSERT (Projection)
          ~0.1ms                  1s interval         可重建
```

### 適用判斷

| 條件 | 是否需要 WAL-Projection |
|------|----------------------|
| 事件遺失可接受（UI 更新、debug log） | 不需要，直接 in-memory queue |
| 事件遺失不可接受（交易、audit、統計） | **需要** |
| 已有外部持久化（Redis Streams、Kafka） | 不需要自建，善用外部保證 |

### 為何不用 Redis / Kafka？

| 方案 | 優點 | 缺點 | 結論 |
|------|------|------|------|
| **JSONL spool + cursor** | 零依賴、crash-safe、可完整重建 | 延遲 ~1s | 單服務、中低吞吐量首選 |
| Redis Stream | 持久化、原子操作 | 額外服務依賴 | 多消費者場景 |
| Kafka / NATS | 高吞吐、多 consumer | 運維複雜度高 | 大規模分散式場景 |
| asyncio.Queue | 延遲最低 | **崩潰時遺失全部事件** | 僅限可接受遺失的場景 |

**Workshop 現階段決策**：單人工作站 + 10 Core Modules，JSONL spool 足以覆蓋所有需要零遺失保證的場景。但 spool 不需要完整的 WAL 狀態機——當冪等投影（P2）已到位時，簡單的「rename → INSERT → delete」流程已足夠。`.processing → .done` 狀態機和 cursor checkpoint 是在 P2 不存在時才需要的防護。

### 規則

1. WAL 檔案是 **append-only**、**不可變的**——寫入後永不修改
2. DB 投影是 **可重建的**——提供 admin/rebuild 端點，從 WAL 完整重建
3. WAL 保留策略：活躍檔案 → 已處理（.done）→ 歸檔（7 天後移至 archive/）→ 可選清除
4. 不要在 WAL 與 Projection 之間引入額外的 in-memory 中間層——增加崩潰遺失面

---

## P4 — Checkpoint Recovery

### 問題

批次處理如果在中途崩潰，重啟後如何知道「上次處理到哪裡了」？如果從頭重新處理，效率低且可能產生副作用（即使有冪等保護，也浪費資源）。

### 模式

使用 **cursor checkpoint** 記錄最後成功處理的位置，搭配 **檔案狀態機** 確保每個步驟的崩潰都可安全恢復。

```
檔案狀態機:
  .jsonl       →  .processing  →  batch INSERT  →  .done
  (活躍寫入)      (原子重命名)      (冪等寫入)       (歸檔)

cursor.json:
  { "last_file": "...", "last_processed_at": "...", "total_events_processed": N }
```

### 崩潰場景分析

| 崩潰時機 | 檔案狀態 | 恢復方式 | 事件遺失 |
|----------|---------|---------|---------|
| 寫入 WAL 中途 | JSONL 部分行 | 跳過 malformed 行 | 最多 1 條 |
| rename 前 | .jsonl 完好 | 正常處理 | 0 |
| INSERT 前 | .processing 存在 | startup re-process | 0（durable）/ 過期丟棄（ephemeral） |
| INSERT 後、cursor 更新前 | .processing 存在 | re-process，冪等 INSERT | 0 |
| cursor 更新後、.done 前 | .processing 存在 | re-process，冪等 INSERT | 0 |

### 規則

1. Cursor 只在**成功投影後**才更新——永遠不要提前移動 cursor
2. Startup 時先掃描 `.processing` 檔案——這些是上次崩潰的遺留
3. 搭配 P2（冪等投影）——re-process 不會產生重複資料
4. 搭配 P1（事件時效）——re-process 時 ephemeral 事件自動過期丟棄

> **⚠️ 簡化條件**：如果 P2（冪等投影）已完整實作，P4 的大部分機制可以簡化。
> dedup_hash + ON CONFLICT DO NOTHING 本身就是 crash safety —— 重播整個檔案不會產生重複資料。
> 此時 checkpoint 的價值退化為「避免重複工作」（效能優化），而非「避免資料錯誤」（正確性保證）。
> 對低吞吐量場景（< 1K events/day），重播的效能成本可忽略，P4 可安全省略。

---

## P5 — 非阻塞隔離 (Non-Blocking Isolation)

### 問題

事件生產者（hook、API handler、UI action）如果同步等待事件處理完成，下游的任何故障都會直接阻塞上游。在 Claude Code hook 的場景中，一個 50ms 的 curl 呼叫就會讓每次工具使用都慢 50ms——累積起來嚴重影響體驗。

### 模式

**三層隔離設計**：

```
Layer 1: Fire-and-forget (caller)
  └─ 做最少的事（file append / queue push），立即返回
  └─ 延遲目標: < 1ms

Layer 2: Background drain (processor)
  └─ 非同步輪詢，批次處理
  └─ 延遲可接受: 1-5s

Layer 3: Downstream services (consumers)
  └─ 可獨立故障，不影響 Layer 1-2
```

### 允許 vs 禁止（Layer 1 — caller 端）

| 允許（< 1ms） | 禁止 |
|--------------|------|
| File append | 同步網路請求（curl、HTTP） |
| 環境變數讀取 | 同步 DB 寫入 |
| JSON 建構（printf、jq） | 等待外部服務回應 |
| Background subprocess（`& disown`） | sleep 或任何延遲 |

### 優雅降級矩陣

| 失敗場景 | 行為 | 對 caller 影響 |
|----------|------|--------------|
| Layer 2 processor 未啟動 | 事件堆積在 spool / queue | 零影響，啟動後消費 |
| Layer 3 DB 掛掉 | Layer 2 重試（指數退避） | 零影響 |
| Spool 磁碟滿 | Layer 1 silent fail | 零影響 |
| Queue overflow | 丟棄最舊事件 / 返回 429 | 零影響（fire-and-forget） |

### 規則

1. **鐵律**：事件管線的任何故障都**不可**影響 caller 的正常運作
2. Layer 1 的延遲預算 < 1ms——超過就需要重新設計
3. 使用 `& disown` 啟動 background process 時，注意進程累積——設定上限或使用 pool
4. 網路呼叫**只能出現在 Layer 2+**——Layer 1 必須是純本地操作

### Workshop 應用

| 場景 | Layer 1 | Layer 2 | Layer 3 |
|------|---------|---------|---------|
| Hook 事件 | bridge → spool append | SpoolDrainer → batch INSERT | Dashboard query |
| EventBus publish | in-process queue push | async handler execution | 跨模組 side effects |
| Bridge 通知 | webhook 佇列寫入 | 定期批次送出 | LINE/Telegram API |

---

## P6 — 層級式過載保護 (Tiered Backpressure)

### 問題

當事件 burst（突發大量事件）發生時，如果沒有保護機制，每一層都可能被壓垮——queue 溢出、DB 連線池耗盡、下游 API 被 rate limit。

### 模式

在每一層獨立設置流量控制，越靠近 caller 的層級越寬鬆，越靠近持久化的層級越嚴格：

| 層級 | 機制 | 參數 | 行為 |
|------|------|------|------|
| **入口層** | 寫入限制 | 磁碟容量 / queue max_size | 滿了就 silent fail 或 429 |
| **處理層** | 輪詢間隔 + 批次大小 | drain_interval, batch_size | 自然限流，不會 overwhelm DB |
| **持久層** | 連線池 + 冪等約束 | pool_size, ON CONFLICT | DB 自我保護 |
| **歸檔層** | 時間閾值 | archive_after_days | 長期資料不佔主表空間 |

### 批次大小設計原則

```
batch_size = 連線池可承受的單次寫入量
drain_interval = 可接受的最大投影延遲

吞吐量上限 = batch_size / drain_interval
例: 100 events / 1s = 100 events/s — 對個人工作站綽綽有餘
```

### 規則

1. 每一層的保護機制**獨立運作**——不依賴上游的限流
2. 入口層**永遠不阻塞**——寧可丟事件也不阻塞 caller（參見 P5）
3. 處理層使用**指數退避**處理下游故障——1s → 2s → 4s → 8s → cap at 60s
4. 監控每層的佇列深度——佇列持續增長 = 處理速度 < 生產速度，需要介入

---

## 模式交互關係

```
               P1 時效分類
                  │
                  ▼
事件產生 ──► P5 非阻塞隔離 ──► P3 WAL 寫入 ──► P4 Checkpoint
               │                    │               │
               │                    ▼               ▼
               │              P2 冪等投影 ──► DB Projection
               │
               ▼
          P6 過載保護（貫穿全鏈路）
```

- **P1 + P4**：Recovery 時，ephemeral 事件被 P1 的 TTL 過濾丟棄——這是正確行為
- **P2 + P4**：Recovery 時可能重複 INSERT，但 P2 的冪等約束確保不會重複
- **P3 + P4**：WAL 是 source of truth，cursor 追蹤投影進度，兩者結合實現 crash-safe
- **P5 + P6**：P5 確保 caller 不被阻塞，P6 確保 burst 不壓垮下游
- **P1 + P6**：ephemeral 事件在 burst 時可優先丟棄（它們本來就有 TTL）

---

## 決策矩陣：你的場景需要哪些模式？

回答以下問題，決定需要實作哪些模式：

| 問題 | 是 | 否 |
|------|:--:|:--:|
| 事件遺失會造成業務問題？ | → P3 (WAL) + P4 (Checkpoint) | → asyncio.Queue 足矣 |
| 相同事件可能被處理兩次？ | → P2 (冪等) | — |
| 有些事件過期後沒意義？ | → P1 (時效分類) | → 全部 durable |
| 事件生產者對延遲敏感？ | → P5 (非阻塞) | → 同步處理 OK |
| 可能出現 burst 流量？ | → P6 (過載保護) | — |

### 各模組建議

| 模組 | P1 | P2 | P3 | P4 | P5 | P6 | 備註 |
|------|:--:|:--:|:--:|:--:|:--:|:--:|------|
| hook-observatory | — | ✅ | ✅ | — | ✅ | ✅ | |
| finance EventBus | ✅ | ✅ | — | — | ✅ | — | dedup: 業務ID / 複合鍵（budget+installment.due） |
| memvault extraction | ✅ | ✅ | — | — | ✅ | — | |
| bridge notification | ✅ | — | — | — | ✅ | ✅ | |
| intelflow pipeline | ✅ | ✅ | ✅ | ✅ | — | — | |

---

## 參考實作

- **Hook Observatory** (`stations/hook-observatory/spool.py`)：P2+P3+P5+P6 簡化實作（dedup_hash 取代 P4 狀態機，P1 TTL 延後）
- **EventBus** (`core/src/events/bus.py`)：P5 (fire-and-forget) 的核心實作
- **Memvault 冷熱分層** (`scripts/archive_cold_data.py`)：P6 歸檔層的參考

---

## 附錄 A：持久化層的故障矩陣

「用 Redis Streams 取代 local spool」看似合理——但 Redis 本身也會 crash。

### Redis 持久化的真相

Redis AOF（Append-Only File）有三種 fsync 策略：

| 策略 | 崩潰時資料遺失 | 效能影響 | 預設？ |
|------|-------------|---------|------|
| `appendfsync no` | OS flush 間隔（秒級） | 最快 | 否 |
| `appendfsync everysec` | **最多 1 秒** | 輕微 | **是** |
| `appendfsync always` | 零 | 慢 10-100x | 否 |

### 故障場景全景比較

| 故障場景 | Local Spool (JSONL) | Redis Streams (預設) | 兩者並用 |
|----------|:--:|:--:|:--:|
| App 崩潰 | ✅ 檔案在磁碟 | ✅ Redis 還活著 | ✅ |
| Redis 崩潰 | ✅ 不依賴 Redis | ❌ 丟最多 1s | ✅ spool 有 |
| Redis OOM kill | ✅ 不依賴 Redis | ❌ in-flight 遺失 | ✅ spool 有 |
| PostgreSQL 掛 | ✅ spool 不受影響 | ✅ Redis 不受影響 | ✅ |
| 突然斷電 | ⚠️ 最多丟 1 行 | ❌ 丟最多 1s | ⚠️ 最多丟 1 行 |
| 磁碟故障 | ❌ | ❌（同機器） | ❌ |

### 核心洞察

**Local spool 的依賴鏈最短：App → 檔案系統。** 只要磁碟沒壞，事件就在。

**Redis 多了一層：App → Redis 進程 → Redis AOF → 檔案系統。** 中間任何一環出問題（Redis 進程被 OOM kill、AOF 還沒 fsync、Redis 配置錯誤），事件就可能丟失。

把一個你完全掌控的持久層（file append）「退役」為一個有獨立故障模式的外部服務，不是降低風險——是換了一個你更不可控的風險點。

### 正確的分層策略

根據事件的業務關鍵程度，選擇不同的持久化深度：

```
關鍵事件（finance、audit）：
  App → Local Spool → SpoolDrainer → Redis Stream → Consumer → DB
  │                                    │
  └─ 第一道防線（零外部依賴）              └─ 第二道（多消費者支援）

標準事件（EventBus 跨模組）：
  App → Redis Stream → Consumer → DB
  └─ Redis 持久化足夠（丟 1s 可接受）

可丟棄事件（UI 刷新、debug）：
  App → asyncio.Queue → Handler
  └─ 崩潰就丟，無所謂
```

### 修正後的 Phase 演進表

| Phase | 事件傳輸 | 標準事件 P3/P4 | 關鍵事件 P3/P4 |
|-------|---------|:--:|:--:|
| Phase 1 (In-process) | asyncio.Queue | 需要 P3+P4 | 需要 P3+P4 |
| Phase 2 (Redis Streams) | Redis 持久化 | 可免（丟 1s 可接受） | **仍需保留**（零遺失要求） |
| Phase 3 (NATS JetStream) | NATS 持久化 | 可免 | 視 NATS 部署拓撲而定 |

### 決策原則

> **不要用「這個外部服務有持久化」來省略自己的持久化。**
> 問自己：「如果這個外部服務完全消失，我的事件還在嗎？」
> 如果答案是「不在」，而且你不能接受——就需要保留 local spool。

**P1（時效分類）、P2（冪等）、P5（非阻塞）、P6（過載保護）在所有 Phase、所有場景都需要，永不退役。**
