# Agent Vista — Feature Roadmap v2

**Created**: 2026-02-25
**Status**: A1-B4 Complete, A3 Complete — Route C next
**Baseline**: P0-P4 all done (46/46 tasks complete)

---

## Overview

Three implementation routes executed in order:

| Route | Focus | Items |
|-------|-------|-------|
| **A** | Polish & Graduation | Dead code cleanup, doc updates, README, station migration |
| **B** | Feature Enhancement | Agent click panel, sound notifications, minimap |
| **C** | Visual Evolution | (Future — day/night, weather, ambient sound) |

Execution order: `A1 → A2 → B1 → B2 → B3 → A3`

---

## A1: Dead Code Cleanup + Doc Update

**Goal**: Remove unused code paths, synchronize documentation with current state.

### Tasks

1. **Remove LayoutManager dead code** in `cmd/agent-vista/main.go`
   - `lm := server.NewLayoutManager(...)` is loaded but never connected to any endpoint
   - `/api/layout` uses `LayoutDB` (PostgreSQL), not the file-based manager
   - Remove: lines 78-92 (LayoutManager init, Load, verbose log)
   - Remove: `--layout` flag (no longer meaningful without LayoutManager in the serving path)

2. **Update PROGRESS.md**
   - Add post-P4 enhancement section with recent work:
     - Rest room system (beds, sofas, machines)
     - 4-direction character sprites
     - Dynamic clock with system time sync
     - Agent inner monologue
     - Usage watchdog
     - 1.5x office expansion (34x20)
     - New furniture (whiteboard, printer, cabinet, bookshelf)
     - Dashboard scrolling fix

3. **Update SPEC.md outdated references**
   - Section 9.2: "16x12 tiles" → "34x20 tiles (1.5x scaled)"
   - Section 2.1: Add REST polling note alongside WebSocket
   - Section 6.4: Note 4-direction sprites (was "4 directions" already, but implementation details changed)

### Files Modified
- `cmd/agent-vista/main.go`
- `PROGRESS.md`
- `SPEC.md`

---

## A2: README

**Goal**: Write a proper project README with installation, usage, and feature overview.

### Content Structure

```
# Agent Vista
> One-line description + pixel art banner concept

## Features
- Real-time visualization of Claude/Codex/Gemini CLI agents
- Zero-intrusion: read-only transcript monitoring
- 6-state character FSM with 4-direction sprites
- Dynamic office with 13+ furniture types
- Sub-agent angel visualization
- Inner monologue system
- REST + WebSocket real-time updates
- Layout editor with drag-and-drop

## Quick Start
- Prerequisites (Go 1.22+, Node 20+)
- Build: make build-all
- Run: ./agent-vista
- Open: http://localhost:8840

## Architecture
- Backend: Go daemon (file watching + parsing + WebSocket)
- Frontend: React 19 + Canvas 2D (pixel rendering + FSM)
- Protocol: REST polling (1.5s) + WebSocket events

## Configuration
- ~/.agent-vista/config.toml
- CLI flags

## Supported CLIs
- Claude Code (JSONL incremental)
- Codex CLI (JSONL incremental)
- Gemini CLI (JSON diff-based)
```

### Files Created
- `README.md`

---

## B1: Agent Click Interaction + Detail Panel

**Goal**: Click on a pixel character to open a detailed information panel.

### Design

```
┌─────────────────────────────────────────────┐
│                 Pixel Office                 │
│                                              │
│    👤 ← click                               │
│                                              │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────┐
│  Agent Detail Panel          │  ← slides in from right
├──────────────────────────────┤
│  🔵 Claude Code              │
│  Session: abc1 (workshop)    │
│  Status: ● Typing            │
│  Uptime: 2h 34m              │
│──────────────────────────────│
│  Token Usage                 │
│  Input:   45,230             │
│  Output:  12,100             │
│  Cached:   8,450             │
│  Total:   65,780             │
│──────────────────────────────│
│  Recent Tools                │
│  ✦ Edit config.ts    2s ago  │
│  ✦ Read package.json 5s ago  │
│  ✦ Bash npm test     12s ago │
│──────────────────────────────│
│  Sub-Agents (2)              │
│  ├ explorer (active)         │
│  └ worker (idle)             │
└──────────────────────────────┘
```

### Technical Implementation

1. **Hit Detection** (`engine/Renderer.ts`)
   - New method: `hitTest(canvasX, canvasY): string | null`
   - Convert canvas coords → world coords via camera inverse transform
   - Check each agent's bounding box (16×16 tiles × zoom)
   - Return agentId or null

2. **Click Handler** (`components/PixelCanvas.tsx`)
   - `onClick` event on canvas element
   - Call `renderer.hitTest(e.offsetX, e.offsetY)`
   - If hit → set `selectedAgentId` in store
   - If miss → clear selection

3. **Detail Panel Component** (`components/AgentDetailPanel.tsx`)
   - Zustand store: `selectedAgentId: string | null`
   - Panel renders when selectedAgentId is set
   - Pulls data from agentStore + wsStore
   - Sections: identity, tokens, recent tools, sub-agents
   - Close button + click-outside-to-dismiss
   - Slide-in animation (CSS transform)

4. **Selection Highlight** (`engine/Renderer.ts`)
   - Draw glowing border around selected agent
   - Pulsing animation (sin wave alpha)

### Files Modified/Created
- `frontend/src/engine/Renderer.ts` — hitTest method + selection highlight
- `frontend/src/components/PixelCanvas.tsx` — click handler
- `frontend/src/components/AgentDetailPanel.tsx` — **new** detail panel
- `frontend/src/stores/uiStore.ts` — **new** UI state (selectedAgentId, panelOpen)

---

## B2: Sound Notification System

**Goal**: Audio feedback for important agent events using Web Audio API.

### Sound Design

| Event | Sound | Description |
|-------|-------|-------------|
| `permission_needed` | Alert chime | Two-tone ascending (C5→E5), 300ms, repeats 2x |
| `session_start` | Welcome ping | Single soft ping (G4), 200ms |
| `session_end` | Farewell | Descending tone (E4→C4), 400ms |
| `error` | Error buzz | Low buzz (A3), 150ms, harsh timbre |
| `sub_agent_start` | Spawn sparkle | High sparkle (C6), 100ms |

### Technical Implementation

1. **Sound Engine** (`engine/SoundEngine.ts`)
   - Singleton AudioContext (lazy init on first user interaction)
   - Oscillator-based synthesis (no external audio files)
   - Methods: `playAlert()`, `playPing()`, `playError()`, `playSparkle()`
   - Master volume control (0-1)
   - Mute toggle

2. **Integration Points**
   - `CharacterFSM.ts` — trigger sounds on state transitions
   - `wsStore.ts` — trigger on permission_needed events

3. **UI Controls** (`components/Dashboard.tsx`)
   - Mute/unmute toggle button (speaker icon)
   - Volume slider (optional, v2)
   - Persist preference in localStorage

### Sound Synthesis Details

```typescript
// Alert chime example (permission_needed)
function playAlert(ctx: AudioContext) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.connect(gain).connect(ctx.destination);

  osc.type = 'sine';
  osc.frequency.setValueAtTime(523, ctx.currentTime);      // C5
  osc.frequency.setValueAtTime(659, ctx.currentTime + 0.15); // E5
  gain.gain.setValueAtTime(0.3, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);

  osc.start(ctx.currentTime);
  osc.stop(ctx.currentTime + 0.3);
}
```

### Files Created/Modified
- `frontend/src/engine/SoundEngine.ts` — **new** Web Audio synthesis
- `frontend/src/engine/CharacterFSM.ts` — sound triggers
- `frontend/src/stores/wsStore.ts` — event-based triggers
- `frontend/src/components/Dashboard.tsx` — mute toggle UI

---

## B3: Minimap

**Goal**: Small overview map showing the entire office with agent positions for quick navigation.

### Design

```
┌─────────────────┐
│ Minimap (120x70) │  ← bottom-right corner, semi-transparent
│ ┌───────┬──┐    │
│ │  ···  │  │    │  · = agent dot (colored by CLI type)
│ │  · ·  │  │    │  □ = viewport indicator
│ │ [□□□] │  │    │
│ │  ·    │  │    │
│ └───────┴──┘    │
└─────────────────┘
```

### Technical Implementation

1. **Minimap Canvas** (`components/Minimap.tsx`)
   - Separate `<canvas>` element, fixed position bottom-right
   - Size: 120×70px (proportional to 34×20 grid)
   - Background: simplified office floor (walls + rooms outline)
   - Agent dots: 3×3px circles, colored by CLI type
   - Viewport rectangle: white outline showing current camera view
   - Semi-transparent background (rgba overlay)

2. **Rendering Pipeline**
   - Render at 10fps (independent of main canvas)
   - Scale factor: minimap_width / (map_width * TILE * zoom)
   - Draw walls as dark lines
   - Draw furniture as subtle gray blocks
   - Draw agents as colored dots (blue/green/purple)
   - Draw camera viewport as white rectangle

3. **Interaction**
   - Click on minimap → pan camera to that position
   - Drag on minimap → continuous pan
   - Hover → show tooltip with agent count

4. **Toggle**
   - Keyboard shortcut: `M` to toggle minimap visibility
   - Button in Dashboard header

### Files Created/Modified
- `frontend/src/components/Minimap.tsx` — **new** minimap component
- `frontend/src/components/PixelCanvas.tsx` — integrate minimap, expose camera state
- `frontend/src/engine/Camera.ts` — add `getViewportRect()` method

---

## B4: Multi-Room Office

**Goal**: Expand single-room office into a 4-room complex with corridors, room-based agent routing.

### Layout (50×34 grid)

```
┌─────────────────────┬════┬─────────────────────────┐
│                     │    │                          │
│  Code Studio        │    │    Research Lab          │
│  (Claude agents)    │ V  │    (Gemini agents)       │
│  x:1-21, y:1-13    │ C  │    x:28-48, y:1-13      │
│  9 desks, 18 seats  │ O  │    9 desks, 18 seats    │
│                     │ R  │                          │
├──── door ───────────┤ R  ├──── door ───────────────┤
│════ HORIZONTAL CORRIDOR ══════════════════════════ │
├──── door ───────────┤ I  ├──── door ───────────────┤
│                     │ D  │                          │
│  Build Lab          │ O  │    Break Room            │
│  (Codex agents)     │ R  │    (Resting agents)      │
│  x:1-21, y:20-32   │    │    x:28-48, y:20-32     │
│  9 desks, 18 seats  │    │    beds/sofas/coffee     │
│                     │    │                          │
└─────────────────────┴════┴─────────────────────────┘
```

### Room Assignment
- Claude CLI → Code Studio (top-left)
- Codex CLI → Build Lab (bottom-left)
- Gemini CLI → Research Lab (top-right)
- Resting agents → Break Room (bottom-right)
- Overflow: any room with available seats

### Files Modified
- `frontend/src/engine/TileMap.ts` — complete rewrite (rooms, corridors, partitions, doors)
- `frontend/src/engine/Renderer.ts` — multi-room floor colors, 8 door portals, room labels
- `frontend/src/engine/Pathfinding.ts` — room-aware random walk
- `frontend/src/engine/CharacterFSM.ts` — zone type expanded to RoomId
- `frontend/src/stores/officeStore.ts` — room-preferred seat claiming
- `frontend/src/stores/agentStore.ts` — CLI-to-room routing
- `frontend/src/components/Minimap.tsx` — moved to top-left
- `internal/server/layout.go` — updated default dimensions

---

## A3: Station Graduation

**Goal**: Promote agent-vista from `lab/` experiment to `stations/` permanent tool.

### Tasks

1. **Move directory**: `lab/agent-vista/` → `stations/agent-vista/`
2. **Update Go module path**: `github.com/joneshong/agent-vista` (verify if change needed)
3. **Update workshop CLAUDE.md** if needed (stations listing)
4. **Final build verification**: `make build-all && make test`
5. **Git commit with milestone tag**: `v0.2.0` (post-feature-enhancement)

### Pre-graduation Checklist
- [x] All A1/A2/B1/B2/B3/B4 tasks complete
- [x] Build passes (`make build-all`)
- [x] Tests pass (`make test`) — Go 11 + Frontend 48 = 0 failures
- [x] README.md exists and is accurate
- [x] No dead code or stale configs
- [x] PROGRESS.md up to date
- [x] Directory moved: `lab/agent-vista/` → `stations/agent-vista/`
- [x] Workshop CLAUDE.md updated with agent-vista in stations list

---

## Future (Route C — Visual Evolution)

Not in current scope, documented for reference:

| # | Feature | Description |
|---|---------|-------------|
| C1 | Day/Night Cycle | Floor/wall tint changes with system time, window lighting |
| C2 | Agent Interactions | Wave on passing, group at whiteboard, coffee break together |
| C3 | Weather System | Sync with real weather API, rain/sun outside windows |
| C4 | Ambient Soundscape | Keyboard clicks, coffee machine hum, office white noise |
| C5 | Custom Avatars | Per-session hairstyle/accessory configuration |
| C6 | Timeline Replay | Historical playback of agent activity |
| C7 | Desktop Notifications | Notification API for critical events |
| C8 | Token Cost Dashboard | $ cost estimation per session/day/week |
