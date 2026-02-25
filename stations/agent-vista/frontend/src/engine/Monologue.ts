// Inner Monologue — generates whimsical "inner thoughts" for idle agents

import { enqueueBubble } from './CharacterFSM';
import type { AgentEntry } from '../stores/agentStore';

// Monologue triggers: agent must be in a specific state for a minimum time
// and have no active bubble, and cooldown must have passed.

const COOLDOWN_MS = 45_000;    // 45s between monologues per agent
const MIN_STATE_MS = 15_000;   // Must be in same state for 15s+
const lastMonologue = new Map<string, number>();

const IDLE_THOUGHTS = [
  '摸魚時間到了～',
  '下班後要吃什麼呢...',
  '今天的進度還不錯',
  '☕ 來杯咖啡',
  '稍微休息一下吧',
  '這段 code 滿漂亮的',
  '需要重構嗎...不，YAGNI',
  '老闆不在，偷懶一下',
];

const THINK_THOUGHTS = [
  '這個 bug 藏在哪裡...',
  '讓我想想最佳方案',
  '架構要怎麼設計呢...',
  '有沒有更優雅的解法？',
  '文件上是這樣寫的嗎...',
  '邏輯好像對了，但是...',
  '如果改用另一種方法...',
  '99 個問題，但 git 不是其中之一',
];

const TYPE_THOUGHTS = [
  '手速全開！',
  '寫 code 中，勿擾',
  '這段應該能用',
  '型別系統是好朋友',
  '測試等等再寫（才怪）',
  '又一個 TODO...',
  'import import import...',
  '讓我們來重構吧',
];

const HIGH_TOKEN_THOUGHTS = [
  '老闆的信用卡在哭泣...',
  '燒 token 不手軟',
  '今天的額度快到了',
  'Token 消耗：速度與激情',
  '這對話越來越長了',
];

const SUB_AGENT_THOUGHTS = [
  '分身術！',
  '交給手下辦事',
  '多線程思考中',
  '一人分飾多角',
  '委派大師上線',
];

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

/**
 * Check if an agent should receive a monologue bubble.
 * Called once per render frame; returns quickly if conditions aren't met.
 */
export function tryMonologue(agentId: string, entry: AgentEntry): void {
  const { fsm } = entry;
  const now = Date.now();

  // Skip if agent is spawning, despawning, or exiting
  if (fsm.spawning || fsm.despawning || fsm.exitTarget) return;

  // Skip if currently showing a bubble (don't interrupt real events)
  if (fsm.bubble && fsm.bubbleTimer > 2000) return;

  // Skip if bubbles are queued
  if (fsm.bubbleQueue.length > 0) return;

  // Minimum state time
  if (fsm.stateTime < MIN_STATE_MS) return;

  // Cooldown
  const last = lastMonologue.get(agentId) ?? 0;
  if (now - last < COOLDOWN_MS) return;

  // Random chance: ~2% per frame-check (called at ~60fps, effective ~1.2/sec)
  if (Math.random() > 0.02) return;

  // Pick thought based on state and context
  let thought: string;

  // Sub-agent special case
  if (fsm.subAgents.length > 0) {
    thought = pick(SUB_AGENT_THOUGHTS);
  }
  // High token usage (> 100k)
  else if (entry.agent.tokens_total > 100_000 && Math.random() < 0.3) {
    thought = pick(HIGH_TOKEN_THOUGHTS);
  }
  // State-based thoughts
  else {
    switch (fsm.state) {
      case 'IDLE':
        thought = pick(IDLE_THOUGHTS);
        break;
      case 'THINK':
        thought = pick(THINK_THOUGHTS);
        break;
      case 'TYPE':
        thought = pick(TYPE_THOUGHTS);
        break;
      case 'WAIT':
        thought = '等待中...有人在嗎？';
        break;
      case 'ERROR':
        thought = '哎呀，出問題了...';
        break;
      default:
        return;
    }
  }

  // Inject as a soft bubble (short duration, won't block real events)
  enqueueBubble(fsm, `💭 ${thought}`, null, 5000);
  lastMonologue.set(agentId, now);
}
