---
source_hash: 6e5c2999
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Agent Vista — LLM CLI Real-time Visualization Monitoring Platform

**Research Date**: 2026-02-24
**Status**: Lab / Pre-POC Research
**Inspiration Sources**:
- [pablodelucca/pixel-agents](https://github.com/pablodelucca/pixel-agents) — Pixel-style LLM agent visualization (VS Code Extension)
- [inventra/lazyoffice-opneclaw](https://github.com/inventra/lazyoffice-opneclaw) — Pixel-style virtual office AI Agent Dashboard
- [Avatar Console](~/Claude/apps/avatar-console) — Master's early multi-agent command console (V1 Prototype, migrated)

---

## I. Vision

To present **all running LLM CLI agents** on Master's computer (Claude Code sessions + sub-agents, Codex CLI, Gemini CLI)
as a pixel-style virtual office, providing an at-a-glance view of each agent's activity, operational needs, and resource consumption.

**Difference from Pixel Agents**:
- Pixel Agents = VS Code Extension, only supports Claude Code
- Agent Vista = **Standalone Web App**, supports three CLIs + system-level process monitoring

---

## II. Avatar Console Legacy Analysis (Master's V1 Prototype)

### Project Overview

**Avatar Console** is Master's early multi-agent command console, V1 located at `~/Claude/apps/avatar-console/`
(actual source code at `~/.openclaw/workspace/openclaw_avator/`).
It uses "paper-doll actors" as the core UI metaphor to manage multiple AI agents on a visual stage.

**Tech Stack**: Vue 3 + Pinia + Vite (Frontend) / FastAPI + SQLite (Backend) / SSE + Polling (Real-time Communication)

### Design Highly Overlapping with Agent Vista

| Avatar Console Existing Design | Corresponding Agent Vista Requirement | Inheritance Method |
|--------------------------------|-------------------------------------|--------------------|
| **Actor Stage Metaphor** — Actors have positions on a stage, drag to move | Agents have seats in a virtual office | Directly inherit concept, Canvas-based |
| **Status Indicator Lights** — idle/working/offline/error four states | Agent Status FSM | Expanded to IDLE/WALK/TYPE/THINK/WAIT/ERROR |
| **Message Bubbles** — Automatically display last message, fade out in 9 seconds | Conversation bubble overlay | Directly inherit, add tool name display |
| **SSE Real-time Push** — Avatar Channel + EventSource | WebSocket real-time push | Upgraded to WebSocket (bidirectional) |
| **Runtime Polling** — Poll session status every 3 seconds | Session Discovery periodic scanning | Inherit polling strategy, change to file watching |
| **Command System** — `/help`, `@mention` registry | Command interaction (optional) | Inheritable, not core |
| **Actor Store** — Pinia state management + LocalStorage persistence | Agent state management | Inherit dual-layer persistence mode |
| **Greenscreen Chroma Key** — BFS seed fill + Spill suppression (175 lines) | Custom avatar image processing | Directly reuse algorithm |
| **Drag-and-bind + Confirmation** — Dragging session to actor triggers confirmation | Session binding agent role | Inherit UX flow |
| **Adapter Middleware** — Decouple frontend from backend API complexity | Parser Adapter pattern | Inherit architectural pattern |

### Reusable Code

| Component | File | Lines | Reuse Value |
|-----------|------|-------|-------------|
| Greenscreen Chroma Key Algorithm | `frontend/.../lib/chromaKey.js` | 175 | **High** — Custom avatar image processing |
| API Client Pattern | `frontend/.../lib/api.js` | 200+ | **Medium** — REST client pattern reference |
| SSE Client | `frontend/.../lib/avatarChannel.js` | ~80 | **Medium** — EventSource handling pattern |
| State Persistence | `frontend/.../stores/actorStore.js` | 195 | **Medium** — LocalStorage + Server sync pattern |
| Runtime Polling | `frontend/.../stores/runtimeStore.js` | 185 | **Medium** — Polling strategy reference |

### Limitations of Avatar Console (to be surpassed by Agent Vista)

| Limitation | Description | Agent Vista Solution |
|------------|-------------|----------------------|
| **OpenClaw Binding** | Only supports OpenClaw Gateway API | Directly read transcript files, zero dependency |
| **CSS Rendering** | Actors are DOM elements + CSS transform | Canvas 2D pixel rendering (more fluid) |
| **No Process Monitoring** | Does not track CPU/Memory | gopsutil system-level monitoring |
| **No Token Statistics** | Only views message content | Extract token counts from transcripts |
| **Vue 3** | Frontend framework | Switch to React (unified with workshop workbench) |
| **Python Backend** | FastAPI + SQLite | Switch to Go (single binary daemon) |
| **Manual Binding** | Requires manually dragging session to actor | Automatic detection + automatic binding |

### Feature Specifications in SPEC.md Worth Adopting

Avatar Console's `SPEC.md` (208 lines) defines several features not yet implemented but worth realizing in Agent Vista:

1. **Broadcast Mode** — Send commands to all agents simultaneously
2. **Meeting Mode** (`#Meeting`) — Multi-agent collaborative discussion
3. **Parallel Task Mode** (`#ParallelTask`) — Split a task into multiple agents in parallel
4. **Usage Watchdog** — Provider usage monitoring + automatic switching (see `USAGE_WATCHDOG_PLAN.md` for details)

### Usage Watchdog Design (Integrable)

Avatar Console planned a smart provider switching system:
- Check remaining provider quota every 30 minutes
- ≤ 15% → Warning notification
- ≤ 5% → Automatically switch to fallback provider
- Provider priority: OpenAI → Google → GitHub Copilot
- Automatically check if high-priority providers recover after cooldown

**Agent Vista can integrate this as part of the Token/Cost Dashboard.**

---

## III. Pixel Agents Original Architecture Analysis

### Core Mechanism

```
Claude Code Terminal → JSONL transcript → fileWatcher (fs.watch + polling)
  → transcriptParser → postMessage → React + Canvas 2D → pixel character animation
```

### Tech Stack
- **Backend**: Node.js / TypeScript (VS Code Extension Host)
- **Frontend**: React 18 + Vite + Canvas 2D (pixel-perfect rendering)
- **Communication**: VS Code postMessage (bidirectional)

### Design Worth Borrowing

| Design | Details | Borrowing Value |
|--------|---------|-----------------|
| Incremental JSONL Reading | `fileOffset` + `lineBuffer` for partial lines | High — Direct copy pattern |
| Tool State FSM | `agentToolStart` / `agentToolDone` / `agentToolPermission` | High — Unified state abstraction for three CLIs |
| Permission Timer | 7s no progress → Determine permission wait | Medium — Different CLIs may need different thresholds |
| 300ms Debounce | Tool done delayed sending to prevent UI flicker | High — Directly adopt |
| Hue-shift Coloring | Sprite hue shift to distinguish different agents | High — Used to distinguish Claude/Codex/Gemini |
| Z-sort Rendering | Tiles → Furniture → Characters (sorted by y-coordinate depth) | Medium — Visual layering reference |

### Limitations (to be overcome)

1. **VS Code Binding** — Must decouple, change to independent web server + browser
2. **Claude Code Format Coupling** — `transcriptParser.ts` deeply tied to Claude JSONL structure
3. **No System-level Monitoring** — Does not track CPU/Memory/Token cost
4. **Single Entry Point** — Only launched from VS Code terminal, does not detect external processes

---

## III-B. LazyOffice Analysis (Pixel-style Virtual Office Dashboard)

### Project Overview

[inventra/lazyoffice-opneclaw](https://github.com/inventra/lazyoffice-opneclaw) is a **pixel-style virtual office Dashboard**,
visualizing AI Agent teams as pixel characters (called "sloths"), presenting their work status, task flow, skills, and memory in real-time within an office setting.

**Tech Stack**: Node.js + Express (Backend) / Vanilla JS + HTML + CSS (Frontend) / PostgreSQL (DB) / SSE (Real-time) / Docker

### Differences in Positioning from Pixel Agents

| | Pixel Agents | LazyOffice |
|---|---|---|
| **Platform** | VS Code Extension | Standalone Web App |
| **Backend** | Node.js (Extension Host) | Node.js + Express + PostgreSQL |
| **Frontend** | React + Canvas 2D | Vanilla JS + HTML/CSS |
| **Agent Detection** | Read Claude JSONL transcript | Scan `~/.clawdbot/agents/` directory |
| **Agent Management** | Read-only monitoring | Full CRUD (name, title, avatar, skills, memory) |
| **Task System** | None | Task CRUD + Task flow animation |
| **Dashboard** | None | Cost + Interaction + Security three dashboards |
| **Persistence** | `~/.pixel-agents/layout.json` | PostgreSQL + `office-layout.json` |

### Design Worth Borrowing for Agent Vista

| LazyOffice Design | Borrowing Value | Description |
|-------------------|-----------------|-------------|
| **Office Layout JSON Format** | **High** | `leftPct`/`topPct` (percentage positioning) + `direction` + `scale` + `zIndex` — More flexible than Pixel Agents' fixed grid seats |
| **Multi-office Support** | **High** | `offices[]` array supports multiple office scenes (can be used for partitioning: Claude zone/Codex zone/Gemini zone) |
| **Department Grouping Concept** | **Medium** | `departments` table — Agents can be grouped by CLI type or project |
| **Task Flow Animation** | **High** | `task_flows` records from_agent → to_agent, visualizes task flow between agents — Suitable for presenting sub-agent delegation |
| **Token Usage Log** | **High** | `token_usage_log` + `agent_daily_stats` — Directly aligned with Agent Vista's Token/Cost Dashboard |
| **Cost Dashboard** | **High** | 7-day trend, cost savings calculation, task completion volume — Can integrate ccusage data |
| **Interaction Dashboard** | **Medium** | Number of conversations, words processed, token usage, number of errors — Statistical dimensions reference |
| **Agent Inner Monologue** | **Low (Fun)** | Automatically generate Agent's "inner thoughts" based on daily statistics — Interesting but not core |
| **Memory File Management UI** | **Medium** | Browse/edit/create/download Agent memory — Can integrate Master's `memory/` system |
| **AI Avatar Generation** | **Low** | KIE.ai API generates Agent avatars — Not needed for pixel style |
| **Port Scanner** | **Low** | Security feature, unrelated to visualization monitoring |
| **Filesystem Agent Detection** | **High** | Directly scan `~/.clawdbot/agents/` to parse SOUL.md — Similar to Agent Vista scanning three CLI transcript directories |

### LazyOffice Layout Format (for Reference)

```json
{
  "offices": [{
    "id": "office_main",
    "name": "Main Office",
    "background": "office-bg.png",
    "sloths": [{
      "charId": "kevin",
      "name": "Kevin Assistant",
      "role": "Secretary/Commander",
      "leftPct": 45.2,
      "topPct": 77.1,
      "direction": "sw",
      "scale": 200,
      "zIndex": 10
    }]
  }]
}
```

**Advantages**: Percentage positioning (responsive), direction control, scaling control, layer control — More suitable for free layout than Pixel Agents' fixed grid (tile x/y).

Agent Vista can consider a **hybrid approach**: default to tile grid (pixel consistency), but support free positioning mode.

### LazyOffice Database Design (Token Tracking Part for Reference)

```sql
-- Tables related to Agent Vista
token_usage_log (agent_id, tokens_used, model, timestamp)
agent_daily_stats (agent_id, date, conversations, words_processed,
                   tokens_used, errors, compliments)
```

Agent Vista can use a similar structure to track token statistics parsed from transcripts.

### Limitations of LazyOffice (to be surpassed by Agent Vista)

| Limitation | Description |
|------------|-------------|
| **Clawdbot Binding** | Only supports OpenClaw/Clawdbot agent framework |
| **Non-Canvas Rendering** | Uses HTML/CSS to position pixel images, not true Canvas 2D |
| **No Transcript Parsing** | Does not read agent's real-time work logs, only configuration files |
| **No Incremental Monitoring** | Requires manual triggering of `POST /api/agents/detect`, not real-time detection |
| **Vanilla JS** | No frontend framework, difficult to maintain for large applications |
| **PostgreSQL Dependency** | Daemon requires PostgreSQL, increasing deployment complexity |

---

## IV. Investigation of Three CLI Transcript Formats

### 3.1 Claude Code

| Item | Content |
|------|---------|
| **Format** | JSONL (line-by-line append) |
| **Path** | `~/.claude/projects/<project-hash>/<session-id>.jsonl` |
| **Record Types** | `assistant`, `user`, `system`, `progress` |
| **Tool Tracking** | `tool_use` blocks (including id/name/input), `tool_result` blocks |
| **Sub-agent** | `agent_progress` record type tracks sub-agents within Task tool |
| **Hook System** | 9 events (PreToolUse, PostToolUse, etc.) |
| **Monitoring Method** | `fs.watch` + polling (Pixel Agents has verified feasibility) |
| **Real-time** | Real-time writing, delay ~10-100ms (OS FSEvents) |

### 3.2 Codex CLI

| Item | Content |
|------|---------|
| **Format** | JSONL (Rollout session files) |
| **Path** | `~/.codex/sessions/YYYY/MM/DD/rollout-{timestamp}-{uuid}.jsonl` |
| **Record Types** | `session_meta`, `response_item`, `event_msg`, `turn_context` |
| **Tool Tracking** | `function_call` (built-in tool) + `custom_tool_call` (MCP tool), including name/args/call_id |
| **Result Tracking** | `function_call_output` (stdout/stderr/exit code/wall time) |
| **Token Statistics** | `event_msg` type=`token_count`, including rate_limits |
| **Hook System** | None (only prepare-commit-msg git hook) |
| **Alternative Solution** | App Server JSON-RPC 2.0 protocol (item/started, item/completed notifications, etc.) |
| **Monitoring Method** | File watching (recommended) or App Server stdio |
| **Master's Data** | 79MB session data, 65 lines of history |

### 3.3 Gemini CLI

| Item | Content |
|------|---------|
| **Format** | JSON (single complete conversation file, continuously updates `lastUpdated`) |
| **Path** | `~/.gemini/tmp/<project-hash>/chats/session-{timestamp}-{id}.json` |
| **Message Types** | `user`, `gemini` |
| **Tool Tracking** | `toolCalls` array (id/name/args/result/status/timestamp) |
| **Thought Process** | `thoughts` array (subject/description/timestamp) |
| **Token Statistics** | per-message `tokens` object (input/output/cached/thoughts/tool/total) |
| **Hook System** | 11 events (BeforeTool/AfterTool/BeforeModel/AfterModel, etc.), protocol almost identical to Claude Code |
| **Activity Log** | JSONL format, requires `GEMINI_CLI_ACTIVITY_LOG_TARGET` to be enabled |
| **OpenTelemetry** | Native OTLP export support |
| **Master's Data** | 703 sessions, 31 project hashes |

### Format Uniformity Assessment

```
           Claude Code          Codex CLI           Gemini CLI
Format       JSONL (Append)      JSONL (Append)      JSON (Overwrite)
Real-time     Real-time           Real-time           Real-time (lastUpdated)
Hook       9 events             None                   11 events
OTel       None                   None                   Native support
Token      Yes                   Yes (rate_limits)     Yes (detailed categories)
```

**Key Finding**: All three have sufficient transcript data, but the formats are completely different. Requires **per-CLI parser adapter**.

---

## V. Unified Data Model Design (Draft)

```
AgentEvent {
  cli_type:    "claude" | "codex" | "gemini"
  session_id:  string
  timestamp:   ISO8601
  event_type:  "tool_start" | "tool_done" | "tool_permission"
             | "message" | "thinking" | "idle" | "waiting"
             | "session_start" | "session_end"
  tool_name?:  string          // Read, Bash, exec_command, run_shell_command...
  tool_input?: string          // Summary (truncated)
  tool_status?: "running" | "success" | "error"
  tokens?: {
    input:  number
    output: number
    total:  number
  }
  metadata?: Record<string, any>  // CLI-specific additional information
}
```

### Parser Adapter Interface

```
trait TranscriptParser {
  fn detect(path: &Path) -> bool;            // Is this file handled by me?
  fn parse_incremental(bytes: &[u8]) -> Vec<AgentEvent>;  // Incremental parsing
  fn session_info() -> SessionMeta;          // Session metadata
}
```

Three implementations: `ClaudeParser`, `CodexParser`, `GeminiParser`

---

## VI. Backend Selection Analysis

### Demand Scale

| Metric | Value |
|--------|-------|
| Monitored Files | 3-15 JSONL/JSON |
| WebSocket Connections | 1-3 browsers |
| Concurrent Sessions | 5-15 LLM agents |
| Event Frequency | ~1-50 events/s |

**This is a very low-load scenario**. The bottleneck is OS file event latency (~10-100ms), not language performance.

### Four Language Comparison

| | Rust | Go | Python | Bun/Node |
|---|---|---|---|---|
| **Memory (idle)** | ~3-6 MB | ~10-18 MB | ~50-90 MB | ~35-55 MB |
| **Latency (processing)** | <1 ms | <2 ms | <10 ms | <3 ms |
| **Compile/Startup** | ~1-3 min / <10ms | ~3-8s / <20ms | N/A / ~500ms | N/A / ~100ms |
| **Development Speed** | Slow (4 weeks to learn) | Fast (1 week to learn) | Fastest (familiar) | Fast |
| **Distribution** | Single binary | Single binary | Requires Python env | Requires Bun/Node |
| **File Monitoring** | notify (FSEvents) | fsnotify (kqueue) | watchdog | fs.watch |
| **WebSocket** | axum (tokio) | coder/websocket | FastAPI WS | Built-in |

### Recommendation: Go

**Core Reasons**:

1. **Best balance of development speed vs. performance** — 8s compile vs Rust's 3 minutes, POC iteration efficiency is 5-10 times faster
2. **goroutine naturally fits** — One goroutine per monitored file, model is simple and intuitive
3. **Single binary** — `go build` one line, native macOS arm64, zero friction distribution
4. **Performance far exceeds demand** — 50 events/s won't even register on CPU
5. **Community precedents** — Prometheus/Grafana/Loki and other monitoring tools are all Go

**If Master wants to use Rust**: Completely feasible, but initial completion time is estimated to be 3-4 times longer than Go.
If this is a "practice project for learning Rust", that's another good reason.

**Quick Prototype Alternative**: Python (FastAPI + watchdog), MVP can be out in 2 hours, but not suitable for long-term daemon.

### Go Tech Stack

```go
require (
    github.com/fsnotify/fsnotify v1.8.0      // File monitoring
    github.com/coder/websocket   v1.8.12     // WebSocket (successor to nhooyr)
    github.com/shirou/gopsutil/v3 v3.24.5    // Process monitoring
)
```

### Rust Tech Stack (Alternative)

```toml
notify = "8.2"             # File monitoring (FSEvents backend)
axum = "0.8"               # Web + WebSocket
tokio = "1"                # async runtime
serde = "1"                # JSON parsing
sysinfo = "0.32"           # Process monitoring
```

---

## VII. System Architecture Design

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
│  │  │ Parser  │ │
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2579ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2676ms
