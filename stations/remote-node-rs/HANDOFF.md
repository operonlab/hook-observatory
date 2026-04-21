# remote-node-rs — Rust rewrite of stations/remote-node

> Status: **功能完成 + 全部測試通過**，尚未做 production cutover
> Branch: `feature/remote-node-rs`
> Date: 2026-04-22

## 目標

把 Python FastAPI `stations/remote-node` 改寫成 Rust (axum + reqwest)，
作為 Mac → Windows GPU 視覺推論的 HTTP proxy station。

## 實作結果

### 檔案清單
```
stations/remote-node-rs/
├── Cargo.toml
├── config.yaml
├── src/
│   ├── main.rs            (Cli + lifespan + router wiring)
│   ├── config.rs          (YAML loader, tilde expansion)
│   ├── error.rs           (ProxyError → HTTP status mapping)
│   ├── state.rs           (AppState: reqwest client + health + output_dir)
│   ├── health_check.rs    (每 30s ping 遠端 /health)
│   └── routes.rs          (8 endpoints, base64 IO, JSON proxy)
├── tests/
│   └── integration.rs     (獨立 agent 寫的 18 個整合測試)
└── HANDOFF.md             (本檔)
```

### 端點對齊（與 Python 版 parity）
| Endpoint | Method | Python | Rust |
|----------|--------|--------|------|
| /health | GET | ✅ | ✅ (keys 完全一致) |
| /segment | POST | ✅ | ✅ (mask_base64 → mask_path 轉換) |
| /detect | POST | ✅ | ✅ (passthrough) |
| /caption | POST | ✅ | ✅ (detail=brief/detailed 分支) |
| /batch-segment | POST | ✅ | ✅ (per-prompt masks + composite) |
| /models | GET | ✅ | ✅ |
| /models/load | POST | ✅ | ✅ |
| /models/unload | POST | ✅ | ✅ |

## 效能量測

```
=== RSS ===
Python (PID 6589):  32.17 MB
Rust   (PID 68668): 11.44 MB    → -64%

=== /health latency (50 samples) ===
Python: p50=0.29ms  p95=0.40ms
Rust:   p50=0.15ms  p95=0.22ms  → ~1.9× faster

=== artefact size ===
Python .venv:        30 MB
Rust single binary:  5.5 MB     → -82%
```

> 註：`/segment` 等 base64-heavy endpoint 的真實端到端延遲需 Windows GPU
> 伺服器可達才能測；目前 Windows 不在，未做 live benchmark。預期 Rust 在
> 大圖 base64 encode + HTTP forward 場景有更大改善（Python base64 + httpx
> 是純 CPU bound）。

## 測試結果

```
cargo test --release --test integration
test result: ok. 18 passed; 0 failed; finished in 9.85s
```

測試由獨立 `worker` sub-agent 撰寫，**禁止閱讀 src/routes.rs 等實作**。
只能讀 Python `main.py` 作為行為規格 + Cargo.toml + config.yaml。

### 六鐵律遵守情況
1. **Mutation thinking**: 測試會被以下 mutation 殺死 —
   remote_healthy bool 翻轉、mask_base64/mask_path 轉換漏掉、
   caption detail 分支搞反、文件 path-traversal-safe 的 canonicalize 被移除
2. **寫測分離**: ✅ 獨立 worker agent，無法讀 Rust 實作
3. **不變量優先**: 每個 endpoint 都至少一條格式不變量
   （成功時 detail 不存在；不健康時一律 503；mask 系列一律無 base64 欄位）
4. **runtime 回歸**: 啟動真實 Rust binary（release build），HTTP 端對端
5. **Mock 僅限外部 I/O**: 只 mock Windows GPU server（wiremock），內部邏輯無 mock
6. **草稿自檢**: 測試檔頂部誠實揭露 gap

### 測試覆蓋的場景
- Health: remote 200 / 5xx / 連不上
- 503 gate: 所有 7 個 non-health endpoint 在 unhealthy 時都回 503
- 404: file_path 不存在時 detail 含檔名
- Success paths: 8 個端點全部
- mask_base64 → mask_path 正確性: 驗證存下的檔案 bytes 真的等於 decode 後的內容（殺掉「只檢查 key 存在」的 weak assertion）
- Caption detail 分支: brief / detailed / custom prompt 三條
- Remote error: 500 → 500 + "Remote error:" 前綴；timeout → 504；invalid JSON → 502

## Known gaps（測試 agent 誠實揭露）

測試 agent 回報以下邊界**未覆蓋**：
- 大檔案（>10MB）的 base64 記憶體行為
- 並發多請求下的 health_check race condition
- Unicode file_path / 含空格 path 的 edge
- 遠端回傳的 mask_base64 是空字串 / 格式損毀 base64 的 fallback

這些在 cutover 前可以補，或先上線觀察。

## 初始 Rust 實作的一個 bug

Rust 首版在 `src/routes.rs` 的 `thiserror` attribute 用了
`#[error("Remote error: {0}")]` + struct enum variant → 編譯 fail。
（struct variant 的 field 要用 `{status}` `{body}` 名稱引用，不是 `{0}`）
改為 `#[error("Remote error: {status} {body}")]` 後過 build。

## Cutover 步驟（尚未執行）

### Option A — 並行觀察 (建議)
1. 不改動現況 Python (port 10208) 服務
2. 把 Rust binary 放到 `~/workshop/stations/remote-node-rs/target/release/`
3. 起在 port 10209 並觀察一週（或下次實際用 Windows GPU 時）
4. 對照 Python 行為無誤後，再做 swap

### Option B — 直接替換
1. `scripts/workshop_services.py` 找到 `remote-node` entry
2. 把 `cmd` 從 `.venv/bin/python3 main.py` 改為
   `~/workshop/stations/remote-node-rs/target/release/remote-node-rs --config config.yaml`
3. `workdir` 改為 `stations/remote-node-rs/`
4. `launchctl kickstart -k` 重啟
5. 觀察 Sentinel `/health` 檢查

### Rollback
1. 還原 `workshop_services.py` 那一段
2. `launchctl kickstart -k`

## 尚未完成的 station onboarding

依 `.claude/rules/module-onboarding.md` 的 Standalone Station checklist：
- [ ] Port registry: `libs/sdk-client/sdk_client/port_registry.py` — port 不變 (10208)，但加入 `-rs` 變體 or 直接替換
- [ ] Service registry: `scripts/workshop_services.py` — cutover 時改 cmd
- [ ] Sentinel remediation map: 不需改（service name 相同）
- [ ] Nginx reverse proxy: 不需改（未經 Nginx）

## 編譯指令

```bash
cd stations/remote-node-rs
cargo build --release           # 5.5 MB binary
cargo clippy --all-targets --release   # 0 warnings
cargo test --release --test integration  # 18/18 passed in 9.85s
```
