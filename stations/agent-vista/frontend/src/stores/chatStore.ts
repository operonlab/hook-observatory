// Chat channel store — MMO-style activity log
import { create } from 'zustand';
import type { AgentEvent } from '../types/event';
import { parseToolDetail } from '../engine/CharacterFSM';

export interface ChatMessage {
  id: string;
  timestamp: number;
  cliType: string;
  agentName: string;  // e.g. "claude-52da"
  text: string;        // formatted message
  eventType: string;
}

interface ChatState {
  messages: ChatMessage[];
  isOpen: boolean;
  toggle: () => void;
  addEvent: (evt: AgentEvent) => void;
  clear: () => void;
}

const MAX_MESSAGES = 200;

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isOpen: true,

  toggle() {
    set({ isOpen: !get().isOpen });
  },

  addEvent(evt) {
    const text = formatEvent(evt);
    if (!text) return;

    const msg: ChatMessage = {
      id: `${evt.agent_id}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      timestamp: Date.now(),
      cliType: evt.cli_type,
      agentName: `${evt.cli_type}-${evt.session_id?.slice(-4) ?? '????'}`,
      text,
      eventType: evt.event_type,
    };

    const messages = [...get().messages, msg];
    if (messages.length > MAX_MESSAGES) messages.splice(0, messages.length - MAX_MESSAGES);
    set({ messages });
  },

  clear() {
    set({ messages: [] });
  },
}));

function formatEvent(evt: AgentEvent): string | null {
  switch (evt.event_type) {
    case 'session_start':
      return '上線了';
    case 'session_end':
      return '離線了';
    case 'tool_start': {
      const detail = parseToolDetail(evt.tool_name, evt.tool_input);
      return `使用 ${evt.tool_name ?? '工具'}${detail ? ` — ${detail}` : ''}`;
    }
    case 'tool_done': {
      const status = evt.tool_status === 'error' ? '(失敗)' : '(完成)';
      return `工具結束 ${status}`;
    }
    case 'thinking': {
      const thought = evt.metadata?.text as string | undefined;
      return thought ? thought.slice(0, 100) : '思考中...';
    }
    case 'message': {
      const text = evt.metadata?.text as string | undefined;
      return text ? text.slice(0, 150) : '回覆中...';
    }
    case 'sub_agent_start': {
      const desc = parseToolDetail('Task', evt.tool_input);
      return `委派子任務${desc ? `: ${desc}` : ''}`;
    }
    case 'sub_agent_end':
      return '子任務完成';
    case 'idle':
      return null;
    default:
      return null;
  }
}
