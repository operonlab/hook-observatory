# Agent Vista — LLM CLI 即時視覺化監控平台

**研究日期**: 2026-02-24
**狀態**: Lab / POC 前期研究
**靈感來源**:
- [pablodelucca/pixel-agents](https://github.com/pablodelucca/pixel-agents) — 像素風 LLM agent 視覺化（VS Code Extension）
- [inventra/lazyoffice-opneclaw](https://github.com/inventra/lazyoffice-opneclaw) — 像素風虛擬辦公室 AI Agent Dashboard
- [Avatar Console](~/Claude/apps/avatar-console) — 少爺早期的多代理人命令控制台（V1 原型）

---

## 一、願景

將少爺電腦上**所有正在運行的 LLM CLI agent**（Claude Code sessions + sub-agents、Codex CLI、Gemini CLI）
以像素風格虛擬辦公室呈現，一眼看到每個 agent 在做什麼、是否需要操作、資源消耗多少。

**與 Pixel Agents 的差異**：
- Pixel Agents = VS Code Extension，僅支援 Claude Code
- Agent Vista = **獨立 Web App**，支援三種 CLI + 系統級進程監控

---

## 二、Avatar Console 遺產分析（少爺的 V1 原型）

### 專案概述

**Avatar Console** 是少爺早期開發的多代理人命令控制台，位於 `~/Claude/apps/avatar-console/`
（實際原始碼在 `~/.openclaw/workspace/openclaw_avator/`）。
以「紙娃娃演員」(paper-doll actors) 為核心 UI 隱喻，在一個視覺化舞台上管理多個 AI agent。

**技術棧**: Vue 3 + Pinia + Vite（前端）/ FastAPI + SQLite（後端）/ SSE + Polling（即時通訊）

### 與 Agent Vista 高度重疊的設計

| Avatar Console 既有設計 | 對應 Agent Vista 需求 | 繼承方式 |
|------------------------|---------------------|---------|
| **Actor 舞台隱喻** — 演員在舞台上各有位置，拖拽移動 | Agent 在虛擬辦公室各有座位 | 直接繼承概念，Canvas 化 |
| **狀態指示燈** — idle/working/offline/error 四態 | Agent 狀態 FSM | 擴展為 IDLE/WALK/TYPE/THINK/WAIT/ERROR |
| **訊息泡泡** — 自動顯示最後訊息，9 秒淡出 | 對話泡泡 overlay | 直接繼承，加上 tool name 顯示 |
| **SSE 即時推送** — Avatar Channel + EventSource | WebSocket 即時推送 | 升級為 WebSocket（雙向） |
| **Runtime 輪詢** — 每 3 秒 poll session 狀態 | Session Discovery 定期掃描 | 繼承輪詢策略，改為 file watching |
| **命令系統** — `/help`、`@mention` 註冊表 | 指令互動（可選） | 可繼承，非核心 |
| **Actor Store** — Pinia 狀態管理 + LocalStorage 持久化 | Agent 狀態管理 | 繼承雙層持久化模式 |
| **綠屏去背** — BFS 種子填充 + Spill 抑制（175 行） | 自訂 avatar 圖片處理 | 直接復用演算法 |
| **拖拽綁定 + 確認** — session 拖到 actor 觸發確認 | session 綁定 agent 角色 | 繼承 UX 流程 |
| **Adapter 中間層** — 解耦前端與後端 API 複雜性 | Parser Adapter 模式 | 繼承架構模式 |

### 可直接復用的程式碼

| 元件 | 檔案 | 行數 | 復用價值 |
|------|------|------|---------|
| 綠屏去背演算法 | `frontend/.../lib/chromaKey.js` | 175 | **高** — 自訂 avatar 圖片處理 |
| API 客戶端模式 | `frontend/.../lib/api.js` | 200+ | **中** — REST client 模式參考 |
| SSE 客戶端 | `frontend/.../lib/avatarChannel.js` | ~80 | **中** — EventSource 處理模式 |
| 狀態持久化 | `frontend/.../stores/actorStore.js` | 195 | **中** — LocalStorage + Server sync 模式 |
| Runtime 輪詢 | `frontend/.../stores/runtimeStore.js` | 185 | **中** — 輪詢策略參考 |

### Avatar Console 的限制（Agent Vista 需超越的）

| 限制 | 說明 | Agent Vista 解法 |
|------|------|-----------------|
| **OpenClaw 綁定** | 僅支援 OpenClaw Gateway API | 直接讀 transcript 檔案，零依賴 |
| **CSS 渲染** | 演員是 DOM 元素 + CSS transform | Canvas 2D 像素渲染（更流暢） |
| **無進程監控** | 不追蹤 CPU/Memory | gopsutil 系統級監控 |
| **無 token 統計** | 只看訊息內容 | 從 transcript 提取 token counts |
| **Vue 3** | 前端框架 | 改用 React（與 workshop workbench 統一） |
| **Python 後端** | FastAPI + SQLite | 改用 Go（single binary daemon） |
| **手動綁定** | 需手動將 session 拖拽到 actor | 自動偵測 + 自動綁定 |

### SPEC.md 中值得採納的功能規格

Avatar Console 的 `SPEC.md`（208 行）定義了幾個尚未實作但值得在 Agent Vista 實現的功能：

1. **廣播模式** — 對所有 agent 同時發送指令
2. **會議模式** (`#會議`) — 多 agent 協作討論
3. **並行分工模式** (`#並行分工`) — 同一任務拆給多個 agent 並行
4. **Usage Watchdog** — Provider 使用量監控 + 自動切換（詳見 `USAGE_WATCHDOG_PLAN.md`）

### Usage Watchdog 設計（可整合）

Avatar Console 規劃了一個 provider 智能切換系統：
- 每 30 分鐘檢查 provider 剩餘額度
- ≤ 15% → 警告通知
- ≤ 5% → 自動切換 fallback provider
- Provider 優先順序：OpenAI → Google → GitHub Copilot
- 冷卻時間結束後自動檢查高優先 provider 是否復原

**Agent Vista 可將此整合為 Token/Cost Dashboard 的一部分。**

---

## 三、Pixel Agents 原始架構分析

### 核心機制

```
Claude Code Terminal → JSONL transcript → fileWatcher (fs.watch + polling)
  → transcriptParser → postMessage → React + Canvas 2D → 像素角色動畫
```

### 技術棧
- **後端**: Node.js / TypeScript（VS Code Extension Host）
- **前端**: React 18 + Vite + Canvas 2D（像素完美渲染）
- **通訊**: VS Code postMessage（雙向）

### 值得借鑑的設計

| 設計 | 細節 | 借鑑價值 |
|------|------|---------|
| 增量 JSONL 讀取 | `fileOffset` + `lineBuffer` 處理 partial lines | 高 — 直接複製模式 |
| Tool 狀態 FSM | `agentToolStart` / `agentToolDone` / `agentToolPermission` | 高 — 統一三 CLI 的狀態抽象 |
| Permission Timer | 7s 無 progress → 判定等待許可 | 中 — 各 CLI 可能需要不同閾值 |
| 300ms Debounce | tool done 延遲發送防 UI flicker | 高 — 直接採用 |
| Hue-shift 著色 | sprite 色相偏移區分不同 agent | 高 — 用於區分 Claude/Codex/Gemini |
| Z-sort 渲染 | tiles → 家具 → 角色（依 y 座標深度排序） | 中 — 視覺層次參考 |

### 限制（需克服）

1. **VS Code 綁定** — 必須脫離，改為獨立 web server + 瀏覽器
2. **Claude Code 格式耦合** — `transcriptParser.ts` 深度綁定 Claude JSONL 結構
3. **無系統級監控** — 不追蹤 CPU/Memory/Token cost
4. **單一入口** — 只從 VS Code terminal 啟動，不偵測外部進程

---

## 三-B、LazyOffice 分析（像素風虛擬辦公室 Dashboard）

### 專案概述

[inventra/lazyoffice-opneclaw](https://github.com/inventra/lazyoffice-opneclaw) 是一個**像素風虛擬辦公室 Dashboard**，
將 AI Agent 團隊視覺化為像素角色（稱為 "sloths" 樹懶），在辦公室場景中即時呈現工作狀態、任務流轉、技能與記憶。

**技術棧**: Node.js + Express（後端）/ Vanilla JS + HTML + CSS（前端）/ PostgreSQL（DB）/ SSE（即時）/ Docker

### 與 Pixel Agents 的定位差異

| | Pixel Agents | LazyOffice |
|---|---|---|
| **平台** | VS Code Extension | 獨立 Web App |
| **後端** | Node.js (Extension Host) | Node.js + Express + PostgreSQL |
| **前端** | React + Canvas 2D | Vanilla JS + HTML/CSS |
| **Agent 偵測** | 讀 Claude JSONL transcript | 掃描 `~/.clawdbot/agents/` 目錄 |
| **Agent 管理** | 唯讀監控 | 完整 CRUD（名稱、職稱、頭像、技能、記憶） |
| **任務系統** | 無 | 任務 CRUD + 任務流轉動畫 |
| **Dashboard** | 無 | 成本 + 互動 + 安全三個儀表板 |
| **持久化** | `~/.pixel-agents/layout.json` | PostgreSQL + `office-layout.json` |

### Agent Vista 可借鑑的設計

| LazyOffice 設計 | 借鑑價值 | 說明 |
|-----------------|---------|------|
| **辦公室佈局 JSON 格式** | **高** | `leftPct`/`topPct`（百分比定位）+ `direction` + `scale` + `zIndex` — 比 Pixel Agents 的固定格座位更靈活 |
| **多辦公室支援** | **高** | `offices[]` 陣列支援多個辦公室場景（可用於分區：Claude 區/Codex 區/Gemini 區） |
| **部門分組概念** | **中** | `departments` 表 — Agent 可依 CLI 類型或專案分組 |
| **任務流轉動畫** | **高** | `task_flows` 記錄 from_agent → to_agent，視覺化任務在 agent 間的流動 — 適合呈現 sub-agent 委派 |
| **Token 使用記錄** | **高** | `token_usage_log` + `agent_daily_stats` — 直接對標 Agent Vista 的 Token/Cost Dashboard |
| **成本儀表板** | **高** | 7 天趨勢、成本節省計算、任務完成量 — 可整合 ccusage 資料 |
| **互動儀表板** | **中** | 對話數、處理字數、token 使用量、錯誤數 — 統計維度參考 |
| **Agent 內心獨白** | **低（趣味）** | 根據每日統計自動生成 Agent 的「內心想法」— 有趣但非核心 |
| **記憶檔案管理 UI** | **中** | 瀏覽/編輯/建立/下載 Agent 記憶 — 可整合少爺的 `memory/` 系統 |
| **AI 頭像生成** | **低** | KIE.ai API 生成 Agent 頭像 — 像素風下不需要 |
| **Port Scanner** | **低** | 安全功能，與視覺化監控無關 |
| **檔案系統 Agent 偵測** | **高** | 直接掃描 `~/.clawdbot/agents/` 解析 SOUL.md — 類似 Agent Vista 掃描三 CLI transcript 目錄 |

### LazyOffice 的佈局格式（值得參考）

```json
{
  "offices": [{
    "id": "office_main",
    "name": "主辦公室",
    "background": "office-bg.png",
    "sloths": [{
      "charId": "kevin",
      "name": "Kevin 小幫手",
      "role": "秘書/總指揮",
      "leftPct": 45.2,
      "topPct": 77.1,
      "direction": "sw",
      "scale": 200,
      "zIndex": 10
    }]
  }]
}
```

**優點**：百分比定位（響應式）、方向控制、縮放控制、圖層控制 — 比 Pixel Agents 的固定格 (tile x/y) 更適合自由佈局。

Agent Vista 可考慮**混合方案**：預設用 tile grid（像素風一致性），但支援自由定位模式。

### LazyOffice 的資料庫設計（Token 追蹤部分可參考）

```sql
-- 與 Agent Vista 相關的表
token_usage_log (agent_id, tokens_used, model, timestamp)
agent_daily_stats (agent_id, date, conversations, words_processed,
                   tokens_used, errors, compliments)
```

Agent Vista 可用類似結構追蹤從 transcript 解析出的 token 統計。

### LazyOffice 的限制（Agent Vista 需超越的）

| 限制 | 說明 |
|------|------|
| **Clawdbot 綁定** | 僅支援 OpenClaw/Clawdbot agent 框架 |
| **非 Canvas 渲染** | 用 HTML/CSS 定位像素圖片，非真正的 Canvas 2D |
| **無 transcript 解析** | 不讀取 agent 的即時工作記錄，只讀設定檔 |
| **無增量監控** | 需手動觸發 `POST /api/agents/detect`，非即時偵測 |
| **Vanilla JS** | 無前端框架，大型應用維護困難 |
| **PostgreSQL 依賴** | daemon 需要 PostgreSQL，增加部署複雜度 |

---

## 四、三大 CLI Transcript 格式調查

### 3.1 Claude Code

| 項目 | 內容 |
|------|------|
| **格式** | JSONL（逐行追加） |
| **路徑** | `~/.claude/projects/<project-hash>/<session-id>.jsonl` |
| **Record Types** | `assistant`、`user`、`system`、`progress` |
| **Tool 追蹤** | `tool_use` blocks（含 id/name/input）、`tool_result` blocks |
| **Sub-agent** | `agent_progress` record type 追蹤 Task tool 內的子 agent |
| **Hook 系統** | 9 個事件（PreToolUse、PostToolUse 等） |
| **監控方式** | `fs.watch` + polling（Pixel Agents 已驗證可行） |
| **即時性** | 即時寫入，延遲 ~10-100ms（OS FSEvents） |

### 3.2 Codex CLI

| 項目 | 內容 |
|------|------|
| **格式** | JSONL（Rollout session files） |
| **路徑** | `~/.codex/sessions/YYYY/MM/DD/rollout-{timestamp}-{uuid}.jsonl` |
| **Record Types** | `session_meta`、`response_item`、`event_msg`、`turn_context` |
| **Tool 追蹤** | `function_call`（內建 tool）+ `custom_tool_call`（MCP tool），含 name/args/call_id |
| **結果追蹤** | `function_call_output`（stdout/stderr/exit code/wall time） |
| **Token 統計** | `event_msg` type=`token_count`，含 rate_limits |
| **Hook 系統** | 無（僅 prepare-commit-msg git hook） |
| **替代方案** | App Server JSON-RPC 2.0 protocol（item/started、item/completed 等 notifications） |
| **監控方式** | File watching（推薦）或 App Server stdio |
| **少爺資料** | 79MB session 資料，65 行 history |

### 3.3 Gemini CLI

| 項目 | 內容 |
|------|------|
| **格式** | JSON（單檔完整對話，持續更新 `lastUpdated`） |
| **路徑** | `~/.gemini/tmp/<project-hash>/chats/session-{timestamp}-{id}.json` |
| **Message Types** | `user`、`gemini` |
| **Tool 追蹤** | `toolCalls` 陣列（id/name/args/result/status/timestamp） |
| **思考過程** | `thoughts` 陣列（subject/description/timestamp） |
| **Token 統計** | per-message `tokens` 物件（input/output/cached/thoughts/tool/total） |
| **Hook 系統** | 11 個事件（BeforeTool/AfterTool/BeforeModel/AfterModel 等），協議與 Claude Code 幾乎一致 |
| **Activity Log** | JSONL 格式，需設 `GEMINI_CLI_ACTIVITY_LOG_TARGET` 啟用 |
| **OpenTelemetry** | 原生支援 OTLP 匯出 |
| **少爺資料** | 703 個 session，31 個 project hash |

### 格式統一性評估

```
           Claude Code          Codex CLI           Gemini CLI
格式       JSONL (追加)          JSONL (追加)        JSON (覆寫)
即時性     即時                  即時                 即時 (lastUpdated)
Hook       9 events             無                   11 events
OTel       無                   無                   原生支援
Token      有                   有 (rate_limits)     有 (分類詳細)
```

**關鍵發現**: 三者都有足夠的 transcript 資料，但格式完全不同。需要 **per-CLI parser adapter**。

---

## 五、統一資料模型設計（草案）

```
AgentEvent {
  cli_type:    "claude" | "codex" | "gemini"
  session_id:  string
  timestamp:   ISO8601
  event_type:  "tool_start" | "tool_done" | "tool_permission"
             | "message" | "thinking" | "idle" | "waiting"
             | "session_start" | "session_end"
  tool_name?:  string          // Read, Bash, exec_command, run_shell_command...
  tool_input?: string          // 摘要（截斷）
  tool_status?: "running" | "success" | "error"
  tokens?: {
    input:  number
    output: number
    total:  number
  }
  metadata?: Record<string, any>  // CLI-specific 額外資訊
}
```

### Parser Adapter 介面

```
trait TranscriptParser {
  fn detect(path: &Path) -> bool;            // 這個檔案是我負責的嗎？
  fn parse_incremental(bytes: &[u8]) -> Vec<AgentEvent>;  // 增量解析
  fn session_info() -> SessionMeta;          // session metadata
}
```

三個實作：`ClaudeParser`、`CodexParser`、`GeminiParser`

---

## 六、後端選型分析

### 需求規模

| 指標 | 數值 |
|------|------|
| 監控檔案數 | 3-15 個 JSONL/JSON |
| WebSocket 連線 | 1-3 個瀏覽器 |
| 並行 session | 5-15 個 LLM agent |
| 事件頻率 | ~1-50 events/s |

**這是一個極低負載的場景**。瓶頸在 OS 檔案事件延遲（~10-100ms），而非語言效能。

### 四語言比較

| | Rust | Go | Python | Bun/Node |
|---|---|---|---|---|
| **記憶體 (idle)** | ~3-6 MB | ~10-18 MB | ~50-90 MB | ~35-55 MB |
| **延遲 (處理)** | <1 ms | <2 ms | <10 ms | <3 ms |
| **編譯/啟動** | ~1-3 min / <10ms | ~3-8s / <20ms | N/A / ~500ms | N/A / ~100ms |
| **開發速度** | 慢（4 週上手） | 快（1 週上手） | 最快（熟悉） | 快 |
| **分發** | single binary | single binary | 需 Python env | 需 Bun/Node |
| **檔案監控** | notify (FSEvents) | fsnotify (kqueue) | watchdog | fs.watch |
| **WebSocket** | axum (tokio) | coder/websocket | FastAPI WS | 內建 |

### 建議：Go

**核心理由**：

1. **開發速度 vs 效能的最佳平衡點** — 8s 編譯 vs Rust 的 3 分鐘，POC 迭代效率差 5-10 倍
2. **goroutine 天然契合** — 每個監控檔案一個 goroutine，模型簡潔直觀
3. **single binary** — `go build` 一行，macOS arm64 原生，分發零摩擦
4. **效能遠超需求** — 50 events/s 連 CPU 都量不到
5. **社群先例** — Prometheus/Grafana/Loki 等監控工具都是 Go

**如果少爺想用 Rust**：完全可行，但初版完成時間預估是 Go 的 3-4 倍。
如果這是「學 Rust 的練手專案」，那是另一個好理由。

**快速原型備選**：Python（FastAPI + watchdog），2 小時內可出 MVP，但不適合長期 daemon。

### Go 技術棧

```go
require (
    github.com/fsnotify/fsnotify v1.8.0      // 檔案監控
    github.com/coder/websocket   v1.8.12     // WebSocket（nhooyr 繼任者）
    github.com/shirou/gopsutil/v3 v3.24.5    // 進程監控
)
```

### Rust 技術棧（備選）

```toml
notify = "8.2"             # 檔案監控（FSEvents 後端）
axum = "0.8"               # Web + WebSocket
tokio = "1"                # async runtime
serde = "1"                # JSON 解析
sysinfo = "0.32"           # 進程監控
```

---

## 七、系統架構設計

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (React + Canvas 2D)           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ Office   │  │ Agent    │  │ Resource │  │ Session │ │
│  │ Canvas   │  │ Detail   │  │ Monitor  │  │ List    │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
└──────────────────────┬──────────────────────────────────┘
                       │ WebSocket
┌──────────────────────┴──────────────────────────────────┐
│                   Agent Vista Server (Go)                │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ File Watcher │  │ Event Broker │  │ HTTP/WS Server │ │
│  │ (fsnotify)  │──│  (fan-out)   │──│ (coder/ws)     │ │
│  └──────┬──────┘  └──────────────┘  └────────────────┘ │
│         │                                               │
│  ┌──────┴───────────────────────────────────┐           │
│  │           Parser Adapters                 │           │
│  │  ┌─────────┐ ┌─────────┐ ┌────────────┐ │           │
│  │  │ Claude  │ │ Codex   │ │ Gemini     │ │           │
│  │  │ Parser  │ │ Parser  │ │ Parser     │ │           │
│  │  └─────────┘ └─────────┘ └────────────┘ │           │
│  └──────────────────────────────────────────┘           │
│                                                         │
│  ┌──────────────┐  ┌───────────────────────┐            │
│  │ Process      │  │ Session Discovery     │            │
│  │ Monitor      │  │ (scan new sessions)   │            │
│  │ (gopsutil)   │  │                       │            │
│  └──────────────┘  └───────────────────────┘            │
└─────────────────────────────────────────────────────────┘
         │                        │
    ┌────┴────┐          ┌───────┴────────────────────┐
    │ ps aux  │          │ Transcript Files            │
    │ claude  │          │ ~/.claude/projects/**/*.jsonl│
    │ codex   │          │ ~/.codex/sessions/**/*.jsonl │
    │ gemini  │          │ ~/.gemini/tmp/**/chats/*.json│
    └─────────┘          └────────────────────────────┘
```

### 模組職責

| 模組 | 職責 |
|------|------|
| **Session Discovery** | 定期掃描三個 CLI 的 transcript 目錄，偵測新/消失的 session |
| **File Watcher** | fsnotify 監控活躍 session 檔案，偵測內容變更 |
| **Parser Adapters** | 三個 CLI 各一個 adapter，將 raw transcript → 統一 `AgentEvent` |
| **Event Broker** | 收集所有 AgentEvent，fan-out 廣播到所有 WebSocket 連線 |
| **Process Monitor** | gopsutil 掃描 `claude`/`codex`/`gemini` 進程的 CPU/Memory |
| **HTTP/WS Server** | 提供靜態前端 + WebSocket endpoint + REST API |

### Session Discovery 策略

```
每 2 秒掃描：
  ~/.claude/projects/*/conversations/  → 找最新 .jsonl
  ~/.codex/sessions/YYYY/MM/DD/        → 找最新 rollout-*.jsonl
  ~/.gemini/tmp/*/chats/               → 找 lastUpdated 最近的 .json

新 session 出現 → 啟動 goroutine 監控
session 30 分鐘無更新 → 標記 idle
session 檔案消失 → 清理
```

---

## 八、前端視覺化方案

### 核心保留：Canvas 2D + Pixel Art

Pixel Agents 的視覺風格是其最大特色，值得保留。但需要擴展：

| 視覺元素 | Pixel Agents | Agent Vista |
|---------|-------------|-------------|
| 角色外觀 | 統一像素人 | 三種 CLI 各有獨特角色造型 |
| 顏色區分 | hue-shift | CLI 類型色系 + hue-shift 個體區分 |
| 狀態動畫 | IDLE/WALK/TYPE | + THINKING/WAITING/ERROR |
| 辦公室佈局 | 單一房間 | 分區（Claude 區/Codex 區/Gemini 區）或混合 |
| 資訊 overlay | tool name | + token count + elapsed time |
| Dashboard | 無 | 側邊欄：session 列表 + 資源使用圖表 |

### 角色設計概念

```
Claude Code agents → 藍色系管家角色（呼應阿福/賈維斯）
Codex CLI agents  → 綠色系工程師角色
Gemini CLI agents → 紫色系研究員角色
Sub-agents        → 縮小版（50%）跟隨在主 agent 旁邊
```

---

## 九、與 Workshop 既有基礎設施的整合

| 既有元件 | 整合方式 |
|---------|---------|
| **Avatar Console (V1)** | 繼承舞台隱喻、狀態指示燈、訊息泡泡、chromaKey、輪詢策略等核心 UX 設計 |
| **Avatar Console Usage Watchdog** | 整合為 Token/Cost Dashboard，provider 額度監控 + 自動切換 |
| **Hooks Observability Bridge** | Agent Vista 可作為 bridge 的消費者，接收 hook 事件做即時視覺化 |
| **stations/system-monitor** | 共用 process monitoring 邏輯，或合併 |
| **stations/agent-metrics** | token/cost 統計可整合到 Agent Vista dashboard |
| **Claude Squad (`cs`)** | 互補 — cs 管理 sessions，Agent Vista 視覺化狀態 |
| **ccusage** | 歷史用量分析，Agent Vista 即時用量 |

### 畢業路徑

```
lab/agent-vista/ (POC)
  → 驗證三 CLI 監控可行性
  → 驗證 Canvas 2D 視覺化效果
  → 確認效能足夠（<20MB RAM, <1% CPU）
  ↓
stations/agent-vista/ (畢業)
  → 作為 standalone local tool
  → 可選整合到 workbench 前端
```

---

## 十、實作路線圖

### Phase 0 — 可行性驗證（1-2 天）

- [ ] Go 專案初始化
- [ ] Claude JSONL 增量讀取 + 解析
- [ ] 最簡 WebSocket server（推送 raw events）
- [ ] 瀏覽器 console 驗證事件流

### Phase 1 — 三 CLI 監控（3-5 天）

- [ ] Codex JSONL parser adapter
- [ ] Gemini JSON parser adapter
- [ ] Session discovery（自動偵測新 session）
- [ ] 統一 AgentEvent 模型
- [ ] Process monitor（CPU/Memory per agent）

### Phase 2 — 前端視覺化（5-7 天）

- [ ] React + Canvas 2D 基礎框架
- [ ] Pixel art sprite 系統（角色 + 辦公室）
- [ ] Agent 狀態 FSM（IDLE/WALK/TYPE/THINK/WAIT）
- [ ] WebSocket 連線 + 即時更新
- [ ] CLI 類型視覺區分

### Phase 3 — Dashboard + 精修（3-5 天）

- [ ] Session 列表側邊欄
- [ ] Token/Cost 即時統計
- [ ] Resource usage 圖表
- [ ] 佈局編輯器（自訂辦公室）
- [ ] 音效通知（permission needed）

---

## 十一、風險與緩解

| 風險 | 影響 | 緩解 |
|------|------|------|
| Gemini CLI JSON 非 append-only | Parser 需要 diff-based 更新 | 用 `lastUpdated` + 全檔重解析（檔案小，可接受） |
| Codex CLI 無 hook 系統 | 無法即時攔截事件 | File watching 已足夠（Codex 即時寫入 JSONL） |
| Claude Code JSONL 格式變更 | Parser 壞掉 | 版本偵測 + graceful degradation |
| Canvas 2D 效能（>20 agents） | 掉幀 | 視口裁剪（只渲染可見區域）+ requestAnimationFrame 節流 |
| Go 生態不熟 | 開發速度降低 | 核心邏輯簡單，~1000 行 Go 足矣 |

---

## 十二、社群現況與差異化

### 現有方案（無一站式解決）

| 方案 | 類型 | 限制 |
|------|------|------|
| Pixel Agents | VS Code Extension | 僅 Claude Code，VS Code 綁定 |
| **LazyOffice** | **Web Dashboard** | **僅 Clawdbot/OpenClaw，非即時 transcript 解析** |
| Claude Squad | TUI 管理器 | 僅 Claude Code，無視覺化 |
| LangWatch / Langfuse | Observability 平台 | 需要 SDK 整合，非 CLI 原生 |
| Prometheus + Grafana | Metrics Dashboard | 需自寫 exporter，無像素風 |

### Agent Vista 的差異化

1. **三 CLI 統一視覺化** — 唯一支援 Claude + Codex + Gemini 的方案
2. **零侵入** — 純讀 transcript 檔案，不修改任何 CLI
3. **像素風** — 開發者文化 + 趣味感知（Pixel Agents 已驗證需求）
4. **獨立部署** — single binary，不綁定 IDE

---

## 十三、設計譜系 — 三個來源匯流成 Agent Vista

```
Avatar Console (V1)        Pixel Agents (社群)       LazyOffice (社群)
├─ 舞台隱喻               ├─ 像素辦公室              ├─ 像素辦公室 + 多房間
├─ CSS 渲染               ├─ Canvas 2D               ├─ HTML/CSS 定位
├─ SSE + 3s 輪詢          ├─ postMessage              ├─ SSE 即時
├─ OpenClaw API 綁定      ├─ Claude JSONL 綁定        ├─ Clawdbot 目錄掃描
├─ Vue 3 + Pinia          ├─ React 18                 ├─ Vanilla JS
├─ FastAPI + SQLite        ├─ Node.js (Ext Host)      ├─ Express + PostgreSQL
├─ 綠屏去背               ├─ Hue-shift 著色           ├─ AI 頭像 (KIE.ai)
├─ 狀態燈 (4 態)          ├─ Tool FSM (3 態)          ├─ 狀態追蹤
├─ 訊息泡泡               ├─ 對話泡泡                 ├─ 無
├─ 拖拽綁定               ├─ 自動座位分配             ├─ % 定位 + scale + zIndex
├─ Usage Watchdog          ├─ 無                      ├─ Token log + 成本儀表板
├─ 命令系統               ├─ 無                       ├─ 任務流轉動畫
└─ 無                     └─ 無                       └─ 部門分組 + 記憶管理
         │                         │                          │
         └─────────────────────────┼──────────────────────────┘
                                   │
                            Agent Vista (2026)
                            ├─ 像素辦公室 + 舞台隱喻 + 多房間（三者合併）
                            ├─ Canvas 2D 像素渲染（from Pixel Agents）
                            ├─ WebSocket 雙向通訊（升級 SSE）
                            ├─ 三 CLI transcript 直讀（零依賴）
                            ├─ React（統一 workshop 前端）
                            ├─ Go daemon（single binary，無 PostgreSQL 依賴）
                            ├─ Hue-shift + CLI 類型色系（合併）
                            ├─ 擴展 FSM（6 態）
                            ├─ 對話泡泡 + tool overlay（合併）
                            ├─ 自動偵測 + 手動調整 + % 自由定位（合併）
                            ├─ Token/Cost Dashboard（Usage Watchdog + LazyOffice 融合）
                            ├─ 任務流轉動畫（sub-agent 委派視覺化）
                            └─ CLI 類型分組（from 部門概念）
```

### 核心演進（四方比較）

| 面向 | Avatar Console | Pixel Agents | LazyOffice | **Agent Vista** |
|------|---------------|-------------|------------|----------------|
| **Agent 來源** | OpenClaw API | Claude JSONL | Clawdbot 目錄 | **三 CLI transcript** |
| **支援範圍** | OpenClaw only | Claude only | Clawdbot only | **Claude + Codex + Gemini** |
| **渲染** | CSS DOM | Canvas 2D | HTML/CSS | **Canvas 2D** |
| **即時通訊** | SSE + polling | postMessage | SSE | **WebSocket** |
| **後端** | Python/FastAPI | Node.js (VSC) | Express + PG | **Go daemon** |
| **分發** | Python + Nginx | VS Code ext | Docker Compose | **single binary** |
| **佈局儲存** | LocalStorage | layout.json (tiles) | layout.json (%) | **混合（tile + %）** |
| **Token 追蹤** | 無 | 無 | PG table | **從 transcript 解析** |
| **任務流轉** | 無 | 無 | 有 (task_flows) | **sub-agent 委派** |
| **多房間** | 無 | 無 | 有 (offices[]) | **CLI 類型分區** |
| **Agent 管理** | 拖拽綁定 | 自動分配 | 完整 CRUD | **自動偵測 + 手動調整** |
| **安全** | 無 | 無 | Port Scanner | **非核心** |

---

## 附錄 A：少爺機器上的 Transcript 資料量

| CLI | 路徑 | 資料量 |
|-----|------|--------|
| Claude Code | `~/.claude/projects/` | 待確認 |
| Codex CLI | `~/.codex/sessions/` | 79 MB, 多個 session |
| Gemini CLI | `~/.gemini/tmp/*/chats/` | 703 個 session, 31 個 project |

## 附錄 B：參考資料

- [pablodelucca/pixel-agents](https://github.com/pablodelucca/pixel-agents) — 像素風 agent 視覺化（VS Code）
- [inventra/lazyoffice-opneclaw](https://github.com/inventra/lazyoffice-opneclaw) — 像素風虛擬辦公室 Dashboard
- [openai/codex](https://github.com/openai/codex) — Codex CLI 原始碼
- [google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) — Gemini CLI 原始碼
- [Codex App Server Protocol](https://developers.openai.com/codex/app-server/)
- [Gemini CLI Hooks](https://geminicli.com/docs/hooks/)
- [fsnotify/fsnotify](https://github.com/fsnotify/fsnotify) — Go 檔案監控
- [coder/websocket](https://github.com/coder/websocket) — Go WebSocket
- [notify-rs/notify](https://github.com/notify-rs/notify) — Rust 檔案監控（備選）
- Avatar Console SPEC.md — `~/.openclaw/workspace/openclaw_avator/SPEC.md`
- Avatar Console Usage Watchdog — `~/.openclaw/workspace/openclaw_avator/USAGE_WATCHDOG_PLAN.md`
- Avatar Console chromaKey.js — `~/.openclaw/workspace/openclaw_avator/frontend/avatar-console/src/lib/chromaKey.js`
