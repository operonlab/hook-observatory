// Connection store — REST polling for events (replaces WebSocket streaming)

import { create } from 'zustand';
import { useAgentStore } from './agentStore';
import { useChatStore } from './chatStore';
import type { AgentState, AnimationState } from '../types/agent';
import type { CLIType, AgentEventType, AgentEvent } from '../types/event';
import { notificationService } from '../engine/NotificationService';
import { soundEngine } from '../engine/SoundEngine';

interface ConnectionState {
  status: 'disconnected' | 'connecting' | 'connected';
  connect: () => void;
  disconnect: () => void;
  startMock: () => void;
}

interface EventEntry {
  seq: number;
  event: AgentEvent;
  new_agent?: AgentState;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
let lastSeq = 0;

const API_BASE = window.location.origin;
const POLL_INTERVAL = 1500; // 1.5s

async function pollEvents() {
  try {
    const res = await fetch(`${API_BASE}/api/events?after=${lastSeq}`);
    if (!res.ok) return;
    const entries: EventEntry[] = await res.json();
    const store = useAgentStore.getState();

    for (const entry of entries) {
      if (entry.new_agent) {
        store.agentOnline(entry.new_agent);
        notificationService.notifySessionStart(
          entry.new_agent.cli_type,
          entry.new_agent.session_id ?? entry.new_agent.id,
        );
      }
      if (entry.event.event_type === 'session_end') {
        store.agentOffline(entry.event.agent_id);
        notificationService.notifySessionEnd(
          entry.event.cli_type,
          entry.event.session_id ?? entry.event.agent_id,
        );
      } else {
        store.applyEvent(entry.event);
        // Desktop notifications for critical events (C7)
        if (entry.event.event_type === 'tool_permission') {
          notificationService.notifyPermissionNeeded(
            entry.event.cli_type,
            entry.event.session_id ?? entry.event.agent_id,
          );
        }
      }
      useChatStore.getState().addEvent(entry.event);
      lastSeq = entry.seq;
    }
  } catch {
    // Fetch error — will retry next interval
  }
}

export const useWSStore = create<ConnectionState>((set, get) => ({
  status: 'disconnected',

  async connect() {
    if (get().status !== 'disconnected') return;
    set({ status: 'connecting' });

    try {
      // Fetch agents + latest seq in parallel
      const [agents, stats] = await Promise.all([
        fetch(`${API_BASE}/api/agents`).then(r => r.json()),
        fetch(`${API_BASE}/api/stats`).then(r => r.json()),
      ]);
      const store = useAgentStore.getState();
      // Filter out offline agents
      const visible = (agents as AgentState[]).filter(a => a.status !== 'offline');
      store.initAgents(visible);

      // Send synthetic chat events for initial agent state
      const chat = useChatStore.getState();
      const active = visible.filter(a => a.status !== 'resting');
      for (const a of active) {
        chat.addEvent({
          cli_type: a.cli_type, session_id: a.session_id, agent_id: a.id,
          timestamp: new Date().toISOString(), event_type: 'session_start',
        });
        if (a.current_tool) {
          chat.addEvent({
            cli_type: a.cli_type, session_id: a.session_id, agent_id: a.id,
            timestamp: new Date().toISOString(), event_type: 'tool_start',
            tool_name: a.current_tool, tool_input: a.tool_detail,
          });
        }
      }

      // Skip historical events — only poll NEW events from now on
      lastSeq = stats.latest_seq ?? 0;

      // Start polling for events
      pollTimer = setInterval(pollEvents, POLL_INTERVAL);
      set({ status: 'connected' });

      // Request desktop notification permission (C7)
      notificationService.requestPermission();
      // Start ambient soundscape (C4)
      soundEngine.startAmbient();
      soundEngine.startKeyClicks(() => {
        const agents = useAgentStore.getState().agents;
        let count = 0;
        for (const [, e] of agents) {
          if (e.fsm.state === 'TYPE') count++;
        }
        return count;
      });
    } catch {
      // Backend not available — retry after delay
      set({ status: 'disconnected' });
      setTimeout(() => get().connect(), 3000);
    }
  },

  disconnect() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    lastSeq = 0;
    soundEngine.stopAmbient();
    set({ status: 'disconnected' });
  },

  startMock() {
    const store = useAgentStore.getState();

    const mockAgents: AgentState[] = [
      mockAgent('claude-a3f9', 'claude', 'claude-a3f9', 'active', 'TYPE'),
      mockAgent('codex-019c', 'codex', 'codex-019c', 'thinking', 'THINK'),
      mockAgent('gemini-f54d', 'gemini', 'gemini-f54d', 'idle', 'IDLE'),
    ];

    store.initAgents(mockAgents);
    set({ status: 'connected' });

    // Start ambient soundscape in mock mode too (C4)
    soundEngine.startAmbient();
    soundEngine.startKeyClicks(() => {
      const agents = useAgentStore.getState().agents;
      let count = 0;
      for (const [, e] of agents) {
        if (e.fsm.state === 'TYPE') count++;
      }
      return count;
    });

    const tools = ['Read', 'Edit', 'Bash', 'Grep', 'Write', 'WebFetch', 'Task'];
    const toolInputs = ['src/App.tsx', 'internal/server/server.go', 'README.md', 'package.json', 'tsconfig.json', 'Makefile'];
    const thinkTexts = ['思考最佳方案中...', '分析依賴關係...', '規劃架構設計...', '評估效能影響...'];
    const msgTexts = ['正在分析程式碼結構...', '找到問題根源了', '修正已完成', '正在寫入測試...'];
    const eventTypes: AgentEventType[] = ['tool_start', 'tool_done', 'thinking', 'idle', 'message', 'sub_agent_start', 'sub_agent_end'];
    const pick = <T,>(arr: T[]) => arr[Math.floor(Math.random() * arr.length)];

    // Send initial session_start + first activity events (staggered to match queued entrance)
    mockAgents.forEach((a, i) => {
      // session_start → chat
      setTimeout(() => {
        useChatStore.getState().addEvent({
          cli_type: a.cli_type, session_id: a.session_id, agent_id: a.id,
          timestamp: new Date().toISOString(), event_type: 'session_start',
        });
      }, i * 1500);

      // First activity event 2s after entrance (guarantees bubble + chat visible)
      const firstEvents: AgentEventType[] = ['tool_start', 'thinking', 'message'];
      setTimeout(() => {
        const evtType = firstEvents[i % firstEvents.length];
        const tool = pick(tools);
        const evt: AgentEvent = {
          cli_type: a.cli_type, session_id: a.session_id, agent_id: a.id,
          timestamp: new Date().toISOString(), event_type: evtType,
          tool_name: evtType === 'tool_start' ? tool : undefined,
          tool_input: evtType === 'tool_start' ? pick(toolInputs) : undefined,
          tokens: { input: 1000, output: 500, total: 1500 },
          metadata: evtType === 'message' ? { text: pick(msgTexts) } : evtType === 'thinking' ? { text: pick(thinkTexts) } : undefined,
        };
        useAgentStore.getState().applyEvent(evt);
        useChatStore.getState().addEvent(evt);
      }, i * 1500 + 2000);
    });
    let activeIds = mockAgents.map(a => a.id);
    const offlineIds: string[] = [];

    setInterval(() => {
      // 5% chance: offline an active agent (walk to door + despawn)
      if (activeIds.length > 1 && Math.random() < 0.05) {
        const idx = Math.floor(Math.random() * activeIds.length);
        const offId = activeIds.splice(idx, 1)[0];
        offlineIds.push(offId);
        useAgentStore.getState().agentOffline(offId);
        const cliType = offId.startsWith('claude') ? 'claude' as CLIType : offId.startsWith('codex') ? 'codex' as CLIType : 'gemini' as CLIType;
        useChatStore.getState().addEvent({
          cli_type: cliType, session_id: `session-${offId}`, agent_id: offId,
          timestamp: new Date().toISOString(), event_type: 'session_end',
        });
        return;
      }
      // 3% chance: bring back an offline agent
      if (offlineIds.length > 0 && Math.random() < 0.03) {
        const offId = offlineIds.shift()!;
        const cliType = offId.startsWith('claude') ? 'claude' as CLIType : offId.startsWith('codex') ? 'codex' as CLIType : 'gemini' as CLIType;
        useAgentStore.getState().agentOnline({
          id: offId, cli_type: cliType, session_id: `session-${offId}`,
          display_name: offId, status: 'active', tokens_total: 0,
          last_active: Date.now(), position: { x: 0, y: 0 }, animation: 'IDLE', sub_agents: [],
        });
        activeIds.push(offId);
        return;
      }

      if (activeIds.length === 0) return;
      const agentId = activeIds[Math.floor(Math.random() * activeIds.length)];
      const evtType = eventTypes[Math.floor(Math.random() * eventTypes.length)];
      const tool = tools[Math.floor(Math.random() * tools.length)];
      const cliType = agentId.startsWith('claude') ? 'claude' as CLIType : agentId.startsWith('codex') ? 'codex' as CLIType : 'gemini' as CLIType;

      const mockEvt: AgentEvent = {
        cli_type: cliType,
        session_id: `session-${agentId}`,
        agent_id: agentId,
        timestamp: new Date().toISOString(),
        event_type: evtType,
        tool_name: evtType === 'tool_start' ? tool : undefined,
        tool_input: evtType === 'tool_start' ? pick(toolInputs) : undefined,
        tool_status: evtType === 'tool_done' ? 'success' as const : undefined,
        tokens: { input: 1000, output: 500, total: 1500 },
        metadata: evtType === 'message' ? { text: pick(msgTexts) } : evtType === 'thinking' ? { text: pick(thinkTexts) } : undefined,
      };
      useAgentStore.getState().applyEvent(mockEvt);
      useChatStore.getState().addEvent(mockEvt);
    }, 3000);
  },
}));

function mockAgent(
  id: string,
  cli: CLIType,
  name: string,
  status: AgentState['status'],
  anim: AnimationState,
): AgentState {
  return {
    id,
    cli_type: cli,
    session_id: `session-${id}`,
    display_name: name,
    status,
    tokens_total: Math.floor(Math.random() * 50000),
    last_active: Date.now(),
    position: { x: 0, y: 0 },
    animation: anim,
    sub_agents: [],
  };
}
