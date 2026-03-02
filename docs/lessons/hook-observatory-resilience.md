# Hook Observatory — 事件韌性設計經驗

> 日期：2026-02-28
> 來源：Hook Observatory 設計與實作過程中的多輪迭代

## 背景

設計 Hook Observatory 時，最初方案是 hook → curl POST → in-memory queue → DB。經過多輪 review 暴露出 4 個致命問題，逐一解決後形成了 6 個通用模式（已文件化至 `docs/architecture/event-resilience-patterns.md`）。

## 關鍵教訓

### 1. in-memory queue 是隱性資料遺失陷阱

**初始設計**：hook → HTTP POST → asyncio.Queue → batch INSERT

**問題**：進程崩潰時 queue 中的事件全部消失。對統計類事件來說「偶爾丟幾筆」看似可接受，但長期累積後統計結果失真，且無法追查原因。

**修正**：移除 in-memory queue，所有路徑（bridge + API POST）統一先寫入磁碟 spool（JSONL），由 SpoolDrainer 非同步消費。只要磁碟寫入成功，事件就不會丟。

**教訓**：**如果你需要持久化保證，永遠不要把 in-memory 結構當作唯一的傳輸管道。**

### 2. Hook 阻塞是效能的隱形殺手

**初始設計**：bridge.sh 用 `curl --connect-timeout 1` 呼叫 API

**問題**：
- connect-timeout=1s 但 response 可能更慢
- PreToolUse hook 在每次工具呼叫都執行，1 次 50ms = 100 次工具呼叫浪費 5 秒
- 目標 server 沒開時仍嘗試連線（1s timeout × N 次）

**修正**：bridge 完全移除網路呼叫，改為 file append（< 0.1ms）。零網路 = 零等待 = 零外部依賴。

**教訓**：**高頻路徑上的每一毫秒都有放大效應。Hook / middleware / interceptor 的延遲預算應以微秒計。**

### 3. 事件不是生而平等的

**初始設計**：所有事件同等對待（全部持久保存 + 崩潰恢復時全部重播）

**問題**：TTS 語音通知在 10 秒後重播 = 荒謬。但交易記錄不能丟。用同一套策略處理所有事件，必然在某些場景過度、某些場景不足。

**修正**：引入 ephemeral / durable / idempotent 三級分類 + TTL 配置。Recovery 時 TTL 過濾器自動丟棄過期事件。

**教訓**：**設計事件系統時，第一個問題不是「怎麼傳」而是「這個事件的生命週期是什麼」。**

### 4. 冪等不是可選的——它是崩潰恢復的前提

**初始設計**：INSERT 不帶 dedup，依賴「每個事件只處理一次」的假設

**問題**：崩潰恢復時必然重新處理 .processing 檔案中的事件。如果 INSERT 不是冪等的，重新處理 = 重複資料。

**修正**：每個事件計算 dedup_hash（SHA256[:16]），INSERT 用 ON CONFLICT DO NOTHING。

**教訓**：**崩潰恢復和冪等是一體兩面。如果你設計了 recovery 機制但沒有冪等保護，recovery 本身就會製造問題。**

## 設計演進時間線

```
V1: hook → curl POST → asyncio.Queue → DB
    問題：阻塞 + 崩潰遺失 + 全量重播

V2: hook → curl POST → spool JSONL → SpoolDrainer → DB
    問題：curl 仍阻塞 + 無 TTL + 無冪等

V3: hook → file append (spool) → SpoolDrainer → DB
    改善：零網路、TTL 分類、dedup_hash、checkpoint recovery

V4: hook → file append (spool) → SimpleDrainer → DB
    簡化：移除狀態機 + cursor + TTL + archive
    安全網：dedup_hash + ON CONFLICT DO NOTHING
    = 三方辯論後的最終方案
```

### 5. 「外部服務有持久化」不等於「你可以省略自己的持久化」

**初始假設**：Redis Streams 有 AOF 持久化，所以升級到 Phase 2 後 local spool 可以退役

**問題**：Redis 預設 `appendfsync everysec`——crash 時最多丟 1 秒。Redis OOM kill、AOF 配置錯誤、Redis 進程意外死亡，都會造成事件遺失。Local spool 的依賴鏈是 App → 檔案系統（1 層），Redis 是 App → Redis 進程 → Redis AOF → 檔案系統（3 層），中間任何一環斷裂都比你多丟資料。

**修正**：依據事件關鍵程度分層——關鍵事件（finance、audit）即使有 Redis 仍保留 local spool 作為第一道防線；標準事件可以只依賴 Redis。

**教訓**：**在決定「可以退役某個持久層」之前，問自己：如果那個外部服務完全消失，我的事件還在嗎？如果不在且不可接受——就不能退役。**

### 6. 解決同一個問題兩次 = 過度設計

**設計**：`.processing → .done` 三段式狀態機 + `dedup_hash` + `ON CONFLICT DO NOTHING`

**問題**：兩者解決的是同一個問題——「crash 後重播不會產生重複」。狀態機確保「不需要重播」，dedup_hash 確保「重播了也沒事」。同時存在時，狀態機的價值趨近於零。

**三方辯論結論**：
- YAGNI 派：5 個活動部件太多，asyncio.Queue 就夠了
- 可靠性派：每一層都對應一個真實的故障模式
- **務實派（勝出）**：dedup_hash 是真正的安全網，狀態機是它的不必要替身

**修正**：移除 `.processing/.done` 狀態機、cursor.json、TTL 分類、archive 機制。保留 spool JSONL + dedup_hash + 簡單 drain loop。7 部件 → 4 部件。

**教訓**：**在增加新的防護層之前，檢查現有的防護是否已覆蓋相同的故障模式。兩層防護 ≠ 兩倍安全，它是兩倍複雜度 + 接近零的額外安全。**

## 通用化

上述 6 個教訓已被抽象為 6 個架構模式（P1-P6），文件化在：
- **架構模式**：`docs/architecture/event-resilience-patterns.md`
- **架構決策**：`docs/architecture/architecture-decisions.md` (AD-10)
