# Agent Vista — Shared Progress

Last updated: 2026-02-25

## Convention
- Each worktree updates its own rows when completing tasks
- Read the other worktree's status before starting dependent work
- Status: `pending` → `in-progress` → `done` → `verified`

---

## Scaffold (main branch)

| # | Task | Status | Notes |
|---|------|--------|-------|
| S1 | Git init + repo | done | Independent repo under lab/ |
| S2 | Go module + deps | done | fsnotify, websocket, gopsutil, toml |
| S3 | Shared Go types (internal/protocol/) | done | AgentEvent, WS messages, AgentState |
| S4 | Parser interface | done | TranscriptParser in internal/parser/ |
| S5 | React + Vite project | done | frontend/ with pnpm |
| S6 | Shared TS types (frontend/src/types/) | done | Mirrors Go protocol |
| S7 | Test fixtures (testdata/) | done | Claude JSONL + Codex JSONL + Gemini JSON |
| S8 | Entry point (cmd/) | done | main.go with flag parsing |
| S9 | Makefile | done | build, dev-backend, dev-frontend, test |
| S10 | .gitignore + CLAUDE.md | done | Worktree ownership rules |
| S11 | PROGRESS.md | done | This file |
| S12 | Worktree branches | done | wt/backend + wt/frontend |

---

## Backend (wt/backend)

| # | Task | Status | Phase | Notes |
|---|------|--------|-------|-------|
| B1 | Claude JSONL Parser | done | P0 | 11 tests, 20 events from sample, incremental chunking verified |
| B2 | fsnotify File Watcher | done | P0 | Offset-based incremental read, parser factory pattern |
| B3 | WebSocket server (minimal) | done | P0 | /ws + /api/health, init msg + event broadcast |
| B4 | Codex JSONL Parser | done | P1 | 8 tests, 9 events from sample, function_call/output mapping |
| B5 | Gemini JSON Parser | done | P1 | 10 tests, 26 events, diff-based via lastMessageCount |
| B6 | Session Discovery | done | P1 | Three-dir scan (Claude/Codex/Gemini), 2s interval, 7 tests |
| B7 | Event Broker (fan-out) | done | P1 | Non-blocking fan-out, slow subscriber drop |
| B8 | REST API | done | P1 | /api/agents + /api/stats + /api/events (polling) + AgentTracker state machine |
| B9 | Process Monitor | done | P1 | gopsutil every 5s, WSResourceSnapshot broadcast |
| B10 | Layout persistence | done | P3 | ~/.agent-vista/layout.json, atomic write, 4 tests |
| B11 | Config TOML parsing | done | P3 | ~/.agent-vista/config.toml, partial merge, 4 tests |

---

## Frontend (wt/frontend)

| # | Task | Status | Phase | Notes |
|---|------|--------|-------|-------|
| F1 | Canvas 2D render engine | done | P2 | engine/Renderer.ts + Camera.ts + TileMap.ts, Z-sort + floor + culling |
| F2 | Sprite system | done | P2 | sprites/templates.ts + cache.ts, indexed-color → OffscreenCanvas |
| F3 | Character FSM (6 states) | done | P2 | engine/CharacterFSM.ts, state transitions + frame animation |
| F4 | BFS pathfinding | done | P2 | engine/Pathfinding.ts, idle random wander |
| F5 | REST polling client + store | done | P2 | stores/wsStore.ts, REST polling (1.5s) + mock mode |
| F6 | Event → animation mapping | done | P2 | CharacterFSM.ts eventToAnim + eventToBubble |
| F7 | CLI color scheme + hue-shift | done | P2 | sprites/palette.ts, 3 palettes + shiftPalette |
| F8 | Speech bubbles + overlays | done | P2 | Renderer.ts drawBubble ("...") + BubbleOverlay (click expand) |
| F9 | Spawn/Despawn effects | done | P2 | Renderer.ts drawSpawnEffect, matrix digital rain |
| F10 | Dashboard sidebar | done | P3 | components/Dashboard.tsx, session list + tokens |
| F11 | Layout editor | done | P3 | hooks/useLayoutEditor.ts, right-click drag + edit mode toggle |
| F12 | Sub-agent visualization | done | P3 | Angel sprites (topmost layer) + FSM subAgents array |
| F13 | Door portal entrance | done | P3 | TileMap door pos + Renderer drawDoor, walk-in/out animation |
| F14 | Name labels + CLI legend | done | P3 | CLI badge + 4-char session ID + bottom-left legend |
| F15 | Chat channel | done | P3 | ChatChannel.tsx, collapsible MMO-style activity log |
| F16 | Interactive bubble expand | done | P3 | BubbleOverlay.tsx, click-to-expand with 10s auto-close |
| F17 | Custom sprites | done | P3 | sprites/custom.ts, ~/.agent-vista/sprites/ PNG loader |

---

## Integration Milestones

| Milestone | Depends On | Status |
|-----------|-----------|--------|
| P0: Browser console shows Claude events | B1 + B2 + B3 | done |
| P1: Three CLI events in browser | B4-B9 | done |
| P2: Pixel office with live agents | B1-B9 + F1-F9 | done |
| P3: Full dashboard experience | All | done |
| P4: Production single binary | B1-B11 + F1-F17 | done |

---

## Production (P4)

| # | Task | Status | Notes |
|---|------|--------|-------|
| P4-1 | Go embed frontend | done | web/embed.go, `go:embed all:dist`, fs.Sub for SPA |
| P4-2 | SPA static file server | done | server.go spaHandler, index.html fallback |
| P4-3 | Auto-open browser | done | main.go openBrowser (darwin/linux/windows) |
| P4-4 | Build pipeline | done | `make build-all`: frontend → cp dist → go build with ldflags |
| P4-5 | Version injection | done | git describe → `-ldflags -X main.version` |
| P4-6 | Bug fixes (door exit, angels) | done | Renderer despawn trigger, updateIdle guard, subAgent cap |

---

## Post-P4 Enhancements

| # | Enhancement | Status | Notes |
|---|------------|--------|-------|
| E1 | Rest room system | done | Beds, sofas, coffee machine, water dispenser, partition wall |
| E2 | 4-direction character sprites | done | Up/down/left/right facing, direction preserved after stopping |
| E3 | Dynamic clock | done | Syncs with system time, hour + minute hands via canvas drawing |
| E4 | Agent inner monologue | done | Idle agents show random thought bubbles (state-based) |
| E5 | Usage watchdog | done | Token consumption warnings |
| E6 | 1.5x office expansion | done | 34×20 grid (was 24×14), 12 desks, 24 seats, 14 rest spots |
| E7 | New furniture types | done | Whiteboard, printer, filing cabinet, bookshelf |
| E8 | Dashboard scrolling | done | maxHeight + overflowY for agent list panel |
| E9 | Dead code cleanup | done | Removed unused LayoutManager, updated fallback defaults |
| E10 | Agent detail panel | done | Click character → right-side panel with identity, tokens, sub-agents, project |
| E11 | Sound notifications | done | Web Audio API synthesis — alert/ping/farewell/error/sparkle, mute toggle |
| E12 | Minimap | done | 136×80px overview, agent dots, viewport indicator, click-to-navigate, M key toggle |
| E13 | Multi-room office | done | 50×34 grid, 4 rooms (Code Studio/Research Lab/Build Lab/Break Room), cross corridors, room-based agent routing, 8 door portals, room labels, CLI→room mapping |
| E14 | Day/Night cycle | done | 5-phase ambient lighting, window glow, desk lamps, Dashboard indicator |
| E15 | Agent interactions | done | Corridor wave gesture when IDLE agents pass near each other |
| E16 | Ambient soundscape | done | Filtered white noise office hum + typing keyboard clicks |
| E17 | Desktop notifications | done | Browser Notification API for permission_needed, session start/end |
| E18 | Station graduation | done | lab/agent-vista → stations/agent-vista, v0.2.0 tag |
