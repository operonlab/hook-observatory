# Anvil — 技能數據平台 Station 規格書

**Feature Branch**: `feature/anvil-station`
**建立日期**: 2026-03-05
**狀態**: 草稿
**輸入**: 技能生態系的數據層與結構性工具平台。提供持久化存儲、被動遙測、結構性檢測、三角驗證基礎設施。不取代需要 LLM 推理的 Skill，而是作為它們的數據後端。

---

## 背景脈絡

### 問題陳述

Workshop 目前有 9 個獨立的 skill-xxx Skills（create-skill, skill-tester, skill-security-scan, skill-optimizer, skill-curator, skill-catalog, skill-graph, skill-publisher, skill-lifecycle），各自為政：

1. **無持久化**：每次執行結果即丟棄，無法追蹤趨勢與 regression
2. **無遙測**：不知道哪些 skill 被用了、多常用、表現如何
3. **無量化品質**：品質判斷仰賴人工檢視，無自動化驗證管道
4. **入口分散**：9 個 skill 各有觸發方式，認知負擔高
5. **無視覺化**：92+ skills 的關聯拓撲只存在於 skill-graph 的靜態輸出

### 願景

**Anvil（鐵砧）**：技能生態系的數據平台與結構性工具箱。

- **是**：持久化存儲、被動遙測、結構性檢測（T1-T4, S1-S3）、評估基礎設施、統計分析
- **不是**：取代需要 LLM 推理能力的 Skill（create, optimize, curate, lifecycle 等）
- **定位**：原始 Skill 保留 LLM 智能層，Anvil 提供數據後端供它們調用

```
          ┌─────────────────────────────────────┐
          │           Anvil Station              │
          │                                      │
          │  create → test → scan → eval →       │
          │  optimize → curate → publish          │
          │         ↕          ↕                  │
          │    telemetry    evaluation            │
          │         ↓          ↓                  │
          │      PostgreSQL (長期追蹤)             │
          │         ↓                             │
          │    WebUI Skill Graph (視覺化管理)      │
          └─────────────────────────────────────┘
```

### Skill 與 Anvil 職責分工

| 原 Skill | 保留？ | Anvil 提供 | 說明 |
|----------|:---:|------------|------|
| create-skill | ✅ 保留 | `anvil create`（scaffold）、`anvil catalog`（重疊數據） | LLM 負責智能設計，Anvil 負責機械 scaffold |
| skill-tester | ✅ 保留 | `anvil test`（T1-T4） | T5 scenario 測試需要 LLM agent |
| skill-security-scan | ✅ 保留 | `anvil scan`（S1-S3） | S4-S6 語義分析需要 LLM |
| skill-optimizer | ✅ 保留 | `anvil stats`（使用數據）、`anvil eval`（評估數據） | 分析+建議+修改全程需要 LLM |
| skill-curator | ✅ 保留 | `anvil catalog` + `anvil graph`（inventory 數據） | 3-agent panel 需要 LLM |
| skill-catalog | ⚡ 可被取代 | `anvil catalog` 完全覆蓋 | 純數據列表，無需 LLM |
| skill-graph | ⚡ 可被取代 | `anvil graph` 完全覆蓋 | I/O MIME 比對是確定性的 |
| skill-publisher | ✅ 保留 | （未來：git ops） | 雙語 README/changelog 生成需要 LLM |
| skill-lifecycle | ✅ 保留 | 所有 CLI subcommands | 多步 orchestration 需要 LLM |
| skill-graph | `anvil graph` | `graph_skills()` | 依賴 + 協作拓撲 |
| skill-publisher | `anvil publish` | `publish_skill()` | GitHub 推送 + 版本控制 |
| skill-lifecycle | `anvil lifecycle` | `lifecycle_skill()` | 全生命週期 pipeline |
| **新增** | `anvil eval` | `eval_skill()` | 三角驗證（Anthropic 方法論） |
| **新增** | `anvil stats` | `get_stats()` | Hook 遙測統計 |
| **新增** | `anvil history` | `get_history()` | 版本趨勢追蹤 |
| **新增** | `anvil correct` | `correct_skill()` | 受控自我修正 |

### 架構：四層複合 + Hook Observatory 整合

```
┌────────────────────────────────────────────────────────────┐
│ Skill Layer: ~/.claude/skills/anvil/SKILL.md               │
│   意圖路由，呼叫 CLI + MCP，不 import SDK                  │
├────────────────────────────────────────────────────────────┤
│ MCP Layer: mcp/anvil/server.py                             │
│   結構化合約，Claude Code main agent 使用                  │
├────────────────────────────────────────────────────────────┤
│ CLI Layer: stations/anvil/cli/anvil.py                     │
│   人 + 腳本 + headless agent 通用存取                      │
├────────────────────────────────────────────────────────────┤
│ SDK Layer: libs/sdk-client/sdk_client/anvil.py       │
│   基底層 — CLI 和 MCP 都 import 此 SDK                     │
├────────────────────────────────────────────────────────────┤
│ HTTP Service: stations/anvil/src/server.py                 │
│   FastAPI 常駐服務 + PostgreSQL (schema: anvil)             │
├────────────────────────────────────────────────────────────┤
│ Hook 遙測：stations/hook-observatory/handlers/             │
│   anvil_telemetry.py — PostToolUse/Skill 被動收集          │
│   ↳ 掛載於 dispatcher REGISTRY，非獨立 hook 腳本           │
│   ↳ 走 spool → Anvil API（或直接寫 spool + DB drain）      │
└────────────────────────────────────────────────────────────┘
```

#### Hook 遙測整合路徑

```
使用者觸發 Skill
    │
    ▼
~/.claude/hooks/dispatcher.py (PostToolUse)
    │
    ▼
stations/hook-observatory/handlers/__init__.py
    REGISTRY["PostToolUse"] = [
        ...
        ("Skill", anvil_telemetry.handle),   ← 新增
        ("Skill", external.skill_tracker),   ← 現有（可共存或替換）
        (None, observability.handle),        ← 全量事件繼續收集
    ]
    │
    ▼
handlers/anvil_telemetry.py
    ├─ 方案 A：寫 spool JSONL → SpoolDrainer → hook_observatory DB
    │           → Anvil server 從 hook_observatory DB 讀取
    └─ 方案 B：直接 HTTP POST → Anvil API（非阻塞，fire-and-forget）
              → Anvil 自行寫入 anvil schema
```

**設計決策**：採用方案 B（直接 POST 到 Anvil API）。原因：
1. Anvil 需要自己的 schema（不混用 hook_observatory schema）
2. 遙測資料結構較複雜（需解析 skill_name, duration, success 等語義欄位）
3. handler 內用 `run_background()` 發 HTTP request → 零阻塞（< 1ms）
4. Anvil server 離線時 gracefully fail → 不影響 skill 執行

---

## 使用者場景與測試

### User Story 1 — 被動遙測與使用統計 (優先級: P1)

少爺日常使用 92+ skills，想知道哪些 skill 被用了、多常用、成功率如何，但不想每次手動紀錄。系統透過 Hook Observatory 的 handler 被動攔截每次 skill 調用，自動寫入 Anvil DB，隨時可查統計。

**為何此優先級**: 這是整個系統的資料基礎。沒有遙測數據，後續的評估、趨勢、修正都沒有依據。且 Hook 機制一旦啟用即持續收集，越早啟用資料越豐富。

**獨立測試方式**: 部署 handler + 啟動 Anvil server + 呼叫任意 skill → `anvil stats` 顯示該 skill 被調用一次。

**驗收場景**:

1. **Given** Anvil server 已啟動且 handler 已掛載於 hook-observatory, **When** 使用者觸發任意 skill（如 `/smart-search`）, **Then** Anvil DB 新增一筆 invocation 紀錄（skill_name, timestamp, duration, success, tool_calls count）
2. **Given** DB 有多筆 invocation 紀錄, **When** 執行 `anvil stats`, **Then** 顯示 Top 10 skills by 使用頻率、平均成功率、近 7 日趨勢
3. **Given** DB 有多筆 invocation 紀錄, **When** 執行 `anvil stats --skill finance`, **Then** 顯示該 skill 的詳細統計（每日調用數、平均 duration、失敗率、最常見 error）
4. **Given** Anvil server 未啟動, **When** handler 攔截 skill 調用, **Then** handler gracefully fail（不阻塞 skill 執行），hook-observatory 日誌記錄連線失敗

---

### User Story 2 — 統一 CLI 管理 (優先級: P1)

少爺想用一個 CLI 完成所有 skill 管理操作，取代 9 個分散的 skill 觸發。`anvil` CLI 統一入口，subcommand 對應原 skill 功能。

**為何此優先級**: CLI 是 SDK 的直接消費者，建立 CLI 即驗證 SDK API 完整性。且 CLI 是 headless agent + 腳本的主要介面。

**獨立測試方式**: `anvil create my-skill` 生成 scaffold → `anvil test my-skill` 通過結構驗證 → `anvil catalog` 列出新 skill。

**驗收場景**:

1. **Given** SDK 已實作 create_skill(), **When** 執行 `anvil create my-skill`, **Then** 生成 `~/.claude/skills/my-skill/` scaffold（SKILL.md + README.md）
2. **Given** 一個已存在的 skill, **When** 執行 `anvil test finance`, **Then** 執行 T1-T5 結構驗證並輸出 JSON 結果
3. **Given** 一個已存在的 skill, **When** 執行 `anvil scan finance`, **Then** 執行 6 類安全掃描並輸出風險報告
4. **Given** 全域 `--json` flag, **When** 任何子命令加 `--json`, **Then** 輸出 machine-readable JSON

---

### User Story 3 — 三角驗證評估 (優先級: P2)

少爺想對重要 skill 進行功能品質驗證（不只結構檢查）。系統用 Anthropic 三角驗證：Grader（微觀斷言）+ Comparator（盲測 A/B）+ Analyzer（宏觀模式偵測），產出量化的 benchmark。

**為何此優先級**: 這是 Anvil 的核心差異化功能 — skill-tester 只做結構，eval 做真實功能驗證。但它依賴 P1 的 DB 基礎存放結果。

**獨立測試方式**: 為 finance skill 撰寫 evals.json → `anvil eval finance` → 查看 benchmark.json 分數。

**驗收場景**:

1. **Given** finance skill 有 evals.json（2+ test cases）, **When** 執行 `anvil eval finance`, **Then** 對每個 test case spawn `claude -p` subprocess 執行 → 捕獲 transcript + outputs
2. **Given** eval 執行完成, **When** Grader agent 分析 transcript, **Then** 逐項 expectation 判定 PASS/FAIL（需正面證據，預設 FAIL）+ Claim Extraction
3. **Given** eval 有 baseline 版本, **When** 執行 `anvil eval finance --regression`, **Then** Comparator 盲測 A/B 兩版本（不知哪個是新/舊）→ 每維度 1-5 分
4. **Given** 多個 skill 的 eval 結果, **When** Analyzer 執行, **Then** 產出跨 skill 模式偵測報告（只觀察，不建議改進）
5. **Given** 評估完成, **When** 結果寫入, **Then** benchmark.json + benchmark.md 存入 DB 並關聯 skill version

---

### User Story 4 — MCP 結構化存取 (優先級: P2)

Claude Code main agent 需透過 MCP 工具直接調用 Anvil 功能，無需透過 Bash CLI。MCP server 提供 typed schema 的結構化介面。

**為何此優先級**: MCP 是 Claude Code 原生整合管道，skill layer 依賴 MCP 進行結構化操作。

**獨立測試方式**: 在 Claude Code 中使用 `mcpproxy` 載入 anvil tools → 呼叫 `anvil_test_skill` → 取得結構化結果。

**驗收場景**:

1. **Given** MCP server 已啟動並註冊於 `~/.claude.json`, **When** `mcp__mcpproxy__retrieve_tools(server_name: "anvil")`, **Then** 列出所有 Anvil MCP tools
2. **Given** MCP tool `anvil_eval_skill`, **When** 傳入 `{"skill_name": "finance", "mode": "full"}`, **Then** 回傳結構化評估結果（markdown formatted）
3. **Given** MCP tool `anvil_stats`, **When** 傳入 `{"skill_name": "finance", "period": "7d"}`, **Then** 回傳格式化統計摘要

---

### User Story 5 — WebUI 技能網 + CRUD (優先級: P3)

少爺想透過瀏覽器視覺化管理 92+ skills，像遊戲技能樹那樣呈現 skill 之間的關聯與狀態。可在 WebUI 上進行 CRUD 操作。

**為何此優先級**: 視覺化是 nice-to-have，核心功能（遙測、CLI、評估）必須先穩定。但這是少爺明確要求的特色功能。

**獨立測試方式**: 開啟 Anvil WebUI → 看到 skill 節點網路圖 → 點擊一個 skill → 查看詳情 + 編輯。

**驗收場景**:

1. **Given** Anvil server 已啟動, **When** 瀏覽器訪問 Anvil WebUI, **Then** 顯示技能網（力導向圖或樹狀圖），每個節點代表一個 skill
2. **Given** 技能網已載入, **When** 點擊 skill 節點, **Then** 側邊面板顯示：名稱、版本、描述、統計（調用次數/成功率）、最近 eval 分數、健康指標
3. **Given** 側邊面板已開, **When** 點擊「Edit」, **Then** 可編輯 skill metadata（description, tags, I/O schema）並 Save
4. **Given** 技能網, **When** 切換到「Forge Pipeline」視圖, **Then** 顯示 skill-lifecycle 流程圖（create → test → scan → eval → optimize → publish）
5. **Given** WebUI, **When** 搜尋或篩選, **Then** 可依 tag、使用頻率、健康分數、最近更新時間篩選 skills

---

### User Story 6 — 受控自我修正 (優先級: P3)

當評估持續發現某 skill 品質下降（regression），系統可提出修正建議，經少爺批准後自動執行。分級制度避免失控。

**為何此優先級**: 自我修正是最高級功能，依賴評估管道（P2）+ 遙測數據（P1）才有修正依據。

**獨立測試方式**: 模擬 skill 評估分數連續下降 → 系統產出修正建議 → 少爺批准 → 自動執行修正 → 重新評估確認改善。

**驗收場景**:

1. **Given** skill 評估分數連續 3 次低於閾值, **When** 系統偵測 regression, **Then** 自動生成修正建議（Level 1: 觀察報告）
2. **Given** Level 1 報告已生成, **When** 少爺批准升級到 Level 2, **Then** 系統產出具體的 SKILL.md diff 建議
3. **Given** Level 2 diff 已生成, **When** 少爺批准 Level 3 執行, **Then** 系統自動在 worktree 中修改 SKILL.md → 重新 eval → 只有分數提升才 merge
4. **Given** 任何自動修正, **When** 執行完成, **Then** 修正紀錄寫入 DB（before/after score, diff, approval timestamp）

---

### 邊界情況

- **Anvil server 離線時 Hook 觸發**：handler 內 `run_background()` HTTP POST 失敗 → gracefully 忽略，不阻塞 skill 執行。hook-observatory 的 observability handler 仍會記錄原始事件到 spool。
- **eval subprocess 卡死**：每個 `claude -p` subprocess 有 timeout（預設 120s），超時 → SIGTERM → 標記 eval 為 TIMEOUT。
- **Grader 判定不穩定**：同一 eval 跑 N 次（`--runs 3`），取 mean score，附帶 stddev。
- **遙測資料量膨脹**：invocation 表設 retention policy（預設保留 90 天原始紀錄，之後只保留每日聚合摘要）。
- **Comparator 無 baseline**：首次 eval 無舊版可比，Comparator 跳過，只跑 Grader + Analyzer。
- **skill 被刪除**：invocation 紀錄保留（soft reference），catalog 標記為 archived。
- **巢狀 claude -p subprocess 呼叫失敗**：移除 `CLAUDECODE` 環境變數允許巢狀呼叫（Anthropic 已驗證方案）。
- **併發 eval 執行**：ProcessPoolExecutor 控制 worker 數（預設 3），避免 API rate limit。
- **與現有 skill_tracker 共存**：`external.skill_tracker` 寫到 memvault，`anvil_telemetry` 寫到 Anvil — 兩者在 REGISTRY 中共存，不衝突。

---

## 需求

### 功能需求

**DB + 遙測基礎**

- **FR-001**: System MUST 提供 PostgreSQL-backed HTTP API（FastAPI），作為 Anvil 的資料持久層
- **FR-002**: System MUST 透過 hook-observatory 的 PostToolUse handler 被動攔截所有 Skill tool 調用，記錄 invocation 到 Anvil DB
- **FR-003**: Handler MUST 非阻塞 — 使用 `run_background()` fire-and-forget HTTP POST，skill 調用不得因 handler 錯誤而中斷
- **FR-004**: System MUST 追蹤 skill 版本（SKILL.md 的 version frontmatter 或 git hash）
- **FR-005**: System MUST 提供 invocation 數據的聚合查詢（按 skill、時段、成功率分組）
- **FR-006**: Handler MUST 掛載於 `stations/hook-observatory/handlers/anvil_telemetry.py` 並在 `__init__.py` REGISTRY 中註冊

**SDK**

- **FR-010**: SDK MUST 為 Standalone HTTP client（httpx），連接 Anvil station HTTP API
- **FR-011**: SDK MUST 吸收 9 個原 skill-xxx 的核心邏輯為 methods
- **FR-012**: SDK MUST 支援同步 API（CLI 直接呼叫）
- **FR-013**: SDK MUST 提供 `AnvilError(status_code, detail)` 統一錯誤類型

**CLI**

- **FR-020**: CLI MUST 用 argparse 實作，13+ subcommands 對應 SDK methods
- **FR-021**: CLI MUST 支援全域 `--json` flag（`parents=[common_parser]`）
- **FR-022**: CLI MUST import SDK，不直接碰 HTTP
- **FR-023**: CLI MUST 安裝為 `~/.local/bin/anvil` symlink

**三角驗證**

- **FR-030**: System MUST 支援 `evals.json` per-skill 測試定義格式
- **FR-031**: Eval executor MUST 透過 `claude -p` subprocess 執行 skill，捕獲 transcript + outputs
- **FR-032**: Grader agent MUST 採用舉證責任倒置 — 預設 FAIL，需正面證據才 PASS
- **FR-033**: Grader MUST 執行 Claim Extraction — 主動驗證產出中的事實宣稱
- **FR-034**: Comparator agent MUST 盲測 — 不知道 A/B 哪個是新版
- **FR-035**: Analyzer agent MUST 只報告觀察，不建議改進
- **FR-036**: 評估結果 MUST 寫入 DB 並關聯 skill version

**MCP**

- **FR-040**: MCP server MUST 基於 SDK 實作，用 `asyncio.to_thread()` 包裝同步方法
- **FR-041**: MCP tools MUST 提供 formatting helpers（markdown 格式化輸出）
- **FR-042**: MCP server MUST 註冊於 `~/.claude.json` mcpServers

**Skill 層**

- **FR-050**: Skill MUST 只透過 CLI（Bash tool）+ MCP（mcpproxy）調用，不 import SDK
- **FR-051**: Skill MUST 在 SKILL.md 中維護 Interfaces 表（CLI / MCP / SDK 對照）

**WebUI**

- **FR-060**: WebUI MUST 顯示 skill 關聯網路圖（力導向或層級樹）
- **FR-061**: WebUI MUST 支援 skill metadata CRUD
- **FR-062**: WebUI MUST 顯示每個 skill 的統計儀表板（調用、eval 分數、趨勢）
- **FR-063**: WebUI MUST 顯示 Forge Pipeline 視圖（lifecycle 流程）

**自我修正**

- **FR-070**: System MUST 偵測 regression（連續 N 次 eval 低於閾值）
- **FR-071**: 修正 MUST 分級：Level 0（觀察）→ Level 1（報告）→ Level 2（建議 diff）→ Level 3（自動執行 + 審批）
- **FR-072**: Level 3 自動修正 MUST 在 worktree 隔離環境中執行
- **FR-073**: 自動修正 MUST 重新 eval 驗證改善，分數未提升則 revert

### 關鍵實體

- **Skill**: 92+ skills 的 metadata registry（name, version, description, tags, io_schema, health_score, created_at, updated_at, status[active/archived]）
- **Invocation**: 每次 skill 調用紀錄（skill_id, timestamp, duration_ms, success, error_message, tool_calls_count, session_id, agent_model）
- **Evaluation**: 三角驗證結果（skill_id, version, run_timestamp, grading_results[], comparator_results[], analyzer_report, benchmark_score, benchmark_json）
- **EvalDefinition**: evals.json 的持久化版本（skill_id, test_cases[], version, last_run）
- **Correction**: 自我修正紀錄（skill_id, level, trigger_reason, before_score, after_score, diff_content, approved_by, approved_at, status[proposed/approved/executed/reverted]）
- **SkillVersion**: 版本快照（skill_id, version, skill_md_hash, created_at, eval_score, metadata）

---

## 成功標準

### 可衡量指標

- **SC-001**: 部署後 7 天內，Hook 自動收集 100+ 筆 skill invocation 紀錄（日均 14+）
- **SC-002**: `anvil stats` 回應時間 < 2 秒（含 DB 聚合查詢）
- **SC-003**: 13 個 CLI subcommands 全部可用，`--json` 覆蓋率 100%
- **SC-004**: 三角驗證對單一 skill（3 test cases）完成時間 < 5 分鐘
- **SC-005**: WebUI 技能網可在 3 秒內渲染 92+ skill 節點 + 邊
- **SC-006**: 9 個原 skill-xxx 的功能全部可透過 `anvil` CLI 重現
- **SC-007**: Grader 判定穩定性 > 80%（同一 eval 跑 3 次，結果一致的比例）
- **SC-008**: Hook handler 攔截延遲 < 1ms（fire-and-forget POST，與 observability handler 同等級）
- **SC-009**: 自我修正 Level 3 的成功率 > 60%（修正後分數確實提升）

---

## 技術脈絡

### 技術棧

- **語言**: Python 3.12（`~/.local/bin/python3`, uv-managed）
- **HTTP 框架**: FastAPI（與 Workshop 其他 Station 一致）
- **資料庫**: PostgreSQL（Workshop Core 共用實例，獨立 schema `anvil`）
- **SDK**: Standalone httpx client（不繼承 BaseClient — Anvil 是 Station 非 Core Module）
- **CLI**: argparse + SDK import
- **MCP**: FastMCP SDK + `asyncio.to_thread()`
- **WebUI**: React component in Workbench（或 station 內建 SPA — 參考 hook-observatory/frontend 模式）
- **Hook 遙測**: `stations/hook-observatory/handlers/anvil_telemetry.py`（掛載於 dispatcher REGISTRY）
- **Eval Subprocess**: `claude -p --output-format stream-json`
- **Eval Agent Prompts**: `stations/anvil/src/agents/{grader,comparator,analyzer}.md`

### 關鍵設計決策

1. **Station 而非 Core Module**：Anvil 管理的是 Claude Code skills（本地工具），非業務 domain。用 Station 模式（獨立 server + Standalone SDK）
2. **PostgreSQL 而非 SQLite**：長期追蹤 + 聚合查詢 + WebUI 共用 DB。Schema 名稱 `anvil`
3. **Standalone HTTP SDK 模式**：如 agent-metrics, sentinel。自管 httpx.Client + 自訂 port
4. **Hook 掛載於 hook-observatory**：不另建獨立 hook 腳本，複用 dispatcher → handler 架構。handler 用 `run_background()` 發 HTTP POST 到 Anvil API，零阻塞
5. **與現有 skill_tracker 共存**：`external.skill_tracker`（寫 memvault）和 `anvil_telemetry`（寫 Anvil DB）在 REGISTRY 中並列，各司其職
6. **原 Skill 保留但改為 CLI 概念**：原 skill-xxx 的 SKILL.md 檔案留在原位繼續運作，但邏輯遷移到 SDK；長期可考慮退役原 Skills，全改走 Anvil Skill 路由
7. **舉證責任倒置（Grader）**：來自 Anthropic skill-creator 的核心設計，避免假陽性
8. **Analyzer 不建議改進**：分離觀察與建議，觀察由 Analyzer 做，改進由 skill-optimizer（→ `anvil optimize`）做

### 整合介面

```
┌─ Hook Observatory 整合 ───────────────────────────────┐
│  dispatcher.py                                         │
│    └→ handlers/__init__.py REGISTRY                    │
│         └→ ("Skill", anvil_telemetry.handle)  ← 新增   │
│         └→ ("Skill", external.skill_tracker)  ← 現有   │
│         └→ (None, observability.handle)       ← 全量   │
│                                                        │
│  anvil_telemetry.handle():                             │
│    解析 skill_name, duration, success                   │
│    run_background(curl POST → Anvil API /invocations)  │
└────────────────────────────────────────────────────────┘

┌─ 現有 Skills ──────────────────────────────────────────┐
│  原 9 skill-xxx → 邏輯遷移到 SDK methods               │
│  原 SKILL.md 可保留，逐步退役                            │
└────────────────────────────────────────────────────────┘

┌─ Workshop 服務整合 ────────────────────────────────────┐
│  Workbench WebUI → Anvil API（skill graph）             │
│  agent-metrics → 共享 session/agent 元資料              │
│  hook-observatory → 事件流 + spool 共用基礎設施         │
└────────────────────────────────────────────────────────┘

┌─ Eval Pipeline ────────────────────────────────────────┐
│  claude -p subprocess → transcript capture              │
│  Grader/Comparator/Analyzer → structured output         │
│  results → Anvil DB → trend tracking                    │
└────────────────────────────────────────────────────────┘
```

---

## 提案目錄結構

```
stations/anvil/
├── src/
│   ├── server.py               # FastAPI main (port TBD)
│   ├── config.py               # pydantic-settings
│   ├── db.py                   # SQLAlchemy models + engine
│   ├── routes/
│   │   ├── skills.py           # Skill CRUD endpoints
│   │   ├── invocations.py      # 遙測查詢 endpoints
│   │   ├── evaluations.py      # Eval 觸發 + 結果 endpoints
│   │   ├── corrections.py      # 自我修正 endpoints
│   │   └── stats.py            # 聚合 + 儀表板 endpoints
│   ├── services/
│   │   ├── skill_registry.py   # Skill metadata 管理
│   │   ├── telemetry.py        # Invocation 記錄 + 聚合
│   │   ├── evaluator.py        # 三角驗證協調
│   │   ├── grader.py           # Grader subprocess 管理
│   │   ├── comparator.py       # Comparator subprocess 管理
│   │   ├── analyzer.py         # Analyzer subprocess 管理
│   │   └── corrector.py        # 自我修正引擎
│   └── agents/
│       ├── grader.md           # Grader agent prompt
│       ├── comparator.md       # Comparator agent prompt
│       └── analyzer.md         # Analyzer agent prompt
├── cli/
│   └── anvil.py                # 統一 CLI (argparse + SDK)
├── scripts/
│   ├── run_eval.py             # Subprocess 執行器 (claude -p)
│   └── init_db.py              # DB schema 建立
└── README.md

# Hook 遙測 — 掛載於 hook-observatory
stations/hook-observatory/handlers/anvil_telemetry.py

# SDK — Standalone HTTP client
libs/sdk-client/sdk_client/anvil.py

# MCP — SDK adapter
mcp/anvil/server.py

# Skill — 薄包裝層
~/.claude/skills/anvil/SKILL.md
```

---

## 成本與風險分析

### Token 成本估算

| 操作 | Tokens | 時間 |
|------|--------|------|
| 單一 eval 執行 (claude -p) | ~5K | ~30s |
| 完整 skill eval (3 cases × grader) | ~25K | ~3 min |
| + Comparator (regression 模式) | +12K | +1 min |
| + Analyzer | +5K | +20s |
| **單一 skill 完整 pipeline** | **~42K** | **~5 min** |
| **30 skills 批量** | **~1.3M** | **~2.5 hr** |

### 風險與緩解

| 風險 | 影響 | 緩解措施 |
|------|------|---------|
| evals.json 維護負擔（92+ skills） | 中 | 可選配，初期只覆蓋 Top 10-15 常用 skills |
| subprocess 巢狀呼叫失敗 | 高 | 移除 CLAUDECODE env var + timeout 保護 |
| Grader 判定不穩定 | 中 | 多次執行取 mean（`--runs 3`） |
| Token 消耗過大 | 中 | `--changed` 精準模式 + 成本預估提示 |
| 與原 skill-xxx 功能重疊混淆 | 低 | 明確文件：Anvil = 統一入口，原 skills = legacy |
| PostgreSQL 連線問題 | 低 | handler 非阻塞 + observability spool 仍記錄 |
| WebUI 效能（92+ nodes） | 低 | Canvas/WebGL 渲染 + 虛擬化 |
| 自我修正失控 | 高 | 分級制度 + Level 3 需人工批准 + worktree 隔離 |

---

## 遷移策略

### Phase 1: 並行運行

```
原 skill-xxx (9 個)  ──→  繼續運作
Anvil SDK + CLI     ──→  新建，吸收原邏輯
```

- 不動原 SKILL.md，不改原觸發
- Anvil CLI 可用後，兩套並存
- 使用者可選擇用原 skill 或 `anvil` CLI

### Phase 2: 驗證等價

- 對每個原 skill 功能，用 `anvil eval` 三角驗證 Anvil 版等價
- Anvil 版結果 ≥ 原版 → 標記 verified

### Phase 3: 退役原 Skills

- 修改原 SKILL.md → 加入 deprecation notice
- 或：原 SKILL.md 改為 thin wrapper，直接呼叫 `anvil <subcommand>`
- 最終：少爺確認後移除原 SKILL.md

---

## I/O Schema

```yaml
io:
  input:
    - mime: "application/json"
      description: "evals.json 測試定義"
    - mime: "text/markdown"
      description: "SKILL.md 待評估"
  output:
    - mime: "application/json"
      description: "benchmark.json, grading.json, stats"
    - mime: "text/html"
      description: "自包含 eval viewer"
    - mime: "text/markdown"
      description: "benchmark.md 摘要, correction 報告"
```
