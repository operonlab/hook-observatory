# Agent Vista — SPEC

**Version**: 0.1.0 (Draft)
**Status**: Lab / Pre-POC
**Location**: `~/workshop/lab/agent-vista/`
**Graduation Target**: `~/workshop/stations/agent-vista/`

---

## 1. 產品定義

### 1.1 一句話描述

像素風虛擬辦公室，即時視覺化本地所有 LLM CLI agent 的工作狀態。

### 1.2 目標使用者

在同一台機器上同時運行多個 LLM CLI session 的開發者（少爺的三腦架構：Claude Code + Codex CLI + Gemini CLI）。

### 1.3 核心價值

| 價值 | 說明 |
|------|------|
| **一眼全覽** | 所有 agent 的即時狀態在一個畫面上 |
| **零侵入** | 純讀 transcript 檔案，不修改任何 CLI 工具 |
| **趣味感知** | 像素風動畫讓枯燥的監控變有趣 |
| **輕量常駐** | Single binary daemon，<20MB RAM |

### 1.4 非目標

- 不是 agent orchestrator（不啟動/停止 agent）
- 不是 prompt 編輯器（不發送訊息給 agent）
- 不是 observability platform（不做 tracing/alerting）
- 不替代 Claude Squad（cs 管理 session，Vista 視覺化狀態）

---

## 2. 系統架構

### 2.1 高層架構

```
Browser (React + Canvas 2D)
    │ WebSocket (ws://localhost:PORT) + REST polling (1.5s)
    ▼
Agent Vista Server (Go, single binary)
    ├── Session Discovery    — 掃描三 CLI 的 transcript 目錄
    ├── File Watcher         — fsnotify 監控活躍 session 檔案
    ├── Parser Adapters      — Claude / Codex / Gemini 各一
    ├── Event Broker         — fan-out 到所有 WebSocket 連線
    ├── Process Monitor      — gopsutil 掃描 LLM CLI 進程
    └── HTTP/WS Server       — 靜態前端 + WebSocket + REST API
    │
    ▼
Transcript Files (read-only)
    ├── ~/.claude/projects/<hash>/conversations/*.jsonl
    ├── ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
    └── ~/.gemini/tmp/<hash>/chats/session-*.json
```

### 2.2 後端技術棧

| 元件 | 技術 | 版本 |
|------|------|------|
| 語言 | Go | 1.22+ |
| 檔案監控 | fsnotify/fsnotify | v1.8+ |
| WebSocket | coder/websocket | v1.8+ |
| 進程監控 | shirou/gopsutil | v3.24+ |
| HTTP | net/http (stdlib) | - |
| JSON | encoding/json (stdlib) | - |

### 2.3 前端技術棧

| 元件 | 技術 | 版本 |
|------|------|------|
| 框架 | React | 19 |
| 構建 | Vite (or Rsbuild) | latest |
| 渲染 | Canvas 2D API | - |
| 狀態 | zustand (or jotai) | latest |
| 語言 | TypeScript | 5.x |

---

## 3. 資料模型

### 3.1 AgentEvent（核心事件）

```typescript
interface AgentEvent {
  cli_type:     "claude" | "codex" | "gemini"
  session_id:   string
  agent_id:     string       // 自動生成的穩定 ID
  timestamp:    string       // ISO 8601
  event_type:   AgentEventType
  tool_name?:   string
  tool_input?:  string       // 截斷至 200 chars
  tool_status?: "running" | "success" | "error"
  tokens?: {
    input:   number
    output:  number
    cached?: number
    total:   number
  }
  sub_agent?:   boolean      // 是否為 sub-agent 事件
  parent_id?:   string       // sub-agent 的父 agent ID
  metadata?:    Record<string, unknown>
}

type AgentEventType =
  | "tool_start" | "tool_done" | "tool_permission"
  | "message" | "thinking" | "idle" | "waiting"
  | "session_start" | "session_end"
  | "sub_agent_start" | "sub_agent_end"
```

### 3.2 AgentState（前端狀態）

```typescript
interface AgentState {
  id:           string
  cli_type:     "claude" | "codex" | "gemini"
  session_id:   string
  display_name: string      // session 名稱或 project 名
  status:       AgentStatus
  current_tool?: string
  tool_detail?:  string
  tokens_total:  number
  last_active:   number     // unix ms
  position:      { x: number, y: number }  // 辦公室座標
  animation:     AnimationState
  sub_agents:    AgentState[]
}

type AgentStatus = "active" | "thinking" | "typing" | "reading"
                 | "waiting" | "idle" | "offline" | "error"

type AnimationState = "IDLE" | "WALK" | "TYPE" | "THINK" | "WAIT" | "ERROR"
```

### 3.3 OfficeLayout（佈局持久化）

```typescript
interface OfficeLayout {
  version:    number
  offices:    Office[]
  active_office: string
}

interface Office {
  id:          string
  name:        string       // "主辦公室", "Claude 區", ...
  background?: string       // 背景 sprite 名稱
  width:       number       // tiles
  height:      number       // tiles
  furniture:   Furniture[]
  agent_seats: AgentSeat[]
}

interface AgentSeat {
  agent_id:   string
  tile_x:     number
  tile_y:     number
  direction:  "up" | "down" | "left" | "right"
  // 可選：自由定位模式
  free_position?: { left_pct: number, top_pct: number, scale: number, z_index: number }
}
```

**儲存位置**: `~/.agent-vista/layout.json`

---

## 4. Transcript 解析規格

### 4.1 Parser Adapter 介面

```go
type TranscriptParser interface {
    // 判斷此檔案是否由此 parser 負責
    Detect(path string) bool

    // 增量解析新增 bytes，返回解析出的事件
    ParseIncremental(newBytes []byte) ([]AgentEvent, error)

    // 取得 session 元資訊
    SessionInfo() SessionMeta

    // 重置狀態（session 重新開始時）
    Reset()
}

type SessionMeta struct {
    SessionID   string
    CLIType     string
    ProjectDir  string
    StartTime   time.Time
    Model       string
}
```

### 4.2 Claude Code Parser

| 項目 | 規格 |
|------|------|
| 格式 | JSONL（逐行追加） |
| 路徑 | `~/.claude/projects/<hash>/conversations/<session>.jsonl` |
| 偵測 | 路徑含 `.claude/projects` 且副檔名 `.jsonl` |
| 解析 | 增量讀取 — `fileOffset` + `lineBuffer` 處理 partial lines |
| record.type=`assistant` + `tool_use` | → `tool_start` 事件 |
| record.type=`user` + `tool_result` | → `tool_done` 事件 |
| record.type=`system` + subtype=`turn_duration` | → 清除所有活動狀態 |
| record.type=`progress` + `agent_progress` | → `sub_agent_*` 事件 |

**Tool 名稱 → 動畫映射**:

| Tool | 動畫 | 顯示文字 |
|------|------|---------|
| Read | 閱讀 | `Reading [file]` |
| Edit, Write | 打字 | `Editing [file]` / `Writing [file]` |
| Bash | 打字 | `Running: [cmd]` |
| Grep, Glob | 閱讀 | `Searching code` / `Searching files` |
| WebFetch, WebSearch | 閱讀 | `Fetching web` / `Searching web` |
| Task | 打字 | `Subtask: [desc]` |
| AskUserQuestion | 等待 | `Waiting for input` |
| 其他 | 閱讀 | `Using [toolName]` |

### 4.3 Codex CLI Parser

| 項目 | 規格 |
|------|------|
| 格式 | JSONL（逐行追加） |
| 路徑 | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |
| 偵測 | 路徑含 `.codex/sessions` 且檔名以 `rollout-` 開頭 |
| 解析 | 增量讀取（同 Claude） |
| type=`session_meta` | → `session_start` + 提取 model/cwd |
| type=`response_item` + `function_call` | → `tool_start`（name, arguments, call_id） |
| type=`response_item` + `function_call_output` | → `tool_done`（stdout, exit_code） |
| type=`response_item` + `custom_tool_call` | → `tool_start`（MCP tool） |
| type=`event_msg` + `task_complete` | → 清除所有活動狀態 |
| type=`event_msg` + `token_count` | → 更新 tokens |

**Tool 名稱映射**:

| Codex Tool | 統一名稱 | 動畫 |
|-----------|---------|------|
| exec_command | Bash | 打字 |
| apply_patch | Edit | 打字 |
| read_file | Read | 閱讀 |
| 其他 function_call | 原名 | 閱讀 |

### 4.4 Gemini CLI Parser

| 項目 | 規格 |
|------|------|
| 格式 | JSON（單檔覆寫式） |
| 路徑 | `~/.gemini/tmp/<hash>/chats/session-*.json` |
| 偵測 | 路徑含 `.gemini/tmp` 且檔名以 `session-` 開頭 |
| 解析 | **Diff-based** — 比較 `lastUpdated` + message count → 只處理新增 messages |
| message.type=`gemini` + `toolCalls` | → 每個 toolCall 產生 `tool_start` + `tool_done` |
| message.type=`gemini` + `thoughts` | → `thinking` 事件 |
| message.tokens | → 更新 tokens（input/output/cached/thoughts/tool） |

**Tool 名稱映射**:

| Gemini Tool | 統一名稱 | 動畫 |
|-----------|---------|------|
| run_shell_command | Bash | 打字 |
| edit_file | Edit | 打字 |
| read_file | Read | 閱讀 |
| search_files | Grep | 閱讀 |
| 其他 | 原名 | 閱讀 |

**Gemini 特殊處理**:
- JSON 非 append-only → 每次 `lastUpdated` 變更時全檔重解析
- 用 `messages.length` 差值判斷新增 messages
- 檔案通常 <500KB，全檔解析效能可接受

---

## 5. 通訊協定

### 5.1 WebSocket 訊息格式

**Server → Client**:

```typescript
// 初始化：發送所有活躍 agent 的當前狀態
{ type: "init", agents: AgentState[] }

// Agent 事件（增量更新）
{ type: "event", event: AgentEvent }

// Agent 上線
{ type: "agent_online", agent: AgentState }

// Agent 離線
{ type: "agent_offline", agent_id: string }

// 進程資源快照（每 5 秒）
{ type: "resource_snapshot", processes: ProcessInfo[] }
```

**Client → Server**:

```typescript
// 保存佈局
{ type: "save_layout", layout: OfficeLayout }

// 請求重新掃描 sessions
{ type: "rescan" }
```

### 5.2 REST API

| Method | Path | 說明 |
|--------|------|------|
| GET | `/` | 靜態前端 (React build) |
| GET | `/api/agents` | 當前所有 agent 狀態 |
| GET | `/api/agents/:id` | 單一 agent 詳情 |
| GET | `/api/layout` | 取得辦公室佈局 |
| PUT | `/api/layout` | 儲存佈局 |
| GET | `/api/stats` | Token/Cost 統計摘要 |
| POST | `/api/rescan` | 觸發重新掃描 |
| GET | `/ws` | WebSocket 升級端點 |

---

## 6. 前端視覺化規格

### 6.1 設計目標

**以 Pixel Agents 的動畫效果為最終目標** — Canvas 2D 像素完美渲染，
角色有限狀態機驅動動畫，虛擬辦公室場景含家具/地板/牆壁。

### 6.2 渲染引擎

| 項目 | 規格 |
|------|------|
| 技術 | HTML Canvas 2D API |
| 縮放 | 整數倍縮放（不用 `ctx.scale(dpr)`），確保像素清晰 |
| 幀率 | requestAnimationFrame，目標 30fps |
| Sprite | 2D hex 色彩字串陣列 → offscreen canvas → WeakMap 快取（per zoom level） |
| 渲染順序 | Floor tiles → Seat indicators → Z-sort scene → Speech bubbles → Overlays |
| Z-sort | 家具 + 牆壁 + 角色 混合排序（依 y 座標） |
| 相機 | Zoom (滾輪) + Pan (拖拽) |

### 6.3 角色系統

**有限狀態機（6 態）**:

```
                    ┌──────────────┐
                    │    IDLE      │ ← 預設態，BFS 隨機漫遊
                    └──────┬───────┘
                           │ tool_start / message
                    ┌──────▼───────┐
            ┌───────│    WALK      │ ← 尋路到座位
            │       └──────┬───────┘
            │              │ 到達座位
            │       ┌──────▼───────┐
            │   ┌───│    TYPE      │ ← Write/Edit/Bash 動畫
            │   │   └──────────────┘
            │   │   ┌──────────────┐
            │   ├───│   THINK      │ ← reasoning/planning 動畫
            │   │   └──────────────┘
            │   │   ┌──────────────┐
            │   ├───│    WAIT      │ ← permission needed / idle timeout
            │   │   └──────────────┘
            │   │   ┌──────────────┐
            │   └───│   ERROR      │ ← tool error / process crash
            │       └──────────────┘
            │              │ session_end / 30min idle
            │       ┌──────▼───────┐
            └───────│  DESPAWN     │ ← Matrix 數位雨特效
                    └──────────────┘
```

**Sprite 方向**: 4 方向（down/up/right/left，各有獨立 sprite + 水平翻轉變體）

**動畫幀映射**:

| 觸發條件 | 動畫態 | 描述 |
|---------|--------|------|
| Write / Edit / Bash / Task | TYPE | 坐在座位打字 |
| Read / Grep / Glob / WebFetch | TYPE (閱讀變體) | 坐在座位閱讀 |
| thinking / reasoning | THINK | 頭上顯示思考泡泡 |
| AskUserQuestion / permission timeout | WAIT | 頭上顯示 "!" 泡泡 |
| tool error | ERROR | 角色頭上顯示 "X" |
| 無活動 | IDLE | BFS 隨機漫遊 |

### 6.4 CLI 類型視覺區分

| CLI | 基礎色系 | 角色風格 | 標識 |
|-----|---------|---------|------|
| Claude Code | 藍色 (#4A90D9) | 管家 | "C" 徽章 |
| Codex CLI | 綠色 (#4CAF50) | 工程師 | "X" 徽章 |
| Gemini CLI | 紫色 (#9C27B0) | 研究員 | "G" 徽章 |

**個體區分**: 同一 CLI 的不同 session 用 hue-shift（色相偏移 ±30°）區分。

**Sub-agent**: 縮小至主 agent 的 50%，跟隨在主 agent 旁邊。

### 6.5 對話泡泡 / 狀態 Overlay

| 觸發條件 | 顯示內容 | 持續時間 |
|---------|---------|---------|
| tool_start | Tool 名稱 + 摘要（如 `Reading config.ts`） | 持續到 tool_done |
| tool_permission | "Needs permission!" + 閃爍 | 持續到用戶回應 |
| thinking | 思考泡泡（"..."） | 持續到思考結束 |
| message (新回覆) | 訊息前 50 字 | 9 秒後淡出 |
| sub_agent_start | "Delegating: [desc]" | 5 秒後淡出 |

### 6.6 Dashboard Sidebar

```
┌─────────────────────────┐
│ Agent Vista              │
├─────────────────────────┤
│ Sessions (5 active)      │
│ ┌─────────────────────┐ │
│ │ 🔵 Claude: workshop │ │
│ │   ├ typing: Edit    │ │
│ │   └ sub: explorer   │ │
│ │ 🟢 Codex: api-fix   │ │
│ │   └ running: bash   │ │
│ │ 🟣 Gemini: research │ │
│ │   └ idle (2m)       │ │
│ └─────────────────────┘ │
├─────────────────────────┤
│ Tokens Today             │
│ Claude:  45,230  $0.67  │
│ Codex:   12,100  $0.18  │
│ Gemini:   8,450  $0.04  │
│ Total:   65,780  $0.89  │
├─────────────────────────┤
│ Resources                │
│ CPU: ██░░░░░ 14%        │
│ RAM: ████░░░ 58%        │
└─────────────────────────┘
```

---

## 7. Session Discovery 規格

### 7.1 掃描策略

```
每 2 秒執行一次 discovery scan：

Claude Code:
  glob: ~/.claude/projects/*/conversations/*.jsonl
  排序: mtime desc
  取: 最近 30 分鐘內有修改的檔案

Codex CLI:
  glob: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
  YYYY/MM/DD: 今天 + 昨天
  排序: mtime desc
  取: 最近 30 分鐘內有修改的檔案

Gemini CLI:
  glob: ~/.gemini/tmp/*/chats/session-*.json
  排序: mtime desc
  取: 最近 30 分鐘內有修改的檔案
```

### 7.2 Session 生命週期

| 狀態 | 條件 | 視覺表現 |
|------|------|---------|
| **active** | 最近 60 秒內有檔案更新 | 角色在座位工作 |
| **idle** | 60 秒 - 30 分鐘無更新 | 角色起身漫遊 |
| **offline** | >30 分鐘無更新 | 角色 despawn（數位雨特效） |
| **new** | 新偵測到的 session | 角色 spawn（數位雨特效） |

### 7.3 Claude Code `/clear` 處理

Claude Code 執行 `/clear` 時會產生新 JSONL 檔案。偵測方式：
- 同一 `project-hash` 目錄下出現新 `.jsonl` 檔案
- 將現有 agent 重新綁定到新檔案（保留 agent ID 和位置）

---

## 8. 效能預算

| 指標 | 預算 |
|------|------|
| Go daemon RAM (idle) | <20 MB |
| Go daemon CPU (idle) | <0.5% |
| Go daemon CPU (burst, 50 events/s) | <2% |
| Frontend FPS | ≥30 fps (≤20 agents) |
| 事件延遲 (檔案變更 → 前端更新) | <200ms |
| 啟動時間 | <100ms |
| Binary size | <15 MB |

---

## 9. 佈局持久化

### 9.1 儲存格式

檔案: `~/.agent-vista/layout.json`

支援兩種定位模式：
- **Tile mode** (預設): 像素風格格座標，確保視覺一致性
- **Free mode** (可選): 百分比定位，支援自由拖拽

### 9.2 預設佈局

首次啟動時自動生成預設佈局：
- 多房間辦公室（50×34 tiles）：Code Studio、Research Lab、Build Lab、Break Room，十字走廊連接
- 預設家具（12 桌 24 座 + 休息室 + 13 種傢俱類型）
- Agent 依偵測順序自動分配座位

---

## 10. 實作路線圖

### Phase 0 — Backbone（1-2 天）

目標：驗證「讀 transcript → 推到瀏覽器」可行

- [ ] Go module init + 基本目錄結構
- [ ] Claude JSONL parser（增量讀取 + tool_start/tool_done）
- [ ] fsnotify file watcher
- [ ] 最簡 WebSocket server（推送 raw AgentEvent JSON）
- [ ] 靜態 HTML 頁面，console.log 接收事件
- [ ] 驗收：開一個 Claude Code session，瀏覽器即時顯示 tool 事件

### Phase 1 — Three Parsers（3-5 天）

目標：三 CLI 統一監控

- [ ] Codex JSONL parser（rollout 格式）
- [ ] Gemini JSON parser（diff-based）
- [ ] Session Discovery（三目錄掃描 + 生命週期管理）
- [ ] 統一 AgentEvent 模型 + init 訊息
- [ ] Process monitor（gopsutil，每 5 秒快照）
- [ ] REST API（/api/agents, /api/stats）
- [ ] 驗收：同時跑三個 CLI，瀏覽器看到三種事件流

### Phase 2 — Pixel Office（5-7 天）

目標：Pixel Agents 等級的視覺效果

- [ ] React + Vite 專案初始化
- [ ] Canvas 2D 渲染引擎（tiles, Z-sort, 相機控制）
- [ ] Sprite 系統（載入 + 快取 + 著色）
- [ ] 角色 FSM（6 態 + 動畫幀選擇）
- [ ] BFS pathfinding（IDLE 漫遊）
- [ ] WebSocket 連線 + AgentEvent → 角色狀態更新
- [ ] CLI 類型色系 + hue-shift 個體區分
- [ ] 對話泡泡 + tool overlay
- [ ] Spawn/Despawn 特效
- [ ] 驗收：像素辦公室中看到三種 CLI 的 agent 角色即時工作

### Phase 3 — Dashboard + Polish（3-5 天）

目標：完整的使用體驗

- [ ] Dashboard sidebar（session 列表 + token 統計 + resource）
- [ ] 佈局編輯器（放置家具、調整座位）
- [ ] 佈局持久化（~/.agent-vista/layout.json）
- [ ] 多辦公室支援
- [ ] Sub-agent 視覺化（縮小版跟隨）
- [ ] 音效通知（permission needed 時）
- [ ] 命令列參數（--port, --no-browser, --layout-path）
- [ ] 驗收：日常使用 1 週，確認穩定性和實用性

---

## 11. 配置

### 11.1 命令列參數

```
agent-vista [flags]

Flags:
  --port      int     HTTP/WS 監聽埠（預設 8840）
  --no-browser        不自動開啟瀏覽器
  --layout    string  佈局檔案路徑（預設 ~/.agent-vista/layout.json）
  --verbose           詳細日誌
```

### 11.2 設定檔（可選）

`~/.agent-vista/config.toml`

```toml
[server]
port = 8840
auto_open_browser = true

[discovery]
scan_interval = "2s"
idle_timeout = "30m"
active_window = "60s"

[parsers.claude]
enabled = true
path = "~/.claude/projects"

[parsers.codex]
enabled = true
path = "~/.codex/sessions"

[parsers.gemini]
enabled = true
path = "~/.gemini/tmp"

[display]
default_fps = 30
max_agents = 30
```

---

## 12. 測試策略

| 層級 | 方法 |
|------|------|
| Parser 單元測試 | 準備固定 JSONL/JSON 樣本，驗證解析正確性 |
| Discovery 整合測試 | 建立臨時 transcript 目錄結構，驗證偵測/清理 |
| WebSocket 整合測試 | 啟動 server → 連線 → 注入 transcript 行 → 驗證事件 |
| 視覺驗證 | **真實執行**：同時跑三 CLI，目視確認角色狀態正確 |

**不做**: mock test, smoke test（遵循少爺偏好）

---

## 13. 風險登記

| # | 風險 | 影響 | 機率 | 緩解 |
|---|------|------|------|------|
| R1 | Gemini JSON 非 append-only | 需全檔重解析 | 確定 | `lastUpdated` diff + 小檔案可接受 |
| R2 | Codex CLI 無 hook | 無法即時攔截 | 確定 | File watching 已足夠（即時寫入） |
| R3 | Claude JSONL 格式變更 | Parser 壞掉 | 低 | 版本偵測 + graceful degradation |
| R4 | Canvas 效能 >20 agents | 掉幀 | 低 | 視口裁剪 + rAF 節流 |
| R5 | Go 生態不熟 | 開發變慢 | 中 | ~1000 行核心碼，複雜度可控 |
| R6 | Pixel art 素材製作耗時 | Phase 2 延期 | 中 | 初期用簡化 sprite，迭代精修 |
