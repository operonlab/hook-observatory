// Agent state store — character FSM contexts driven by WS events

import { create } from 'zustand';
import type { AgentState, AgentStatus } from '../types/agent';
import type { AgentEvent } from '../types/event';
import { createFSM, eventToAnim, eventToBubble, eventToFullBubble, bubbleDuration, enqueueBubble, type FSMCtx } from '../engine/CharacterFSM';
import { useOfficeStore } from './officeStore';
import { cliToRoom } from '../engine/TileMap';

export interface TokenBreakdown {
  input: number;
  output: number;
  cached: number;
}

export interface AgentEntry {
  agent: AgentState;
  fsm: FSMCtx;
  tokenBreakdown: TokenBreakdown;
  projectDir: string; // working directory / project path
}

interface AgentStoreState {
  agents: Map<string, AgentEntry>;
  initAgents: (list: AgentState[]) => void;
  applyEvent: (evt: AgentEvent) => void;
  agentOnline: (agent: AgentState) => void;
  agentOffline: (id: string) => void;
  agentResting: (id: string) => void;
}

/** Map agent status (from backend) to FSM animation state. */
function statusToFSMState(status: AgentStatus, hasTool: boolean): FSMCtx['state'] {
  switch (status) {
    case 'active':
    case 'typing':
    case 'reading':
      return hasTool ? 'TYPE' : 'IDLE';
    case 'thinking':
      return 'THINK';
    case 'waiting':
      return 'WAIT';
    case 'error':
      return 'ERROR';
    default:
      return 'IDLE';
  }
}

/** Set FSM bubble from loaded agent state (initial load, not from events). */
function initFSMFromAgent(agent: AgentState, fsm: FSMCtx) {
  const state = statusToFSMState(agent.status, !!agent.current_tool);
  // Don't override state during spawn walk — it will take effect once seated
  // Store desired state for after walk completes
  if (agent.current_tool) {
    fsm.bubble = eventToBubble('tool_start', agent.current_tool, agent.tool_detail) ?? agent.current_tool;
    fsm.bubbleFull = eventToFullBubble('tool_start', agent.current_tool, agent.tool_detail);
    fsm.bubbleTimer = 60000; // Long-lived since this is pre-existing state
  } else if (agent.status === 'thinking') {
    fsm.bubble = '思考中...';
    fsm.bubbleTimer = 60000;
  }
  // The FSM state will be set after the agent finishes walking to seat
  // We store it in a post-walk callback via a small delay
  if (state !== 'IDLE') {
    // Set state directly — the Renderer's TYPE/THINK handler will walk agent to seat if needed
    fsm.state = state;
  }
}

export const useAgentStore = create<AgentStoreState>((set, get) => ({
  agents: new Map(),

  initAgents(list) {
    const office = useOfficeStore.getState();

    // Dedup by agent.id (keep first occurrence)
    const seen = new Set<string>();
    const deduped = list.filter(a => {
      if (seen.has(a.id)) return false;
      seen.add(a.id);
      return true;
    });

    // Separate active and inactive agents
    const active = deduped.filter(a => a.status !== 'offline' && a.status !== 'resting');
    const inactive = deduped.filter(a => a.status === 'offline' || a.status === 'resting');

    const agents = new Map<string, AgentEntry>();

    // Place inactive agents at rest spots (no spawn animation)
    for (const a of inactive) {
      const restSpot = office.claimRestSpot(a.id);
      const pos = restSpot ? { x: restSpot.x, y: restSpot.y } : null;
      const fsm = createFSM(pos, null);
      fsm.spawning = false;
      fsm.spawnT = 1;
      fsm.bubble = 'zzZ';
      fsm.bubbleTimer = 999999;
      fsm.zone = 'rest';
      agents.set(a.id, { agent: a, fsm, tokenBreakdown: { input: 0, output: 0, cached: 0 }, projectDir: '' });
    }

    // Place active agents directly at their seats (no door animation on page load).
    // Only truly NEW agents (via agentOnline) get the door entrance animation.
    for (const a of active) {
      const room = cliToRoom(a.cli_type);
      const seat = office.claimSeat(a.id, room);
      const seatPos = seat ? { x: seat.tileX, y: seat.tileY } : null;
      const fsm = createFSM(seatPos, null); // null spawnAt → starts at seat
      fsm.spawning = false;
      fsm.spawnT = 1;
      fsm.zone = room;
      initFSMFromAgent(a, fsm);
      agents.set(a.id, { agent: a, fsm, tokenBreakdown: { input: 0, output: 0, cached: 0 }, projectDir: '' });
    }

    set({ agents });
  },

  agentOnline(agent) {
    const { agents } = get();
    if (agents.has(agent.id)) return;
    const office = useOfficeStore.getState();
    const room = cliToRoom(agent.cli_type);
    const seat = office.claimSeat(agent.id, room);
    const seatPos = seat ? { x: seat.tileX, y: seat.tileY } : null;
    // Spawn at door, FSM will walk to seat
    const doorPos = office.door;
    const fsm = createFSM(seatPos, doorPos);
    fsm.zone = room;
    const next = new Map(agents);
    next.set(agent.id, { agent, fsm, tokenBreakdown: { input: 0, output: 0, cached: 0 }, projectDir: '' });
    set({ agents: next });
  },

  agentResting(id) {
    const { agents } = get();
    const entry = agents.get(id);
    if (!entry) return;
    if (entry.agent.status === 'resting' || entry.agent.status === 'offline') return;
    if (entry.fsm.exitTarget || entry.fsm.despawning) return;
    const office = useOfficeStore.getState();
    // Transition to resting: release desk, claim rest spot, walk there
    entry.agent.status = 'resting';
    entry.fsm.state = 'IDLE';
    entry.fsm.bubble = 'zzZ';
    entry.fsm.bubbleTimer = 999999;
    entry.fsm.zone = 'rest';
    office.releaseSeat(id);
    const restSpot = office.claimRestSpot(id);
    if (restSpot) {
      entry.fsm.seat = { x: restSpot.x, y: restSpot.y };
    }
    const next = new Map(agents);
    next.set(id, { ...entry });
    set({ agents: next });
  },

  agentOffline(id) {
    const { agents } = get();
    const entry = agents.get(id);
    if (!entry) return;
    const office = useOfficeStore.getState();
    const wasResting = entry.agent.status === 'resting';
    // Clear sub-agents
    entry.fsm.subAgents = [];

    if (wasResting) {
      // Resting agents fade out in place — no long walk to door
      entry.fsm.seat = null;
      entry.fsm.despawning = true;
      entry.fsm.spawnT = 0;
      entry.fsm.state = 'IDLE';
      entry.fsm.path = [];
      entry.fsm.bubble = null;
      entry.fsm.bubbleTimer = 0;
      office.releaseRestSpot(id);
    } else {
      // Active agents walk to door for dramatic exit
      const doorPos = office.door;
      entry.fsm.exitTarget = doorPos;
      entry.fsm.state = 'WALK';
      entry.fsm.seat = null;
      office.releaseSeat(id);
    }

    const next = new Map(agents);
    next.set(id, { ...entry });
    set({ agents: next });

    // Wait for despawn animation to finish, then remove agent
    const checkDespawn = setInterval(() => {
      const e = get().agents.get(id);
      if (!e) { clearInterval(checkDespawn); return; }
      if (e.fsm.despawning && e.fsm.spawnT >= 1) {
        clearInterval(checkDespawn);
        const m = new Map(get().agents);
        m.delete(id);
        set({ agents: m });
      }
    }, 200);
    // Safety: force remove (shorter for fade-out, longer for walk)
    setTimeout(() => {
      clearInterval(checkDespawn);
      const m = new Map(get().agents);
      if (m.has(id)) {
        m.delete(id);
        set({ agents: m });
      }
    }, wasResting ? 3000 : 15000);
  },

  applyEvent(evt) {
    const { agents } = get();

    // ── Sub-agent lifecycle ──────────────────
    if (evt.event_type === 'sub_agent_start' && evt.agent_id) {
      const parentEntry = agents.get(evt.agent_id);
      if (parentEntry && !parentEntry.fsm.exitTarget && !parentEntry.fsm.despawning) {
        // Extract meaningful label: Task JSON → description, or metadata.description
        let label = 'sub';
        if (evt.tool_input) {
          try {
            const parsed = JSON.parse(evt.tool_input);
            label = (parsed.description ?? evt.tool_input).slice(0, 20);
          } catch {
            label = evt.tool_input.slice(0, 20);
          }
        }
        const desc = evt.metadata?.description as string | undefined;
        if (label === 'sub' && desc) label = desc.slice(0, 20);

        const subInfo = {
          id: `${evt.agent_id}:sub:${Date.now()}`,
          label,
          startTime: Date.now(),
        };
        // Cap at 8 sub-agents max
        const existing = parentEntry.fsm.subAgents ?? [];
        parentEntry.fsm.subAgents = [...existing.slice(-7), subInfo];
        const next = new Map(agents);
        next.set(evt.agent_id, { ...parentEntry });
        set({ agents: next });
      }
      return;
    }

    if (evt.event_type === 'sub_agent_end' && evt.agent_id) {
      const parentEntry = agents.get(evt.agent_id);
      if (parentEntry) {
        // Remove all sub-agents from parent
        parentEntry.fsm.subAgents = [];
        const next = new Map(agents);
        next.set(evt.agent_id, { ...parentEntry });
        set({ agents: next });
      }
      return;
    }

    // ── Normal agent event ───────────────────
    let entry = agents.get(evt.agent_id);

    // Don't process events for agents that are leaving or despawning
    if (entry && (entry.fsm.exitTarget || entry.fsm.despawning)) return;

    if (!entry) {
      // Agent not yet known — auto-create from event data
      const office = useOfficeStore.getState();
      const evtRoom = cliToRoom(evt.cli_type);
      const seat = office.claimSeat(evt.agent_id, evtRoom);
      const seatPos = seat ? { x: seat.tileX, y: seat.tileY } : null;
      const doorPos = office.door;
      const newAgent: AgentState = {
        id: evt.agent_id,
        cli_type: evt.cli_type,
        session_id: evt.session_id,
        display_name: `${evt.cli_type}-${(evt.session_id ?? evt.agent_id).slice(-4)}`,
        status: 'active',
        tokens_total: 0,
        last_active: Date.now(),
        position: { x: 0, y: 0 },
        animation: 'IDLE',
        sub_agents: [],
      };
      const projDir = (evt.metadata?.project_dir as string) ?? '';
      const newFsm = createFSM(seatPos, doorPos);
      newFsm.zone = evtRoom;
      entry = { agent: newAgent, fsm: newFsm, tokenBreakdown: { input: 0, output: 0, cached: 0 }, projectDir: projDir };
      const next = new Map(agents);
      next.set(evt.agent_id, entry);
      set({ agents: next });
      // Re-read agents so the rest of this handler sees the updated map
      return get().applyEvent(evt);
    }

    const { fsm, agent } = entry;

    if (evt.tokens) {
      agent.tokens_total = evt.tokens.total;
      entry.tokenBreakdown = {
        input: evt.tokens.input,
        output: evt.tokens.output,
        cached: evt.tokens.cached ?? 0,
      };
    }
    agent.last_active = Date.now();
    if (evt.tool_name) agent.current_tool = evt.tool_name;
    if (evt.tool_input) agent.tool_detail = evt.tool_input;
    // Extract project directory from event metadata
    const projDir = evt.metadata?.project_dir as string | undefined;
    if (projDir && !entry.projectDir) {
      entry.projectDir = projDir;
    }

    // If agent was resting, wake it up — reclaim desk seat in preferred room
    if (agent.status === 'resting') {
      const office = useOfficeStore.getState();
      office.releaseRestSpot(agent.id);
      const wakeRoom = cliToRoom(agent.cli_type);
      const seat = office.claimSeat(agent.id, wakeRoom);
      if (seat) {
        fsm.seat = { x: seat.tileX, y: seat.tileY };
      }
      fsm.zone = wakeRoom;
      agent.status = 'active';
    }

    const newAnim = eventToAnim(evt.event_type, evt.tool_name);
    if (newAnim !== fsm.state) {
      fsm.state = newAnim;
      fsm.stateTime = 0;
      fsm.frameIdx = 0;
      fsm.frameTimer = 0;
    }

    const bubbleText = eventToBubble(evt.event_type, evt.tool_name, evt.tool_input, evt.metadata);
    if (bubbleText) {
      const full = eventToFullBubble(evt.event_type, evt.tool_name, evt.tool_input, evt.metadata);
      enqueueBubble(fsm, bubbleText, full, bubbleDuration(evt.event_type));
    }

    if (evt.event_type === 'tool_done') {
      enqueueBubble(fsm, evt.tool_status === 'error' ? '✗ 失敗' : '✓ 完成', null, 2500);
    }
    if (evt.event_type === 'idle') {
      fsm.bubble = null;
      fsm.bubbleFull = null;
      fsm.bubbleTimer = 0;
      fsm.bubbleQueue = [];
      agent.current_tool = undefined;
      agent.tool_detail = undefined;
    }

    const next = new Map(agents);
    next.set(evt.agent_id, { agent: { ...agent }, fsm, tokenBreakdown: entry.tokenBreakdown, projectDir: entry.projectDir });
    set({ agents: next });
  },
}));

// Periodic check: mark agents as resting if idle > 20 min
const ACTIVE_TIMEOUT = 20 * 60 * 1000; // 20 min
setInterval(() => {
  const { agents } = useAgentStore.getState();
  const now = Date.now();
  const office = useOfficeStore.getState();
  let changed = false;
  const next = new Map(agents);

  for (const [id, entry] of next) {
    const elapsed = now - entry.agent.last_active;
    if (elapsed > ACTIVE_TIMEOUT && entry.agent.status !== 'resting' && entry.agent.status !== 'offline') {
      entry.agent.status = 'resting';
      entry.fsm.state = 'IDLE';
      entry.fsm.bubble = 'zzZ';
      entry.fsm.bubbleTimer = 999999;
      entry.fsm.zone = 'rest';
      // Release desk, claim rest spot
      office.releaseSeat(id);
      const restSpot = office.claimRestSpot(id);
      if (restSpot) {
        entry.fsm.seat = { x: restSpot.x, y: restSpot.y };
      }
      changed = true;
    }
  }

  if (changed) useAgentStore.setState({ agents: next });
}, 15000); // check every 15s
