# Phase 5B — line_reader 獨立對抗驗證（六鐵律）

**Test adversary agent**: `line-reader-test-adversary`（不讀 src/line.rs 實作）
**寫測數**: 34 個 invariant tests（`tests/line_invariants.rs`, 553 行）
**Pre-existing test file**: `tests/line_test.rs`（Phase 3d 寫的）

---

## 結果：34/34 invariant 測試全過 + 1 個 pre-existing test FAIL

- **`tests/line_invariants.rs`**: 34/34 ok — 但其中多個 assertion **確認 bug 存在**（用負面測試鎖定 bug 症狀）
- **`tests/line_test.rs::test_extract_survey_urls_fallback_order`**: FAIL — 直接暴露 bug

---

## 🔴 Bug C1：CGWindowID 來源錯誤（Critical — 整個 LINE OCR 管道不可用）

**Python 原版** (`line_reader.py:107-118`)：
```python
import Quartz
windows = Quartz.CGWindowListCopyWindowInfo(
    Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
)
for w in windows:
    if w.get("kCGWindowOwnerName") == "LINE" and w.get("kCGWindowName"):
        return int(w["kCGWindowNumber"])   # ← 系統 CGWindowID
```

**Rust 版** (`line.rs:113-129`)：
```rust
const SCRIPT_GET_WID: &str = r#"tell application "System Events"
    tell process "LINE"
        if (count of windows) > 0 then
            return id of front window       # ← AXWindow id (process-scoped)
        end if
    ..."#;
```

**問題**：
- AppleScript `id of front window` 回傳的是 **System Events 的 AXWindow ID**（process-scoped UUID-like integer）
- `screencapture -l <wid>` 需要的是 **系統全局 CGWindowID**（Quartz `kCGWindowNumber`）
- 這兩個數字**完全不同**，餵錯 id 給 `screencapture -l` 會直接失敗

**後果**：整個 `fetch_latest_survey_urls` 第一步 `get_line_window_id()` 之後的 `capture_line_window(wid)` 會**永遠 return None**，LINE OCR 完全不 work。

**修法**：用 `core-graphics` crate 呼叫 `CGWindowListCopyWindowInfo` 或寫 Swift 小工具 subprocess。預估 1-2 小時。

**測試覆蓋**:
- `test_window_id_script_does_not_use_quartz_cg_window_number` — 確認 Rust 沒使用 Quartz API
- `test_script_activate_structure_matches_python_oracle` — 未觸發（因為 script 結構差異在另一 const）

---

## 🟠 Bug H1：Community navigation 沒實作（High）

**Python 原版**：`_SCRIPT_ACTIVATE` 包含「activate LINE → 點選聊天 → 搜尋 community_name → 點擊 community」多步驟，使用 `community_name` 參數。

**Rust 版**：
```rust
pub fn activate_line_and_go_to_community(name: &str) -> bool {
    tracing::debug!("activating LINE for community '{}'", name);
    run_osascript(SCRIPT_ACTIVATE, 15).is_some()
    //                 ^^ name 只出現在 log，沒真正用到
}
```

`SCRIPT_ACTIVATE` 是 **`&'static str`**，**結構上不可能**包含 runtime 的 `name` 值。

**後果**：抓到的視窗可能是 LINE **最後活躍的聊天室**，不保證是「微光早餐會」社群。若 LINE 當下開在私聊，OCR 會抓錯視窗內容，找不到 SurveyCake URL。

**測試覆蓋**:
- `test_activate_community_name_param_not_embedded_in_script` — 確認 name 結構性無法嵌入
- `test_script_activate_has_no_community_navigation` — 確認 SCRIPT_ACTIVATE 不含「社群」字樣

**修法**：改 `SCRIPT_ACTIVATE` 為 `fn build_activate_script(name: &str) -> String`，動態 embed 搜尋 + 點擊步驟。預估 1-2 小時。

---

## 🟡 Bug M1：URL reassembly 把相鄰 URL 誤合（Medium，**繼承自 Python 原版**）

Python `line_reader.py:431`:
```python
if merged and re.match(r"^(w{2,3}\.|https?://|surveycake|[A-Za-z0-9]{3,8}$)", stripped):
    merged[-1] += stripped
```

同樣邏輯寫進 Rust `line.rs:264-274`。

**症狀**：
```
input:  "https://www.surveycake.com/s/First\nhttps://www.surveycake.com/s/Second"
output: 合併成 "https://www.surveycake.com/s/Firsthttps://www.surveycake.com/s/Second"
regex 只抓第一個 → 回傳 `"https://www.surveycake.com/s/Firsthttps"` (!)
```

`r"^(...|https?://|...)"` 這個 alternative 是錯的 — 它把完整 URL 誤判為 continuation。

**後果**：若 OCR 結果兩個 URL 剛好相鄰（中間無時戳/說話人分隔），會丟失第二個 URL。

**實務影響**：**低**。LINE 訊息通常有時戳/頭像分隔，這 edge case 很少發生。但 adversarial test `test_extract_survey_urls_fallback_order` 剛好 trigger。

**修法**：移除 `https?://` alternative（完整 URL 就該是獨立 line）。10 分鐘。
```rust
// Before
r"^(w{2,3}\.|https?://|surveycake|[A-Za-z0-9]{3,8}$)"
// After
r"^(w{2,3}\.|surveycake|[A-Za-z0-9]{3,8}$)"
```

**注意**：此 bug 同時存在於 Python 原版。根據 `feedback_no_rerun_old.md` "No retroactive fixes"，Python 版**不主動修**，但 Rust 版既然要更正，可同步修正 Python 原版（少爺決定）。

---

## Cutover 阻擋評估

| Bug | 影響 cutover 嗎？ |
|---|---|
| **C1** CGWindowID | ⚠️ **部分阻擋** — Rust service 啟動正常，但若有 API 呼叫觸發 `fetch_latest_survey_urls`，會回傳空陣列 |
| **H1** Community nav | ⚠️ **部分阻擋** — 同上 |
| **M1** URL merge | ❌ 不阻擋 |

### 現行 cronicle 流程分析

週三/五 13:00 的 `ws-auto-survey-wed/fri` 仍呼叫 **Python** `ws_auto_survey.py`，該 runner 用 Python `line_reader.py`（原版，已知 quirk 外正常運作）。**Rust 版的 `line.rs` 目前沒有任何生產路徑呼叫到**（`/api/run` 只接受外部提供的 URL，不自行抓 LINE）。

### 結論

**技術上可以 cutover**，因為：
1. Rust 服務 `/status`、`/api/run`、CRUD endpoints 都正常
2. LINE OCR 由 Python runner 做，不經過 Rust line.rs
3. Bug C1/H1 只在有人顯式觸發 Rust `fetch_latest_survey_urls` 才會爆

**但必須標記 line.rs 為 "untested in prod, use Python runner"**，並在 cutover 後 **優先修 C1 + H1**（1 天內）再啟用任何 Rust 直呼 LINE 的路徑。

---

## 六鐵律檢查表

| 鐵律 | 是否遵守 |
|---|---|
| 1. Mutation score not coverage | ✅ 寫了 mutation probe（如 `test_crop_params_mutation_probe_055_coefficient`） |
| 2. 寫測分離 | ✅ 用獨立 test-adversary agent，禁止讀實作 |
| 3. Invariants not fixed I/O | ✅ crop_params 驗證 width conservation、minimum bounds |
| 4. Runtime → regression | N/A（尚未 prod runtime 資料） |
| 5. Mock 只限外部 I/O | ✅ osascript/screencapture/sips 不 mock，skip 成 const 驗證 |
| 6. AI 測試是草稿 | ✅ 發現 3 個 bug 證明原始 AI 測試不足夠 |
