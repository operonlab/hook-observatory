# Agent Vista — SPR (Sparse Priming Representation)

## Identity
- Agent Vista = 獨立 Web App，像素風虛擬辦公室，即時視覺化所有本地 LLM CLI agent
- 目標 UI/UX：**Pixel Agents 的動畫效果**（Canvas 2D + sprite FSM + hue-shift + Z-sort + pixel-perfect）
- 定位：stations/ 級別的 standalone local tool，single binary daemon + 瀏覽器前端

## Problem
- 少爺同時開多個 Claude Code session + sub-agents + Codex CLI + Gemini CLI
- 無法一眼看到所有 agent 的即時狀態（在做什麼、是否需要操作、資源消耗）
- 現有方案都只支援單一 CLI 或非視覺化

## Core Insight
- 三個 CLI 都有本地 transcript 檔案可被動監控，格式不同但資訊充足
- Claude Code: JSONL 追加式（`~/.claude/projects/`），9 hook events
- Codex CLI: JSONL 追加式（`~/.codex/sessions/`），無 hook 但有 App Server JSON-RPC
- Gemini CLI: JSON 覆寫式（`~/.gemini/tmp/`），11 hook events + OTel 原生
- 零侵入 — 純讀檔案，不修改任何 CLI

## Architecture
- Backend: Go daemon（fsnotify + coder/websocket + gopsutil），<18MB RAM
- Frontend: React + Canvas 2D（Pixel Agents 風格像素渲染）
- Protocol: WebSocket 雙向，統一 AgentEvent 模型
- 模組：Session Discovery → File Watcher → Parser Adapters (x3) → Event Broker → WS Server

## Data Model
- AgentEvent: cli_type + session_id + timestamp + event_type + tool_name + tool_status + tokens
- Parser Adapter 介面: detect() + parse_incremental() + session_info()
- 三實作：ClaudeParser (JSONL 增量), CodexParser (JSONL 增量), GeminiParser (JSON diff)

## Visual Design (Target: Pixel Agents Style)
- Canvas 2D 像素完美渲染，整數縮放，不用 ctx.scale(dpr)
- Sprite 系統：2D hex 色彩陣列 → offscreen canvas → WeakMap zoom-level 快取
- 角色 FSM：IDLE → WALK → TYPE → THINK → WAIT → ERROR（6 態）
- 渲染層：tiles → seat indicators → Z-sort (家具+牆壁+角色) → 對話泡泡 → overlay
- 著色：CLI 類型色系 (Claude 藍/Codex 綠/Gemini 紫) + hue-shift 個體區分
- Sub-agents：縮小版 (50%) 跟隨主 agent
- 動畫映射：Write/Edit/Bash = 打字；Read/Grep/Glob = 閱讀；thinking = 思考
- BFS pathfinding 隨機漫遊（IDLE 態）
- Spawn/Despawn：Matrix 風格數位雨特效
- 300ms debounce 防 UI flicker

## Lineage (三源匯流)
- Pixel Agents → 渲染引擎（Canvas 2D, sprite, FSM, hue-shift, Z-sort, debounce）
- LazyOffice → 業務邏輯（多房間, % 定位, 任務流轉, token 統計, 部門分組）
- Avatar Console → UX 智慧（舞台隱喻, 狀態燈, 訊息泡泡, chromaKey, 輪詢策略）

## Constraints
- 效能：<20MB RAM, <1% CPU idle, <50 events/s
- 分發：single binary (go build), macOS arm64
- 螢幕：BenQ 2K 非 Retina
- 無 PostgreSQL 依賴（佈局 JSON 檔案, 統計 SQLite 或記憶體）
- 無 VS Code 依賴
- 無 framework 綁定（不依賴 OpenClaw/Clawdbot）

## Phases
- P0: Go + Claude JSONL → WebSocket → browser console 驗證
- P1: 三 CLI parser + session discovery + process monitor
- P2: React + Canvas 2D 像素辦公室 + agent FSM + 即時更新
- P3: Dashboard sidebar + token/cost + 佈局編輯 + 音效

## Graduation
- lab/agent-vista/ → stations/agent-vista/
- 可選整合 workshop workbench 前端
