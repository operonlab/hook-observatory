// Connection store — WebSocket push (replaces REST polling)

import { create } from 'zustand';
import { useAgentStore } from './agentStore';
import { useChatStore } from './chatStore';
import { useResourceStore } from './resourceStore';
import type { AgentState } from '../types/agent';
import type { WSMessage } from '../types/ws';
import { notificationService } from '../engine/NotificationService';
import { soundEngine } from '../engine/SoundEngine';

interface ConnectionState {
  status: 'disconnected' | 'connecting' | 'connected';
  connect: () => void;
  disconnect: () => void;
  startMock: () => void;
}

// Derive API base from Vite base URL — works both in dev (/) and behind nginx (/apps/vista/)
const API_BASE = import.meta.env.BASE_URL.replace(/\/$/, '');
const AGENTS_CACHE_KEY = 'agent-vista-agents-cache';

// Derive WebSocket URL from current page location (handles ws:// and wss://)
function wsURL(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = location.host;
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  return `${proto}//${host}${base}/ws/events`;
}

// Module-level WS state (outside store to avoid stale closures)
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 30000; // 30s cap

function scheduleReconnect(connectFn: () => void) {
  if (reconnectTimer) return;
  const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY);
  reconnectAttempts++;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectFn();
  }, delay);
}

function processWSMessage(msg: WSMessage) {
  const store = useAgentStore.getState();
  const chat = useChatStore.getState();

  switch (msg.type) {
    case 'init': {
      if (!msg.init) return;
      const visible = msg.init.agents.filter(a => a.status !== 'offline');
      store.initAgents(visible);
      try { localStorage.setItem(AGENTS_CACHE_KEY, JSON.stringify(visible)); } catch { /* quota */ }

      // Synthetic chat events for initial agent state
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
      break;
    }

    case 'agent_online': {
      if (!msg.agent_online) return;
      store.agentOnline(msg.agent_online);
      notificationService.notifySessionStart(
        msg.agent_online.cli_type,
        msg.agent_online.session_id ?? msg.agent_online.id,
      );
      break;
    }

    case 'agent_offline': {
      if (!msg.agent_offline_id) return;
      // Find agent info before marking offline (for notification)
      const agents = store.agents;
      const entry = agents.get(msg.agent_offline_id);
      if (entry) {
        notificationService.notifySessionEnd(
          entry.agent.cli_type,
          entry.agent.session_id ?? msg.agent_offline_id,
        );
      }
      store.agentOffline(msg.agent_offline_id);
      break;
    }

    case 'event': {
      if (!msg.event) return;
      const evt = msg.event;

      if (evt.event_type === 'session_end') {
        store.agentOffline(evt.agent_id);
        notificationService.notifySessionEnd(
          evt.cli_type,
          evt.session_id ?? evt.agent_id,
        );
      } else if (evt.event_type === 'process_resting') {
        store.agentResting(evt.agent_id);
      } else {
        store.applyEvent(evt);
        if (evt.event_type === 'tool_permission') {
          notificationService.notifyPermissionNeeded(
            evt.cli_type,
            evt.session_id ?? evt.agent_id,
          );
        }
      }
      chat.addEvent(evt);
      break;
    }

    case 'resource_snapshot': {
      if (!msg.resource_snapshot) return;
      useResourceStore.getState().setProcesses(msg.resource_snapshot.processes);
      break;
    }
  }
}

export const useWSStore = create<ConnectionState>((set, get) => ({
  status: 'disconnected',

  async connect() {
    if (get().status !== 'disconnected') return;
    set({ status: 'connecting' });

    // SWR: show stale cached agents immediately while connecting
    try {
      const cached = localStorage.getItem(AGENTS_CACHE_KEY);
      if (cached) {
        const stale = JSON.parse(cached) as AgentState[];
        useAgentStore.getState().initAgents(stale);
      }
    } catch { /* ignore corrupt cache */ }

    // Fetch initial agents + stats via REST as fallback (pre-WS snapshot)
    // This ensures we have data even if WS init message is delayed.
    try {
      const [agents, stats] = await Promise.all([
        fetch(`${API_BASE}/api/agents`).then(r => r.json()),
        fetch(`${API_BASE}/api/stats`).then(r => r.json()),
      ]);
      const store = useAgentStore.getState();
      const visible = (agents as AgentState[]).filter(a => a.status !== 'offline');
      store.initAgents(visible);
      try { localStorage.setItem(AGENTS_CACHE_KEY, JSON.stringify(visible)); } catch { /* quota */ }

      // Pre-populate chat
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
      void stats; // latest_seq no longer needed — WS handles sequencing
    } catch {
      // Backend not available — still attempt WS (it will trigger reconnect on failure)
    }

    // Open WebSocket
    connectWS(get, set);

    // Request desktop notification permission (C7)
    notificationService.requestPermission();
    // Start ambient soundscape (C4) — deferred until user interaction
    soundEngine.enableAfterGesture();
    soundEngine.startAmbient();
    soundEngine.startKeyClicks(() => {
      const agents = useAgentStore.getState().agents;
      let count = 0;
      for (const [, e] of agents) {
        if (e.fsm.state === 'TYPE') count++;
      }
      return count;
    });
  },

  disconnect() {
    if (ws) {
      ws.onclose = null; // prevent reconnect loop
      ws.close(1000, 'user disconnect');
      ws = null;
    }
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    reconnectAttempts = 0;
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
    const eventTypes = ['tool_start', 'tool_done', 'thinking', 'idle', 'message', 'sub_agent_start', 'sub_agent_end'] as const;
    const pick = <T,>(arr: T[]) => arr[Math.floor(Math.random() * arr.length)];
    type CLIType = 'claude' | 'codex' | 'gemini';

    // Send initial session_start + first activity events (staggered to match queued entrance)
    mockAgents.forEach((a, i) => {
      setTimeout(() => {
        useChatStore.getState().addEvent({
          cli_type: a.cli_type, session_id: a.session_id, agent_id: a.id,
          timestamp: new Date().toISOString(), event_type: 'session_start',
        });
      }, i * 1500);

      const firstEvents = ['tool_start', 'thinking', 'message'] as const;
      setTimeout(() => {
        const evtType = firstEvents[i % firstEvents.length];
        const tool = pick(tools);
        useAgentStore.getState().applyEvent({
          cli_type: a.cli_type, session_id: a.session_id, agent_id: a.id,
          timestamp: new Date().toISOString(), event_type: evtType,
          tool_name: evtType === 'tool_start' ? tool : undefined,
          tool_input: evtType === 'tool_start' ? pick(toolInputs) : undefined,
          tokens: { input: 1000, output: 500, total: 1500 },
          metadata: evtType === 'message' ? { text: pick(msgTexts) } : evtType === 'thinking' ? { text: pick(thinkTexts) } : undefined,
        });
        useChatStore.getState().addEvent({
          cli_type: a.cli_type, session_id: a.session_id, agent_id: a.id,
          timestamp: new Date().toISOString(), event_type: evtType,
          tool_name: evtType === 'tool_start' ? tool : undefined,
          tool_input: evtType === 'tool_start' ? pick(toolInputs) : undefined,
          tokens: { input: 1000, output: 500, total: 1500 },
          metadata: evtType === 'message' ? { text: pick(msgTexts) } : evtType === 'thinking' ? { text: pick(thinkTexts) } : undefined,
        });
      }, i * 1500 + 2000);
    });

    let activeIds = mockAgents.map(a => a.id);
    const offlineIds: string[] = [];

    setInterval(() => {
      if (activeIds.length > 1 && Math.random() < 0.05) {
        const idx = Math.floor(Math.random() * activeIds.length);
        const offId = activeIds.splice(idx, 1)[0];
        offlineIds.push(offId);
        useAgentStore.getState().agentOffline(offId);
        const cliType = (offId.startsWith('claude') ? 'claude' : offId.startsWith('codex') ? 'codex' : 'gemini') as CLIType;
        useChatStore.getState().addEvent({
          cli_type: cliType, session_id: `session-${offId}`, agent_id: offId,
          timestamp: new Date().toISOString(), event_type: 'session_end',
        });
        return;
      }
      if (offlineIds.length > 0 && Math.random() < 0.03) {
        const offId = offlineIds.shift()!;
        const cliType = (offId.startsWith('claude') ? 'claude' : offId.startsWith('codex') ? 'codex' : 'gemini') as CLIType;
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
      const cliType = (agentId.startsWith('claude') ? 'claude' : agentId.startsWith('codex') ? 'codex' : 'gemini') as CLIType;

      const mockEvt = {
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

function connectWS(
  get: () => ConnectionState,
  set: (partial: Partial<ConnectionState>) => void,
) {
  if (ws) return; // already connecting/connected

  const url = wsURL();
  ws = new WebSocket(url);

  ws.onopen = () => {
    reconnectAttempts = 0;
    set({ status: 'connected' });
  };

  ws.onmessage = (e: MessageEvent) => {
    try {
      const msg = JSON.parse(e.data as string) as WSMessage;
      processWSMessage(msg);
    } catch {
      // Ignore malformed messages
    }
  };

  ws.onclose = (e: CloseEvent) => {
    ws = null;
    // 1000 = intentional close (user called disconnect())
    if (e.code === 1000) return;

    set({ status: 'disconnected' });
    // Auto-reconnect with exponential backoff
    scheduleReconnect(() => {
      if (get().status === 'disconnected') {
        set({ status: 'connecting' });
        connectWS(get, set);
      }
    });
  };

  ws.onerror = () => {
    // onclose will fire next; errors are handled there
    ws?.close();
  };
}

function mockAgent(
  id: string,
  cli: 'claude' | 'codex' | 'gemini',
  name: string,
  status: AgentState['status'],
  anim: AgentState['animation'],
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
