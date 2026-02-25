# Agent Vista

> 像素風虛擬辦公室，即時視覺化本地所有 LLM CLI agent 的工作狀態。

**版本**: 0.1.0 | **狀態**: Lab / Pre-POC

---

## Features

- **即時三 CLI 視覺化** — 同時監控 Claude Code、Codex CLI、Gemini CLI 的工作狀態
- **零侵入架構** — 純讀取 transcript 檔案，不修改任何 CLI 工具，不攔截任何訊號
- **像素風辦公室** — 34x20 tile grid，13+ 種家具類型（辦公桌、白板、印表機、書架、置物櫃等）
- **6 狀態角色 FSM** — IDLE / WALK / TYPE / THINK / WAIT / ERROR，支援 4 方向精靈圖
- **Sub-agent 天使視覺化** — 子 agent 以天使精靈顯示在最上層
- **Agent 內心獨白** — 閒置 agent 隨機顯示思考泡泡（狀態相關台詞）
- **動態時鐘** — 畫布繪製時鐘，與系統時間同步，顯示時針與分針
- **休息室系統** — 含床、沙發、咖啡機、飲水機及隔間牆
- **語音氣泡** — 顯示工具呼叫狀態與訊息，點擊可展開完整內容（10 秒自動關閉）
- **Spawn/Despawn 特效** — Matrix 數位雨風格的出現與離開動畫
- **Dashboard 側欄** — Session 列表、Token 統計、系統資源監控
- **Layout 編輯器** — 右鍵拖曳家具、旋轉、縮放，佈局自動持久化
- **Chat Channel** — MMO 風格的活動記錄，可收合，記錄所有 agent 事件
- **自訂精靈圖** — 支援 `~/.agent-vista/sprites/` 目錄下的 PNG 自訂角色圖

---

## Quick Start

### Prerequisites

- Go 1.22+
- Node.js 20+ 與 npm

### Build & Run

**完整建置（單一 binary，含嵌入前端）**

```bash
# 安裝前端依賴
make install-frontend

# 建置前端 + 嵌入 + 編譯 Go binary
make build-all

# 執行
./bin/agent-vista
```

**開發模式（前後端分離）**

```bash
# Terminal 1：啟動 Go backend
make dev-backend

# Terminal 2：啟動 React frontend dev server
make dev-frontend
```

**僅建置 Go binary（dev mode，不含嵌入前端）**

```bash
make build
./bin/agent-vista
```

**執行測試**

```bash
make test          # 全部測試（backend + frontend）
```

### Access

開啟瀏覽器至 [http://localhost:8840](http://localhost:8840)

預設會自動開啟瀏覽器（可用 `--no-browser` 停用）。

---

## Architecture

```
Browser (React 19 + Canvas 2D)
    │ REST polling (1.5s) + WebSocket (init + events)
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

- **Backend**: Go daemon — 檔案監控 + transcript 解析 + WebSocket/REST
- **Frontend**: React 19 + Canvas 2D — 像素渲染 + FSM 動畫
- **Protocol**: REST polling（1.5s 輪詢）+ WebSocket（初始化 + 即時事件推送）

---

## Supported CLIs

| CLI | Transcript 格式 | Parser 策略 |
|-----|----------------|------------|
| Claude Code | JSONL（增量追加） | Offset-based chunking |
| Codex CLI | JSONL（增量追加） | Offset-based chunking |
| Gemini CLI | JSON（完整覆寫） | Diff-based（依 lastUpdated）|

---

## Configuration

**設定檔**: `~/.agent-vista/config.toml`

```toml
port = 8840
no_browser = false
verbose = false

[discovery]
scan_interval_ms = 2000
```

**佈局持久化**: `~/.agent-vista/layout.json`（自動儲存，atomic write）

**CLI flags**:

```
--port        監聽埠號（預設 8840）
--no-browser  不自動開啟瀏覽器
--verbose     詳細 log 輸出
--config      指定設定檔路徑
```

---

## Project Structure

```
agent-vista/
├── cmd/agent-vista/        # Go 入口點（main.go, flag parsing）
├── internal/
│   ├── protocol/           # 共享 Go 型別（AgentEvent, WS messages）[FROZEN]
│   ├── parser/
│   │   ├── parser.go       # TranscriptParser 介面 [FROZEN]
│   │   ├── claude/         # Claude JSONL parser
│   │   ├── codex/          # Codex JSONL parser
│   │   └── gemini/         # Gemini JSON diff parser
│   ├── discovery/          # Session 掃描（三 CLI 目錄）
│   ├── watcher/            # fsnotify 檔案監控
│   ├── broker/             # Event fan-out
│   └── server/             # HTTP/WebSocket server, REST API, AgentTracker
├── web/
│   └── embed.go            # go:embed 嵌入前端 dist
├── frontend/
│   ├── src/
│   │   ├── types/          # 共享 TypeScript 型別 [FROZEN]
│   │   ├── engine/         # Canvas 渲染引擎、FSM、Pathfinding
│   │   ├── sprites/        # 精靈圖模板、調色盤、自訂圖載入
│   │   ├── stores/         # Zustand stores（REST polling client）
│   │   └── components/     # Dashboard、ChatChannel、BubbleOverlay
│   └── index.html
├── testdata/               # 測試 fixtures [FROZEN]
├── Makefile
├── SPEC.md                 # 完整技術規格
└── PROGRESS.md             # 開發進度追蹤
```

---

## License

MIT
