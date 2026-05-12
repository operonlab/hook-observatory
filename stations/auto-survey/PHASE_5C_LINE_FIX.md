# Phase 5C — line.rs Critical + High Bug Fix

## C1 修法（CGWindowID 來源錯誤）

**API**：Python3 subprocess 呼叫 `Quartz.CGWindowListCopyWindowInfo` + `kCGWindowNumber`。

實作方式：
- 在 `get_line_window_id()` 中嵌入 Python 一行腳本 `PYTHON_GET_CG_WID`
- 用 `/usr/bin/python3 -c <script>` 取得真實 CGWindowNumber
- Fallback：`osascript do shell script` 包裝同一 Python 腳本
- 完全移除舊的 `SCRIPT_GET_WID`（System Events "id of front window"）

新常數包含：`CGWindowListCopyWindowInfo`、`kCGWindowOwnerName`、`kCGWindowName`、`kCGWindowNumber` — 與 Python line_reader.py:107-118 完全對應。

## H1 修法（Community navigation 沒實作）

**方案**：採用建議 (a)，新增 `pub fn build_activate_script(community_name: &str) -> String`。

腳本內容：
1. `tell application "LINE" to activate` + delay 1.5
2. 確保 chat 視窗存在（開 聊天 menu item）
3. `click menu item "社群" of menu "顯示" of menu bar 1` + delay 1.0
4. `keystroke "f" using {command down}`（搜尋框）
5. `keystroke "<community_name>"` + Return key + delay 1.5

`activate_line_and_go_to_community(name)` 改為呼叫 `build_activate_script(name)`，`name` 不再只出現在 debug log。

## 同步修 M1（URL 合併 bug）

移除 `url_continuation` regex 中的 `https?://` alternative：
- Before: `r"^(w{2,3}\.|https?://|surveycake|[A-Za-z0-9]{3,8}$)"`
- After: `r"^(w{2,3}\.|surveycake|[A-Za-z0-9]{3,8}$)"`

## Test 結果

### Before (Phase 5B)
- `tests/line_invariants.rs`: 34/34 pass（含多個負面斷言確認 bug 存在）
- `tests/line_test.rs::test_extract_survey_urls_fallback_order`: FAIL

### After (Phase 5C)
```
cargo test --test line_invariants
  36 passed (2 新增正面測試 + 2 負面→正面轉換)
  0 failed
```

新增正面測試：
- `test_get_line_window_id_uses_cg_window_api` — 驗證 src/line.rs 含 CGWindowListCopyWindowInfo + kCGWindowNumber + kCGWindowOwnerName
- `test_activate_script_embeds_community_name` — 驗證 `build_activate_script("微光早餐會")` 含社群名稱 + "社群" + "LINE" activate

轉換為正面的測試：
- `test_activate_community_name_param_not_embedded_in_script` — 保留靜態常數斷言 + 新增動態函數有嵌入
- `test_extract_fallback_by_order_no_keywords` — M1 修復後斷言 attend=First, quiz=Second

## cargo check 結果

0 errors，12 warnings（全為 pre-existing dead_code/unused_imports）

## 仍未修的部分

- **playwright.rs::test_to_camoufox_js_fill_conversion**: FAIL（pre-existing，與本次改動無關）
- Python line_reader.py M1 bug 沒動（根據 feedback_no_rerun_old.md）
- 生產端 LINE OCR 路徑仍走 Python runner（Rust line.rs 尚無生產呼叫端）
