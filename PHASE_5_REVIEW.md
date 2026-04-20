# Phase 5 Adversarial Review — auto-survey-rs

**Reviewer**: Claude (主控 agent，自行 review 因 sub-agent 超時)
**LOC**: 4697 行（src: ~3200，tests: ~989）
**日期**: 2026-04-19

---

## Critical（必修，阻擋 cutover）

### C1. URL hash 演算法不一致 — **data integrity bug**

Python `recon.py:133`：
```python
url_hash = hashlib.md5(url.encode()).hexdigest()   # MD5, 32 chars
```

Rust `recon.rs:206`：
```rust
let url_hash = sha256_hex(url);                    # SHA-256, 64 chars
```

**後果**：
- 舊 PG 資料 `url_hash` 為 MD5，遷移到 SQLite 後 Rust 查 `WHERE url_hash = ?` 用 SHA-256，**永遠找不到舊記錄**
- 同一個 survey URL 會被認定為「新 survey」→ UNIQUE 索引以 hash 作 key，不會擋
- 每次重跑會插入 duplicate survey，questions/submissions 全部斷連

**修法**：`recon.rs` 改用 MD5（加 `md5` crate 或 `md-5 = "0.10"`），或遷移腳本重算 hash。推薦前者（維持相容）：

```rust
use md5::compute;
fn url_hash(url: &str) -> String {
    format!("{:x}", compute(url.as_bytes()))
}
```

---

### C2. `Uuid::parse_str(...).unwrap_or_else(|_| Uuid::new_v4())` — 災難性吞錯

`filler.rs:387-389`、`recon.rs:380`、`orchestrator.rs` 多處：

```rust
id: Uuid::parse_str(&r.id).unwrap_or_else(|_| Uuid::new_v4()),
```

若 DB row 的 `id` 因任何原因無法 parse（遷移 bug、手動修資料、編碼錯誤），**Rust 會靜默產生全新 UUID 回傳**。後續用這個假 id 去 UPDATE / INSERT 會：
- 寫入找不到對應 row 的 WHERE 條件（update 0 rows，錯誤被吞）
- INSERT 假 id 造成幽靈 row
- Pathfinder 標記打在錯誤的 submission 上

**修法**：全改為 `?` propagation，讓 parse error 冒出，pipeline 快速失敗比 silent data corruption 好 100 倍：

```rust
id: Uuid::parse_str(&r.id).context("invalid UUID in DB")?,
```

---

### C3. Web routes 沒呼叫 orchestrator — pipeline 完全沒串通

`web.rs:552-567` 仍是 TODO：
```rust
/// TODO Phase 3c: call orchestrator::run_attendance / run_quiz when implemented.
// TODO Phase 3c: orchestrator::run_attendance(&attend_url.unwrap(), &pool, &_cfg).await
// TODO Phase 3c: orchestrator::run_quiz(&quiz_url.unwrap(), &pool, &_cfg).await
```

Phase 3b 寫完 web routes 就交給 Phase 3c，Phase 3c 只寫了 `orchestrator::run_attendance/run_quiz` 但沒回頭改 `web.rs` 把 TODO 補上。結果：**binary 能啟動、能收 POST /api/run，但實際什麼都沒做**（大量 `unused function` warnings 佐證）。

**修法**：web.rs `create_run` handler 改為實際 spawn：
```rust
tokio::spawn(async move {
    if let Some(url) = quiz_url {
        if let Err(e) = orchestrator::run_quiz(&pool, &cfg, &url, false).await {
            tracing::error!("run_quiz failed: {e:?}");
        }
    }
});
```

---

## High（上線前該修）

### H1. `is_transient_error` 覆蓋不完整

Python `_TRANSIENT_ERROR_NAMES` 列 11 種（含 `BrokenPipeError`、`ConnectionResetError`、`PoolTimeout`、`OSError errno 32` 等）。Rust 只檢查 reqwest 的 `is_connect/is_timeout/is_request/5xx`。

- `io::ErrorKind::BrokenPipe` 沒 catch → 長連線 retry 不會 trigger
- `sqlx::Error` 沒 catch → DB 瞬斷會 propagate 而非 retry

**修法**：擴充 `is_transient_error` 的 cause chain 檢查，含 `io::Error` 的 kind 判斷。

### H2. `BarkResponse` 未被使用

`notify.rs:14` 定義 `BarkResponse` 但 warnings 顯示 never constructed。代表 `send_bark` 可能只丟 request 不檢查 body（Python 版有檢查 `resp.get("code") != 200`）。

### H3. `tempfile` 清理未明確保證

`line.rs` 建 temp PNG + crop PNG。若中途 panic（osascript 超時、LINE 視窗消失），temp 檔可能殘留。Python 版用 `tmp.unlink(missing_ok=True)` 在 except 分支。

**修法**：用 `tempfile::NamedTempFile`（RAII 自動刪除），或 `Drop` 實作。

### H4. `migrate_pg_to_sqlite.py` **未執行驗證**

遷移腳本寫好了（scripts/migrate_pg_to_sqlite.py），但沒跑過。Phase 6 cutover 前必須先：
1. 在 Python DB 空集合狀態跑（驗證 script 本身無 bug）
2. 實際產生 SQLite file
3. `cargo test --test db_integration` 驗證 Rust 能讀

**若 C1 url_hash 不修**，遷移後舊資料全部「看不見」。

---

## Medium（可排到後續 iteration）

### M1. `pub const SCRIPT_*` 暴露在 public API

為了 test 把 AppleScript 三段改 pub，但這 3 個常數對外沒意義。建議用 `#[cfg(test)] pub const` 或放到專門 module。

### M2. 多處重複定義 `struct Row` inline in query_as!

可以整合到 `models.rs` 的 `SqliteRow` 型別。不急迫但未來會痛。

### M3. `CamoufoxSession` 的 `new` / `with_sid` / `run_cmd` 都標 never used → 代表**沒有任何路徑實際用到 Camoufox**。驗證整個 browser 自動化管道是否有 entry point。

### M4. CORS `permissive()` — 工時段開放所有 origin

`web.rs:276 CorsLayer::permissive()`，對 localhost 站是 OK，但若 nginx 反向代理暴露則太寬。建議限 `Origin: http://localhost:3000 / https://workshop.joneshong.com`。

### M5. 測試 5 suites 中 3 suites 不完整

- `analyzer_test`: 4/9 pass（wiremock expectations mismatch）
- `line_test`: 13/14 pass（1 edge case）
- `db_integration` / `notify_test` / `ocr_client_test`: 編譯過但沒有 test 案例 OR 全跳過

Adversarial 測試缺：空字串、特殊字元、DB connection 斷、OCR service 503、Camoufox exec 權限錯。

---

## Low（建議）

- L1. `urlencoding` crate 用得少，可用標準 `url::form_urlencoded`
- L2. `tokio-test` 已加 dev-dep 但未見使用
- L3. `orchestrator::type_name_of_error` 未被使用 — dead code
- L4. 多數 `pub` 可降為 `pub(crate)`

---

## 測試覆蓋缺口

| Module | 現有 test | 缺的 edge case |
|---|---|---|
| analyzer | wiremock 5 cases | transient retry 成功 / 全部 retry 耗盡 / 非 JSON 回應 |
| orchestrator | 無 | pathfinder < 100 / person 已 success skip / 延遲抖動 |
| filler | fill script 格式 | submit 失敗、分數抓不到、Camoufox 超時 |
| recon | parse JSON + classify | 空 subjects / 多個 company 欄位 / URL 格式異常 |
| playwright | JS transform | subprocess 逾時 / camoufox binary missing / snapshot 回傳非 JSON |
| line | regex + crop | LINE 視窗不存在 / OCR 全失敗 / 沒抓到任何 URL |
| notify | 無實際發 request | bark server 503 / device_key 無效 / body 含特殊字元 |
| ocr_client | 無 | service 未啟動 / engine 參數錯 / PDF 類型 |
| web | 無 | 401 / 409 conflict / multipart CSV malformed |
| db | 建連線 | schema version mismatch / foreign key cascade |

---

## 總評

- **LOC**: 3200 src + 989 tests + 97 migration SQL
- **品質分數**: **B-**（結構清楚，但 3 個 critical data integrity 問題 + pipeline 沒串通）
- **Cutover 建議**: **❌ 不建議 cutover**。必修 C1 + C2 + C3 三個 critical。
  - C1（url_hash 演算法）：改 MD5，10 分鐘
  - C2（unwrap_or_else Uuid）：改 `?`，10 分鐘
  - C3（web → orchestrator wire up）：15-30 分鐘
  - 加上 H4（跑 migration 驗證）：30 分鐘

**修完 3 個 critical（~1 小時）再進 Phase 6 cutover**，目前不宜直接上 production。
