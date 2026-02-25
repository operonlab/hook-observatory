// 6-state character FSM: IDLE / WALK / TYPE / THINK / WAIT / ERROR

import type { AnimationState } from '../types/agent';
import type { AgentEventType } from '../types/event';
import type { GridPos } from './Pathfinding';
import type { Direction } from '../sprites/templates';
import type { RoomId } from './TileMap';

export interface FSMCtx {
  state: AnimationState;
  pos: GridPos;           // current tile position
  pixelX: number;         // sub-tile pixel interpolation
  pixelY: number;
  target: GridPos | null; // walk target
  path: GridPos[];
  pathIdx: number;
  seat: GridPos | null;   // assigned seat (null if none)
  dir: Direction;
  stateTime: number;      // ms in current state
  wanderCd: number;       // ms until next idle wander
  frameIdx: number;       // current animation frame index
  frameTimer: number;     // ms since last frame advance

  // spawn/despawn
  spawning: boolean;
  despawning: boolean;
  spawnT: number;         // 0..1 progress

  // bubble
  bubble: string | null;
  bubbleFull: string | null; // full text (up to 200 chars) for expanded view
  bubbleTimer: number;       // ms remaining
  bubbleQueue: { text: string; full: string | null; timer: number }[];
  bubbleSetAt: number;       // timestamp when current bubble was set

  // door-based spawn/despawn
  exitTarget: GridPos | null; // walk-to-door target for offline exit

  // zone restriction for movement (room ID or legacy work/rest)
  zone: RoomId | 'work' | 'rest';

  // sub-agent angels (rendered near parent, not as separate characters)
  subAgents: { id: string; label: string; startTime: number }[];
}

export function createFSM(seat: GridPos | null, spawnAt?: GridPos | null): FSMCtx {
  const pos = spawnAt ? { ...spawnAt } : seat ? { ...seat } : { x: 5, y: 5 };
  return {
    state: 'IDLE',
    pos,
    pixelX: pos.x,
    pixelY: pos.y,
    target: null,
    path: [],
    pathIdx: 0,
    seat,
    dir: 'down',
    stateTime: 0,
    wanderCd: 2000 + Math.random() * 4000,
    frameIdx: 0,
    frameTimer: 0,
    spawning: true,
    despawning: false,
    spawnT: 0,
    bubble: null,
    bubbleFull: null,
    bubbleTimer: 0,
    bubbleQueue: [],
    bubbleSetAt: 0,
    exitTarget: null,
    zone: 'work',
    subAgents: [],
  };
}

/** Map an incoming event to the target animation state. */
export function eventToAnim(eventType: AgentEventType, _toolName?: string): AnimationState {
  switch (eventType) {
    case 'tool_start':
    case 'message':
    case 'sub_agent_start':
      return 'TYPE';
    case 'thinking':
      return 'THINK';
    case 'tool_permission':
    case 'waiting':
      return 'WAIT';
    case 'tool_done':
      return 'THINK'; // Agent processes result before next action
    case 'idle':
    case 'session_end':
    case 'sub_agent_end':
      return 'IDLE';
    default:
      return 'IDLE';
  }
}

/** Parse tool input JSON into human-readable detail. */
export function parseToolDetail(toolName?: string, rawInput?: string): string | null {
  if (!rawInput) return null;
  try {
    const obj = JSON.parse(rawInput);
    switch (toolName) {
      case 'Read': case 'Edit': case 'Write':
        return obj.file_path ? shortenPath(obj.file_path) : null;
      case 'Bash':
        return obj.command?.slice(0, 120) ?? null;
      case 'Grep':
        return `"${obj.pattern ?? ''}"${obj.path ? ` in ${shortenPath(obj.path)}` : ''}`;
      case 'Glob':
        return `${obj.pattern ?? ''}${obj.path ? ` in ${shortenPath(obj.path)}` : ''}`;
      case 'WebFetch':
        return obj.url?.slice(0, 80) ?? null;
      case 'WebSearch':
        return obj.query?.slice(0, 80) ?? null;
      case 'Task':
        return obj.description?.slice(0, 80) ?? obj.prompt?.slice(0, 80) ?? null;
      default: {
        const str = Object.values(obj).find(v => typeof v === 'string') as string | undefined;
        return str?.slice(0, 80) ?? rawInput.slice(0, 80);
      }
    }
  } catch {
    return rawInput.slice(0, 80);
  }
}

function shortenPath(p: string): string {
  const parts = p.split('/');
  return parts.length > 3 ? parts.slice(-3).join('/') : p;
}

/** Build bubble text from event. */
export function eventToBubble(
  eventType: AgentEventType,
  toolName?: string,
  toolInput?: string,
  metadata?: Record<string, unknown>,
): string | null {
  switch (eventType) {
    case 'tool_start': {
      const verb = toolVerb(toolName);
      const detail = parseToolDetail(toolName, toolInput);
      return detail ? `${verb} ${detail.slice(0, 30)}` : verb;
    }
    case 'tool_permission':
      return '需要授權！';
    case 'thinking': {
      const thought = metadata?.text as string | undefined;
      return thought ? thought.slice(0, 30) : '...';
    }
    case 'message': {
      const text = metadata?.text as string | undefined;
      return text ? text.slice(0, 30) : '回覆中...';
    }
    case 'sub_agent_start':
      return `委派: ${parseToolDetail('Task', toolInput)?.slice(0, 20) ?? ''}`;
    default:
      return null;
  }
}

/** Full bubble text for expanded view. */
export function eventToFullBubble(
  eventType: AgentEventType,
  toolName?: string,
  toolInput?: string,
  metadata?: Record<string, unknown>,
): string | null {
  switch (eventType) {
    case 'tool_start': {
      const verb = toolVerb(toolName);
      const detail = parseToolDetail(toolName, toolInput);
      return detail ? `${verb} ${detail}` : verb;
    }
    case 'thinking': {
      const text = metadata?.text as string | undefined;
      return text ?? '...';
    }
    case 'message': {
      const text = metadata?.text as string | undefined;
      return text ?? null;
    }
    case 'sub_agent_start':
      return parseToolDetail('Task', toolInput) ? `委派: ${parseToolDetail('Task', toolInput)}` : null;
    default:
      return null;
  }
}

function toolVerb(name?: string): string {
  switch (name) {
    case 'Read': return '讀取';
    case 'Edit': return '編輯';
    case 'Write': return '寫入';
    case 'Bash': return '執行';
    case 'Grep': return '搜尋程式碼';
    case 'Glob': return '搜尋檔案';
    case 'WebFetch': return '抓取網頁';
    case 'WebSearch': return '搜尋網頁';
    case 'Task': return '子任務';
    case 'AskUserQuestion': return '等待輸入';
    default: return name ? `使用 ${name}` : '工作中';
  }
}

/** Bubble duration in ms for an event type. */
export function bubbleDuration(eventType: AgentEventType): number {
  switch (eventType) {
    case 'tool_start': return 30000; // until tool_done
    case 'tool_permission': return 60000;
    case 'thinking': return 30000;
    case 'message': return 9000;
    case 'sub_agent_start': return 5000;
    default: return 0;
  }
}

/** Direction from current position toward a target tile. */
export function directionTo(from: GridPos, to: GridPos): Direction {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? 'right' : 'left';
  return dy > 0 ? 'down' : 'up';
}

// ── Bubble queue (3s minimum hold per message) ────────────

const BUBBLE_MIN_HOLD = 3000;

/** Enqueue a bubble message. Promotes immediately if no current bubble or 3s+ has passed. */
export function enqueueBubble(fsm: FSMCtx, text: string, full: string | null, timer: number) {
  fsm.bubbleQueue.push({ text, full, timer });
  if (fsm.bubbleQueue.length > 8) fsm.bubbleQueue = fsm.bubbleQueue.slice(-8);
  // Promote immediately if nothing showing or minimum hold has passed
  if (!fsm.bubble || Date.now() - fsm.bubbleSetAt >= BUBBLE_MIN_HOLD) {
    promoteBubble(fsm);
  }
}

/** Promote next queued bubble to display. Returns true if promoted. */
export function promoteBubble(fsm: FSMCtx): boolean {
  const next = fsm.bubbleQueue.shift();
  if (next) {
    fsm.bubble = next.text;
    fsm.bubbleFull = next.full;
    fsm.bubbleTimer = next.timer;
    fsm.bubbleSetAt = Date.now();
    return true;
  }
  return false;
}

/** Short status label for canvas bubble (derived from state + tool). */
export function shortCanvasLabel(state: FSMCtx['state'], currentTool?: string): string | null {
  switch (state) {
    case 'THINK': return '思考...';
    case 'WAIT': return '等待...';
    case 'TYPE': return shortToolLabel(currentTool) + '...';
    default: return null;
  }
}

function shortToolLabel(tool?: string): string {
  switch (tool) {
    case 'Read': return '讀取';
    case 'Edit': return '編輯';
    case 'Write': return '寫入';
    case 'Bash': return '執行';
    case 'Grep': case 'Glob': return '搜尋';
    case 'WebFetch': return '網頁';
    case 'WebSearch': return '搜尋';
    case 'Task': return '委派';
    case 'AskUserQuestion': return '等待';
    default: return '工作';
  }
}
