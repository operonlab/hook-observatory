# PHASE 5B — line.rs Adversarial Review

獨立視角對標 Python `line_reader.py`。只讀公開簽名 + 常數，不讀實作內部。

---

## Bug 清單

### Critical

#### BUG-1: CGWindowID 來源錯誤 → `screencapture -l` 截錯視窗

**嚴重度**: Critical  
**位置**: `src/line.rs` `SCRIPT_GET_WID` constant + `get_line_window_id()`  
**症狀**: `screencapture -l <wid>` 傳入的不是真正的 CGWindowID，導致截圖失敗或截到錯誤視窗。

**根因對比**:

| | Python (`line_reader.py`) | Rust (`line.rs`) |
|---|---|---|
| API | `Quartz.CGWindowListCopyWindowInfo(...)` | `osascript "return id of front window"` |
| 回傳值 | `w["kCGWindowNumber"]` = 系統全局 **CGWindowID** | AppleScript `System Events` AXWindow element id |
| screencapture -l | ✅ 需要 CGWindowID | ❌ 得到的是 AXWindow id |

`screencapture -l` 需要 Quartz CGWindowID（`kCGWindowNumber`）。AppleScript 的 `id of front window` 回傳的是 Accessibility framework 的 element id，是完全不同的數字空間，兩者**不可互換**。

**修正方向**:
- 使用 `core-graphics` crate 的 `CGWindowListCopyWindowInfo` 取 `kCGWindowNumber`
- 或用 Swift one-liner subprocess：`swift -e 'import CoreGraphics; ...'` 列出視窗並過濾 LINE

---

#### BUG-2: `activate_line_and_go_to_community(name)` 的 `name` 參數被丟棄，社群導航完全缺失

**嚴重度**: Critical  
**位置**: `src/line.rs` line 102-105  
**症狀**: 每次執行只會把 LINE 帶到最前面並確保聊天視窗開啟，但不會導航到指定社群。OCR 截圖的對象將是 LINE 當前開著的任意視窗，而非目標社群。

**根因對比**:

Python `read_line_community(name)` 執行三段動作：
1. `_run_osascript(_SCRIPT_ACTIVATE)` — activate LINE + open chat window
2. `_click_community_tab(wid)` — 點擊「社群」tab（Quartz 座標計算）
3. `_find_and_click_community(wid, name)` — OCR 左側聊天列表，找到 `name`，double-click

Rust `activate_line_and_go_to_community(name)` 只執行第 1 步。`name` 只被印到 debug log，從未用於任何導航。

```rust
// 現狀（第 102-105 行）:
pub fn activate_line_and_go_to_community(name: &str) -> bool {
    tracing::debug!("activating LINE for community '{}'", name);
    run_osascript(SCRIPT_ACTIVATE, 15).is_some()
    // ← name 在這裡完全沒被用到！
}
```

`SCRIPT_ACTIVATE` 是編譯期常數，沒有插入 community name 的任何機制。

**修正方向**:
- 實作 `SCRIPT_ACTIVATE` 之後的 社群 tab 點擊與 OCR 搜尋流程
- 或在 Rust 中用 `osascript` + cliclick 實作 `_click_community_tab` + `_find_and_click_community` 的等效邏輯

---

### High

#### BUG-3: URL continuation regex 過於寬泛，相鄰兩個 SurveyCake URL 被合併成一個

**嚴重度**: High  
**位置**: `src/line.rs` `extract_survey_urls()` function 的 `url_continuation` regex  
**症狀**: 兩個 SurveyCake URL 若出現在相鄰行，第二個 URL 會被黏貼到第一個末尾，fallback order 指派失效。

**根因**:
```
url_continuation = Regex::new(r"^(w{2,3}\.|https?://|surveycake|[A-Za-z0-9]{3,8}$)")
```

此 pattern 的本意是接住 OCR 斷行的 URL 片段（如 `ww.surveycake...`），但 `https?://` 前綴也會匹配完整的第二個 URL，把它當成第一個 URL 的「continuation」合併進去。

**重現**:
```
輸入: "https://www.surveycake.com/s/First\nhttps://www.surveycake.com/s/Second"
實際輸出 attend: "https://www.surveycake.com/s/Firsthttps://www.surveycake.com/s/Second"
預期輸出 attend: "https://www.surveycake.com/s/First"
         quiz:   "https://www.surveycake.com/s/Second"
```

既有測試 `test_extract_survey_urls_fallback_order` 在 `line_test.rs` 中已失敗（`cargo test` 確認）。

**Python 版本行為**: Python 版也有相同 `url_continuation` regex，同樣存在此 bug。
但 Python 的 fallback 邏輯在 URL 合併後依然能從 `SURVEYCAKE_RE.findall(text)` 拿到合並前的 `urls` list，而 Rust 版的 `urls` 是從 `reassembled` 後的文字重新 scan，所以合並後只剩一個「巨型」URL match（不符合原始 regex），fallback 可能什麼都拿不到。

**修正方向**:
- url_continuation 只應在「前一行以 URL 結尾，且當前行是 URL 殘片（非完整 URL 開頭）」時才合併
- 一個更安全的做法：先跑 `SURVEYCAKE_RE.findall(original_text)` 拿全部 URL，再做 continuation 嘗試

---

### Medium

#### BUG-4: `run_osascript` 未實作 timeout（`timeout_secs` 參數被忽略）

**嚴重度**: Medium  
**位置**: `src/line.rs` `run_osascript()` line 76-96  
**症狀**: `timeout_secs: u64` 參數接受但未使用，std `Command::output()` 沒有 timeout 機制，若 osascript hang 則整個 async task 無限阻塞。

Python 版用 `subprocess.run(..., timeout=timeout)` 有 `subprocess.TimeoutExpired` 保護。

**修正方向**: 改用 `tokio::process::Command` + `timeout(Duration::from_secs(timeout_secs))` wrapper

---

## AppleScript 常數驗證

三段 AppleScript 與 Python 原版逐字相符（SHA-256 checksum 一致）：

| 常數 | Python SHA-256 | Rust SHA-256 | 狀態 |
|------|---------------|-------------|------|
| SCRIPT_ACTIVATE | `3099f959...` | `3099f959...` | ✅ 一致 |
| SCRIPT_ESCAPE | `1c3bddc1...` | `1c3bddc1...` | ✅ 一致 |
| SCRIPT_SCROLL_UP | `b56e7277...` | `b56e7277...` | ✅ 一致 |

---

## Regex 邊界驗證

| 輸入 | 預期 | 狀態 |
|------|------|------|
| `https://www.surveycake.com/s/abc` | ✅ match | ✅ |
| `https://ww.surveycake.com/s/abc` | ✅ match (OCR artifact) | ✅ |
| `https://vvw.surveycake.com/s/abc` | ❌ no match | ✅ |
| `https://w.surveycake.com/s/abc` | ❌ no match | ✅ |
| `https://wwww.surveycake.com/s/abc` | ❌ no match | ✅ |
| `https://www.surveycake.com/s/` | ❌ no match (empty slug) | ✅ |

---

## crop_params 純函數驗證

所有 invariant 通過：
- `crop_x < width` ✅
- `crop_y == 95`（固定）✅
- `crop_x + crop_w == width`（總寬守恆）✅
- `crop_y + crop_h == height - 45`（上 95 下 45）✅
- `saturating_sub` 防止 height < 140 時 underflow ✅
- mutation probe: `0.55` 係數 + `140` offset 都有對應實值比較 ✅

---

## 測試結果

```
cargo test --test line_invariants
test result: ok. 34 passed; 0 failed
```

---

## 優先修復順序

1. **BUG-1** (CGWindowID) — screencapture 完全無法運作的根本錯誤
2. **BUG-2** (community navigation) — 截圖對象錯誤，功能完全失效
3. **BUG-3** (URL merging) — fallback order 指派錯誤，attend/quiz 分類失敗
4. **BUG-4** (timeout) — 可靠性問題，次要
