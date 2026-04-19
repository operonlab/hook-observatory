# auto-survey Rust 化 + SQLite + 按需啟動 遷移計畫

**建立**: 2026-04-19
**目標完工**: 5-7 天（Claude sub-agent 並行）
**負責**: Claude 主導 + 並行 Claude sub-agents（不外包 codex/gemini）

---

## 動機

auto-survey 目前佔 ~45 MB RSS，全天候常駐但實際一週僅工作兩天。Rust 化 + 按需啟動後：

| 指標 | 現況（Python） | 目標（Rust） | 節省 |
|---|---|---|---|
| 活躍 RSS | ~45 MB | **~12 MB** | 33 MB |
| 非工時 RSS | ~45 MB（全天候） | **0 MB**（unload） | 45 MB |
| 每週平均 RSS | 45 MB × 168h | 12 MB × 16h + 0 × 152h | **~43 MB/週持續釋放** |

---

## 決策確認（少爺批准）

| # | 議題 | 選擇 |
|---|---|---|
| 1 | Playwright 處理 | **C**：Rust 全包 + shell out `camoufox-cli` / `playwright-cli` |
| 2 | SQLite 遷移 | **A**：遷移全部歷史資料（pg → sqlite） |
| 3 | 排程機制 | **B**：cronicle shell job 控制 `launchctl kickstart/kill` |
| 4 | 編排方式 | **A (調整)**：主導 + 派 Claude sub-agents 並行，**不外包 codex/gemini** |

---

## 架構

### 現況（Python）
```
auto-survey (Python, :10300)
├── web.py (FastAPI)
├── orchestrator.py → recon.py → filler.py (Playwright)
├── analyzer.py (LiteLLM @ :4000)
├── line_reader.py (LINE OCR)
├── notify.py (Bark)
├── db.py + models.py (PostgreSQL via sqlalchemy+psycopg)
└── cli.py (uvicorn wrapper)
```

### 目標（Rust）
```
auto-survey-rs (Rust, :10300)
├── src/
│   ├── main.rs          # Tokio runtime + axum router
│   ├── web.rs           # REST endpoints + static files
│   ├── orchestrator.rs  # Survey pipeline 控制
│   ├── playwright.rs    # camoufox-cli subprocess wrapper
│   ├── analyzer.rs      # LiteLLM HTTP client
│   ├── line.rs          # LINE OCR reader
│   ├── notify.rs        # Bark HTTP client
│   ├── db.rs            # sqlx SQLite pool
│   └── models.rs        # 結構定義（match Python models.py）
├── migrations/          # sqlx migration
│   └── 001_init.sql
└── Cargo.toml
  Deps: axum + tokio + sqlx(sqlite) + reqwest + serde + tracing
```

### 資料流
```
Cronicle (週三/五 10:00) → launchctl kickstart com.workshop.auto-survey-rs
  ↓
Rust binary 啟動 (~2s)
  ↓
axum :10300 ready
  ↓
[整天處理 survey requests]
  ├── line reader 抓連結 → orchestrator
  ├── orchestrator spawn camoufox-cli subprocess
  ├── snapshot 解析 → analyzer (litellm) → 答案
  ├── filler 回填 camoufox-cli → submit
  └── notify Bark
  ↓
Cronicle (週三/五 18:00) → launchctl kill com.workshop.auto-survey-rs
  ↓
程序退出，RSS → 0
```

---

## 分階段計畫

### Phase 0 · 盤點 + Worktree （序列，30 min）
**Agent**: explorer
**產出**: `HANDOFF.md`（給後續 phase 用）
- [ ] `git worktree add .worktrees/feature/auto-survey-rs -b feature/auto-survey-rs`
- [ ] 列 Python 所有 file + 每個的行數 + 公開 API
- [ ] 匯出 DB schema：`pg_dump --schema-only -t "auto_survey*" workshop`
- [ ] 盤點外部依賴：camoufox-cli、playwright-cli、litellm、LINE、Bark
- [ ] people.csv 格式分析

---

### Phase 1 · Rust 專案骨架（序列，2-3h）
**Agent**: worker
**依賴**: Phase 0
- [ ] `cargo new --bin stations/auto-survey-rs`
- [ ] Cargo.toml 依賴：
  ```toml
  axum = "0.7"
  tokio = { version = "1", features = ["full"] }
  sqlx = { version = "0.8", features = ["sqlite", "runtime-tokio", "macros"] }
  reqwest = { version = "0.12", features = ["json"] }
  serde = { version = "1", features = ["derive"] }
  tracing = "0.1"
  tracing-subscriber = "0.3"
  anyhow = "1"
  ```
- [ ] 基本 axum server + health check (`/status`)
- [ ] `port_registry.py` 確認 10300 保留
- [ ] `workshop_services.py` 新增 `auto-survey-rs` entry（先保留 Python 版，測試通過才切換）

---

### Phase 2 · SQLite schema + 資料遷移（並行 with Phase 1 尾段，2-3h）
**Agent**: worker
**依賴**: Phase 0
- [ ] 建 `migrations/001_init.sql`（對應 Python models.py 的 ORM 表）
- [ ] 資料類型對應表：
  | Python (Postgres) | Rust (SQLite) |
  |---|---|
  | `UUID` | `TEXT` (lowercase hex) |
  | `JSONB` | `TEXT` (JSON string) |
  | `TIMESTAMP` | `TEXT` (ISO-8601) |
  | `Boolean` | `INTEGER` (0/1) |
- [ ] 遷移腳本 `scripts/migrate_pg_to_sqlite.py`：
  1. 讀 pg 所有 auto_survey 相關 table
  2. 轉換欄位型別（JSONB→text、UUID→text）
  3. 寫入 SQLite
  4. count + sample 驗證
- [ ] 輸出 `data/auto_survey.db`
- [ ] 驗證：Rust 能 sqlx 讀到，count 與 pg 一致

---

### Phase 3 · 核心邏輯 Rust 移植（全部並行，各 3-4h）
**依賴**: Phase 1 完成

#### Phase 3a · LLM analyzer（worker）
- [ ] 把 analyzer.py 的 `_call_litellm`、`analyze_quiz`、`analyze_quiz_rlm`、`reanalyze_wrong` 移植到 `src/analyzer.rs`
- [ ] `reqwest::Client::post` → litellm `/v1/chat/completions`
- [ ] 結構化輸出 (`response_format: json_object`) + `serde_json::from_str`
- [ ] prompt 內容**逐字保留**（不改寫，避免行為漂移）

#### Phase 3b · Web routes（worker）
- [ ] `src/web.rs`：axum router + 所有 REST endpoint 遷移
- [ ] static files 服務（`tower-http::services::ServeDir`）
- [ ] CORS middleware（保持原 FastAPI 設定）
- [ ] 健康檢查 `/status` 回 `{"service":"auto-survey-rs","version":"0.1.0"}`

#### Phase 3c · Orchestrator + Playwright（worker）
- [ ] `src/playwright.rs`：`tokio::process::Command` 呼叫 `camoufox-cli`
- [ ] Session 管理：一個 survey 一個 session（`--session sv-<uuid>`）
- [ ] Snapshot 解析：camoufox `snapshot -i` 輸出的 interactive element JSON
- [ ] 基本動作：`open`、`click @elN`、`fill @elN "text"`、`close`
- [ ] `src/orchestrator.rs`：survey pipeline 狀態機（recon → analyze → fill → submit → verify）
- [ ] 保留 `playwright-cli` 作為備援路徑（若 camoufox 失敗）

#### Phase 3d · LINE + notify（worker）
- [ ] `src/line.rs`：HTTP client 抓 LINE OCR 連結
- [ ] `src/notify.rs`：Bark HTTP POST
- [ ] 設定讀自 env (`CORE_BARK_SERVER_URL` 等)

---

### Phase 4 · 排程整合（並行 with Phase 3，1-2h）
**Agent**: worker
- [ ] 建 `infra/launchd/com.workshop.auto-survey-rs.plist`：
  - `RunAtLoad=false`
  - `KeepAlive=false`（只有手動 kickstart 才跑）
  - stdout/stderr → `/opt/homebrew/var/log/workshop/auto-survey-rs/`
- [ ] `schedules/manifest.json` 新增兩個 job：
  ```json
  {
    "name": "ws-auto-survey-start",
    "schedule": { "cron": "0 10 * * 3,5" },  // 週三五 10:00
    "command": "launchctl kickstart -k gui/$(id -u)/com.workshop.auto-survey-rs"
  },
  {
    "name": "ws-auto-survey-stop",
    "schedule": { "cron": "0 18 * * 3,5" },  // 週三五 18:00
    "command": "launchctl kill TERM gui/$(id -u)/com.workshop.auto-survey-rs"
  }
  ```
- [ ] `stations/sentinel/checker.py` 加 `auto-survey-rs` entry（條件式：僅工時檢查）
- [ ] `schedules/scheduler.py` seed 新 job

---

### Phase 5 · 測試 + Adversarial Review（序列，2-3h）
**Agents**: worker (tests) + reviewer (adversarial) 並行

**Worker 寫測試**:
- [ ] 單元測試：analyzer mock litellm、db CRUD、playwright mock
- [ ] 整合測試：啟動 server → health check → 假資料 survey 流程
- [ ] 端到端測試：真實 survey URL（測試帳號）

**Reviewer (adversarial mode)**:
- [ ] 審查 code reuse（有無重複邏輯）、quality（錯誤處理、型別安全）、efficiency（unnecessary allocation / await）
- [ ] 檢查 SQL injection、subprocess argument escape、secret leak
- [ ] 比對資料遷移結果（抽樣 20 筆 survey，欄位逐一對照 pg ↔ sqlite）

**驗收 gate**（須全通）:
1. Rust binary RSS < 15 MB（空閒）
2. 填表延遲 ±10%（vs Python 版）
3. 所有單元 + 整合測試通過
4. reviewer 無 critical 發現
5. 歷史資料 count + sample 一致

---

### Phase 6 · Cutover 部署（序列，1-2h）
**Agent**: 主導（Claude 直接做，不派）
- [ ] Merge worktree 到 main（`git merge --no-ff`）
- [ ] 停 Python 版：`kill <pid>` + 移除 workshop_services.py Python entry
- [ ] launchd：`launchctl load com.workshop.auto-survey-rs.plist`
- [ ] Cronicle：`python3 schedules/scheduler.py sync`
- [ ] 首次手動驗證：`launchctl kickstart -k ...`，curl :10300/status
- [ ] `launchctl kill TERM ...`，確認 RSS = 0
- [ ] Sentinel light check 通過

---

## 並行相依圖

```
Phase 0 (explorer) ──┐
                     ↓
            Phase 1 (worker: skeleton) ──┐
                     │                    ↓
                     ├─→ Phase 2 (worker: sqlite)
                     │
                     ├─→ Phase 3a (worker: analyzer) ──┐
                     ├─→ Phase 3b (worker: web) ──────┤
                     ├─→ Phase 3c (worker: playwright) ┼─→ Phase 5 (worker+reviewer) → Phase 6
                     ├─→ Phase 3d (worker: notify) ───┤
                     └─→ Phase 4 (worker: schedule) ──┘
```

**最大並行度**: 5 個 Claude sub-agents（Phase 3a/b/c/d + Phase 4）

---

## 風險與緩解

| 風險 | 機率 | 影響 | 緩解 |
|---|---|---|---|
| camoufox-cli snapshot 格式變動 | 低 | 中 | Cargo.toml 記錄當前 camoufox 版本，CI 固定 |
| SQLite 與 Postgres 查詢行為差異 | 中 | 中 | 先跑 Phase 2 驗證腳本，抽樣比對 |
| launchctl kickstart/kill 時機漂移 | 低 | 低 | Cronicle job 前置 `launchctl print` 驗證狀態 |
| Prompt 改寫導致 LLM 回答 drift | 中 | 高 | **逐字保留** Python prompt，不改寫 |
| Playwright 填表行為不等同 | 中 | 高 | Phase 5 用舊資料 replay，比對 Python 版輸出 |
| 資料遷移丟失 | 低 | 高 | 遷移後 Postgres 不刪（保留 30 天觀察期） |

---

## 驗收標準

| # | 項目 | 方法 |
|---|---|---|
| 1 | RSS 活躍 < 15 MB | `ps -o rss` |
| 2 | 非工時 RSS = 0 | `pgrep -f auto-survey-rs` 無結果 |
| 3 | 週三/五 10:00 自動啟 | `launchctl print` 狀態 |
| 4 | 週三/五 18:00 自動關 | `pgrep` 為空 |
| 5 | 歷史資料 100% 遷移 | count + 20-row sample 比對 |
| 6 | Survey 端到端成功 | 填一份測試 survey，檢查 DB 紀錄 |
| 7 | Sentinel 通過 | HTTP probe 200 |
| 8 | 無效能倒退 | 填表延遲 p50 ±10% |

---

## 回滾計畫

若 Phase 5/6 出問題：

1. `launchctl unload com.workshop.auto-survey-rs.plist`
2. 移除 cronicle 新 job（保留 Python 版舊排程）
3. 重啟 Python 版 `auto-survey` → port 10300
4. Postgres 資料仍在（未刪）
5. 觀察舊系統恢復正常後，再排查 Rust 問題

---

## Out-of-Scope（本次不做）

- LINE OCR 抓取邏輯改寫（沿用原本的 text 處理）
- Survey 演算法重構（單純語言遷移，不改邏輯）
- 前端 UI 更動（保留原 static files）
- 多機器支援（單機 Mac Mini 部署）

---

## 備註

- **Prompt 不改寫**：analyzer 中所有 LLM prompt 逐字保留，避免行為漂移
- **camoufox-cli 版本固定**：Cargo.lock 不夠，需要 README 記錄 camoufox 測試版本
- **PostgreSQL 保留 30 天**：遷移後不刪除舊資料，以便追溯
